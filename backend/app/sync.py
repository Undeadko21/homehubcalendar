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
    d = {
        "person": source_cfg.get("person"),
        "color": None,
        "hidden": False,
        "private": bool(source_cfg.get("private", False)),
    }
    for rule in source_cfg.get("calendars", []) or []:
        match = str(rule.get("match", "")).lower()
        if match and match in name.lower():
            d.update({k: rule[k] for k in ("person", "color", "hidden", "private") if k in rule})
            break
    if not d["color"]:
        d["color"] = remote_color
    return d


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
            if s.get("person"):
                refs.add(s["person"])
            for r in s.get("calendars", []) or []:
                if r.get("person"):
                    refs.add(r["person"])
        for i, pid in enumerate(sorted(refs - existing)):
            self.db.upsert_person({"id": pid, "name": pid, "color": PALETTE[(len(existing) + i) % len(PALETTE)],
                                   "sort": 100 + i})

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
                    msg = f"{type(e).__name__}: {e}"
                    self.db.set_sync_status(sid, ok=False, error=msg[:500])
                    report[sid] = {"ok": False, "error": msg}
                    log.exception("Ошибка синхронизации %s", sid)
        finally:
            self.running = False
            self._lock.release()
            if self.on_change:
                self.on_change()
        return report
