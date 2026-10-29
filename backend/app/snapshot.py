"""Снимок состояния для телефона: то, что нужно виджету и напоминаниям, когда сервер дома недоступен.

Лежит на Яндекс.Диске в зашифрованном виде (см. cloud.py). Один и тот же JSON отдаётся и
напрямую по /api/snapshot, чтобы приложение разбирало его одним кодом.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import birthdays as bd, ops, reminders, widget
from .db import Database
from .events import EventService

VERSION = 2
HORIZON_DAYS = 7


def _compact(e: dict) -> dict:
    """Событие для офлайн-экрана телефона: без описаний, ссылок и родительского события поездки."""
    out = {k: e[k] for k in ("id", "uid", "title", "start", "end", "all_day", "location", "people", "recurring",
                             "escort", "escort_issue") if k in e}
    if e.get("duty"):
        out["duty"] = {"role": e["duty"]["role"], "parent": e["duty"]["parent"]["id"]}
    return out


def build(events: EventService, db: Database, tz: ZoneInfo, now: datetime | None = None) -> dict:
    now = (now or datetime.now(tz)).astimezone(tz)
    start = datetime.combine(now.date(), time(0), tz)
    evs = events.events(start, start + timedelta(days=HORIZON_DAYS + 1))
    people = {p["id"]: p for p in db.list_people() if not p["hidden"]}
    soon = bd.upcoming(db.birthdays(), evs, start.date(), 14)[:2]
    wid_events = [e for e in evs if datetime.fromisoformat(e["start"][:10]).date() < start.date() + timedelta(days=3)]
    return {
        "v": VERSION,
        "generated": now.isoformat(timespec="seconds"),
        "widget": widget.build(wid_events, people, tz, now, 3, None, soon),
        # lead=None: «за сколько минут» и «чьи поездки» выбирает каждый телефон сам
        "reminders": reminders.build(evs, db.birthdays(), now, tz, None, None, HORIZON_DAYS,
                                    reminders.load_rules(db), reminders.load_allday(db),
                                    [i for l in db.lists() for i in l["items"]], db.sync_status()),
        # --- для офлайн-экрана и команд с телефона (этап 2) ---
        "people": [{k: p.get(k) for k in ("id", "name", "color", "emoji", "needs_escort", "keywords")} for p in people.values()],
        "events": [_compact(e) for e in evs],
        "lists": db.lists(),
        "applied": ops.applied_ids(db)[-300:],
    }
