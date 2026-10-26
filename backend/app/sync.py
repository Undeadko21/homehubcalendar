"""Синхронизация: забираем календари из всех источников и складываем в базу."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .db import Database
from .sources import build_source

log = logging.getLogger(__name__)

PALETTE = ["#4f7cff", "#f2643d", "#22a06b", "#b45cf0", "#e8a400", "#0fa5b5", "#e0457b", "#7a8699"]


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

    def run(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"status": "already_running"}
        self.running = True
        report = {}
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
                    calendars = src.fetch()
                    total = 0
                    seen = set()
                    for rc in calendars:
                        key = f"{sid}/{rc.remote_id}"
                        seen.add(key)
                        self.db.touch_calendar(key, sid, rc.remote_id, rc.name,
                                               calendar_defaults(scfg, rc.name, rc.color))
                        self.db.replace_objects(key, rc.objects)
                        total += len(rc.objects)
                    # Календари, исчезнувшие из источника, очищаем (настройки остаются).
                    for cal in self.db.list_calendars():
                        if cal["source_id"] == sid and cal["key"] not in seen:
                            self.db.replace_objects(cal["key"], {})
                    self.db.set_sync_status(sid, ok=True, count=total)
                    report[sid] = {"ok": True, "calendars": len(calendars), "objects": total}
                    log.info("Синхронизирован %s: %d календарей, %d объектов", sid, len(calendars), total)
                except Exception as e:  # noqa: BLE001
                    msg = friendly_error(e)
                    self.db.set_sync_status(sid, ok=False, error=msg[:500])
                    report[sid] = {"ok": False, "error": msg}
                    log.exception("Ошибка синхронизации %s", sid)
        finally:
            self.running = False
            self._lock.release()
            if self.on_change:
                self.on_change()
        return report
