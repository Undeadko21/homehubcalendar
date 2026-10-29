"""Синхронизация: забираем календари из всех источников и складываем в базу."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .db import Database
from .sources import build_source

log = logging.getLogger(__name__)

PALETTE = ["#007aff", "#ff9500", "#34c759", "#af52de", "#ff2d55", "#00c7be", "#ff3b30", "#a2845e"]


def calendar_defaults(source_cfg: dict, name: str, remote_color: str | None) -> dict:
    """Значения по умолчанию для календаря: уровень источника + правила `calendars:`."""
    def as_list(v):
        if not v:
            return []
        return [v] if isinstance(v, str) else list(v)

    d = {
        "people": as_list(source_cfg.get("people")) or as_list(source_cfg.get("person")),
        "color": None,
        "hidden": False,
        "private": bool(source_cfg.get("private", False)),
    }
    for rule in source_cfg.get("calendars", []) or []:
        match = str(rule.get("match", "")).lower()
        if match and match in name.lower():
            d.update({k: rule[k] for k in ("color", "hidden", "private") if k in rule})
            if "people" in rule or "person" in rule:
                d["people"] = as_list(rule.get("people")) or as_list(rule.get("person"))
            break
    if not d["color"]:
        d["color"] = remote_color
    return d


def _norm_href(h: str) -> str:
    from urllib.parse import unquote, urlparse
    return unquote(urlparse(h).path).rstrip("/")


def _as_state(v) -> dict:
    """Раньше хранилась одна строка ctag, теперь {ctag, token}."""
    return v if isinstance(v, dict) else {"ctag": v, "token": None}


def friendly_error(e: Exception) -> str:
    """Понятное описание ошибки для интерфейса."""
    name = type(e).__name__
    text = str(e)
    low = (name + " " + text).lower()
    if "authorization" in low or "401" in low or "unauthorized" in low or "forbidden" in low or "403" in low:
        return "Неверный логин или пароль приложения. Проверьте, что пароль создан для «Календаря»."
    if any(s in low for s in ("connection", "timeout", "timed out", "name or service", "resolve", "proxy", "unreachable")):
        return "Нет связи с сервером календаря. Проверьте интернет на сервере и адрес источника."
    if isinstance(e, RuntimeError):
        return text
    return f"{name}: {text}"


class SyncEngine:
    def __init__(self, db: Database, sources: list[dict], on_change: Callable[[], None] | None = None):
        self.db = db
        self.sources = sources
        self.on_change = on_change
        self._lock = threading.Lock()
        self.running = False
        self._runs = 0

    def _apply_delta(self, key: str, rc) -> bool:
        """Накладывает изменения sync-collection. Адреса сравниваем по пути: сервер отдаёт то полный URL, то путь."""
        norm = _norm_href
        existing = self.db.objects_map(key)
        by_path = {norm(h): h for h in existing}
        changed = False
        for href, ics in rc.objects.items():
            old = by_path.get(norm(href), href)
            if existing.get(old) != ics:
                self.db.put_object(key, old, ics)
                changed = True
        for href in rc.deleted:
            old = by_path.get(norm(href))
            if old is not None:
                self.db.delete_object(key, old)
                changed = True
        return changed

    def seed_people(self, people: list[dict]) -> None:
        """Люди из config.yaml добавляются, если их ещё нет. Правки из интерфейса сохраняются."""
        existing = {p["id"] for p in self.db.list_people()}
        for i, p in enumerate(people):
            if p.get("id") and p["id"] not in existing:
                self.db.upsert_person({"color": PALETTE[i % len(PALETTE)], "sort": i, **p})
        # Люди, на которых ссылаются источники, но которых нет в списке, создаются автоматически.
        existing = {p["id"] for p in self.db.list_people()}
        refs = set()
        for s in self.sources:
            for item in [s, *(s.get("calendars", []) or [])]:
                for key in ("person", "people"):
                    v = item.get(key)
                    refs.update([v] if isinstance(v, str) else (v or []))
        for i, pid in enumerate(sorted(refs - existing)):
            self.db.upsert_person({"id": pid, "name": pid, "color": PALETTE[(len(existing) + i) % len(PALETTE)],
                                   "sort": 100 + i})

    def credentials(self, source_id: str) -> dict:
        """Логин и пароль, сохранённые через веб-интерфейс (хранятся в базе на сервере)."""
        value, _ = self.db.kv_get(f"auth:{source_id}")
        return value or {}

    def effective_config(self, scfg: dict) -> dict:
        """Конфиг источника с учётом учётных данных из интерфейса (они важнее пустых из config.yaml)."""
        creds = self.credentials(scfg.get("id", ""))
        out = dict(scfg)
        for k in ("username", "password"):
            if creds.get(k):
                out[k] = creds[k]
        return out

    def accounts(self) -> list[dict]:
        """Источники, которым нужны логин и пароль, без самих паролей."""
        out = []
        for s in self.sources:
            if s.get("type") != "caldav":
                continue
            eff = self.effective_config(s)
            out.append({"id": s["id"], "url": s.get("url", ""), "username": eff.get("username") or "",
                        "has_password": bool(eff.get("password"))})
        return out

    def set_credentials(self, source_id: str, username: str, password: str | None) -> None:
        if source_id not in {s.get("id") for s in self.sources}:
            raise KeyError(source_id)
        current = self.credentials(source_id)
        value = {"username": username.strip()}
        value["password"] = password if password else current.get("password", "")
        self.db.kv_set(f"auth:{source_id}", value)

    FULL_EVERY = 12   # раз в N запусков качаем всё, даже если ctag не менялся (страховка)

    def run(self, full: bool = False) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"status": "already_running"}
        self.running = True
        report = {}
        changed = False
        self._runs += 1
        full = full or self._runs % self.FULL_EVERY == 1
        state = self.db.kv_get("sync:ctags")[0] or {}
        try:
            for scfg in self.sources:
                sid = scfg.get("id", "?")
                if scfg.get("enabled", True) is False:
                    continue
                try:
                    scfg = self.effective_config(scfg)
                    if scfg.get("type") == "caldav" and not (scfg.get("username") and scfg.get("password")):
                        raise RuntimeError("не указаны логин и пароль приложения — откройте ⚙ Настройки → Учётные записи")
                    src = build_source(scfg)
                    known = {} if full else {k.split('/', 1)[1]: _as_state(v) for k, v in state.items() if k.startswith(sid + '/')}
                    calendars = src.fetch(known)
                    total = 0
                    seen = set()
                    for rc in calendars:
                        key = f"{sid}/{rc.remote_id}"
                        seen.add(key)
                        self.db.touch_calendar(key, sid, rc.remote_id, rc.name,
                                               calendar_defaults(scfg, rc.name, rc.color))
                        if rc.unchanged:
                            total += len(self.db.objects_map(key))
                            continue
                        if rc.delta:
                            if self._apply_delta(key, rc):
                                changed = True
                            total += len(self.db.objects_map(key))
                        else:
                            if self.db.objects_map(key) != rc.objects:
                                self.db.replace_objects(key, rc.objects)
                                changed = True
                            total += len(rc.objects)
                        if rc.ctag or rc.token:
                            state[key] = {"ctag": rc.ctag, "token": rc.token}
                        else:
                            state.pop(key, None)
                    # Календари, исчезнувшие из источника, очищаем (настройки остаются).
                    for cal in self.db.list_calendars():
                        if cal["source_id"] == sid and cal["key"] not in seen:
                            if self.db.objects_map(cal["key"]):
                                changed = True
                            self.db.replace_objects(cal["key"], {})
                            state.pop(cal["key"], None)
                    self.db.set_sync_status(sid, ok=True, count=total)
                    report[sid] = {"ok": True, "calendars": len(calendars), "objects": total}
                    log.info("Синхронизирован %s: %d календарей, %d объектов", sid, len(calendars), total)
                except Exception as e:  # noqa: BLE001
                    changed = True
                    msg = friendly_error(e)
                    self.db.set_sync_status(sid, ok=False, error=msg[:500])
                    report[sid] = {"ok": False, "error": msg}
                    log.exception("Ошибка синхронизации %s", sid)
        finally:
            self.db.kv_set("sync:ctags", state)
            self.running = False
            self._lock.release()
            if self.on_change and (changed or self._runs == 1):
                self.on_change()
        return report
