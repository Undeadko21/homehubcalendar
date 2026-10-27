"""Дни рождения: ближайшие даты с обратным отсчётом.

Источники: список, который семья ведёт в настройках, и (автоматически) целодневные события
календарей со словами «день рождения», «ДР», «birthday» в названии.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

AUTO_RE = re.compile(r"день\s+рождения|(?<!\w)д\.?\s?р\.?(?!\w)|birthday|b-?day", re.IGNORECASE)


def next_date(month: int, day: int, today: date) -> date:
    def make(year: int) -> date:
        if month == 2 and day == 29 and not _leap(year):
            return date(year, 2, 28)
        return date(year, month, day)
    d = make(today.year)
    return d if d >= today else make(today.year + 1)


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _same_person(name: str, title: str) -> bool:
    """«Оля» ~ «День рождения Оли»: слово названия начинается с основы имени (учёт склонения)."""
    stem = name.lower()[: max(2, len(name) - 1)]
    return bool(stem) and any(w.startswith(stem) for w in re.findall(r"\w+", title.lower()))


def upcoming(manual: list[dict], events: list[dict], today: date, horizon_days: int = 60) -> list[dict]:
    out = []
    for b in manual:
        d = next_date(b["month"], b["day"], today)
        out.append({"id": b["id"], "name": b["name"], "month": b["month"], "day": b["day"], "year": b.get("year"),
                    "date": d.isoformat(), "days": (d - today).days,
                    "turns": d.year - b["year"] if b.get("year") else None, "auto": False})
    names = [b["name"].lower() for b in manual]
    seen: set[tuple[str, str]] = set()
    for e in events:
        if not e["all_day"] or not AUTO_RE.search(e["title"]):
            continue
        d = date.fromisoformat(e["start"][:10])
        days = (d - today).days
        title = e["title"].strip()
        if not 0 <= days <= horizon_days or (title.lower(), e["start"][:10]) in seen:
            continue
        if any(_same_person(n, title) for n in names):
            continue
        seen.add((title.lower(), e["start"][:10]))
        out.append({"id": None, "name": title, "month": d.month, "day": d.day, "year": None,
                    "date": d.isoformat(), "days": days, "turns": None, "auto": True})
    out.sort(key=lambda x: (x["days"], x["name"]))
    return [x for x in out if x["days"] <= horizon_days]


def days_phrase(days: int) -> str:
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    n = days % 100
    word = "дней" if 11 <= n <= 14 else {1: "день", 2: "дня", 3: "дня", 4: "дня"}.get(days % 10, "дней")
    return f"через {days} {word}"
