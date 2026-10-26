"""Поиск общего свободного времени для выбранных людей."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .escorts import duty_intervals


def _merge(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[list[datetime]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def find_free(events: list[dict], people: list[str], start: date, end: date, tz: ZoneInfo,
              day_from: time = time(8), day_to: time = time(22), min_minutes: int = 60,
              include_all_day: bool = False) -> list[dict]:
    """Окна, когда ВСЕ выбранные люди свободны одновременно, по дням [start, end).

    Занятость: события со временем (кроме отмеченных «свободен») с участием любого
    из людей, их поездки за детьми и — по желанию — события на весь день.
    """
    wanted = set(people)
    busy: list[tuple[datetime, datetime, dict]] = []
    for e in events:
        if e.get("duty"):
            continue  # поездки учитываются ниже через duty_intervals
        who = [p for p in e["people"] if p in wanted]
        if not who:
            continue
        if e["all_day"]:
            if include_all_day:
                s = datetime.combine(date.fromisoformat(e["start"]), time(0), tz)
                en = datetime.combine(date.fromisoformat(e["end"]), time(0), tz)
                busy.append((s, en, {"title": e["title"], "people": who, "all_day": True, "kind": "event",
                                     "event_start": e["start"], "event_end": e["end"]}))
            continue
        if not e.get("busy", True):
            continue
        busy.append((datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"]),
                     {"title": e["title"], "people": who, "all_day": False, "kind": "event",
                      "event_start": e["start"], "event_end": e["end"]}))
    for person, w0, w1, e, role in duty_intervals(events):
        if person in wanted:
            verb = "Отвезти" if role == "dropoff" else "Забрать"
            busy.append((w0, w1, {"title": f"{verb}: {e['title']}", "people": [person], "all_day": False,
                                  "kind": "escort", "event_start": w0.isoformat(), "event_end": w1.isoformat()}))

    days = []
    d = start
    while d < end:
        d0 = datetime.combine(d, day_from, tz)
        d1 = datetime.combine(d, day_to, tz) if day_to > day_from else datetime.combine(d + timedelta(days=1), time(0), tz)
        today_busy = [(max(s, d0), min(en, d1), info) for s, en, info in busy if s < d1 and en > d0]
        windows = []
        cursor = d0
        for s, en in _merge([(s, en) for s, en, _ in today_busy]):
            if (s - cursor).total_seconds() >= min_minutes * 60:
                windows.append((cursor, s))
            cursor = max(cursor, en)
        if (d1 - cursor).total_seconds() >= min_minutes * 60:
            windows.append((cursor, d1))
        days.append({
            "date": d.isoformat(),
            "from": d0.isoformat(),
            "to": d1.isoformat(),
            "windows": [{"start": s.isoformat(), "end": en.isoformat(),
                         "minutes": int((en - s).total_seconds() // 60)} for s, en in windows],
            "busy": sorted(({"start": s.isoformat(), "end": en.isoformat(), **info}
                            for s, en, info in today_busy), key=lambda b: b["start"]),
        })
        d += timedelta(days=1)
    return days
