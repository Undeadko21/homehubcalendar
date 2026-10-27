"""Снимок состояния для телефона: то, что нужно виджету и напоминаниям, когда сервер дома недоступен.

Лежит на Яндекс.Диске в зашифрованном виде (см. cloud.py). Один и тот же JSON отдаётся и
напрямую по /api/snapshot, чтобы приложение разбирало его одним кодом.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import birthdays as bd, reminders, widget
from .db import Database
from .events import EventService

VERSION = 1
HORIZON_DAYS = 7


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
        "reminders": reminders.build(evs, db.birthdays(), now, tz, None, None, HORIZON_DAYS),
    }
