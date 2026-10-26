"""Данные для виджета Android (и любых других «маленьких» экранов).

Сервер отдаёт уже готовые к показу строки на русском, чтобы виджет был простым,
а его содержимое можно было менять, не обновляя приложение на телефонах.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]


def _day_label(d: date, today: date) -> str:
    base = f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"
    if d == today:
        return "Сегодня"  # дата уже есть в шапке виджета
    if d == today + timedelta(days=1):
        return "Завтра, " + base
    return base[0].upper() + base[1:]


def _hm(s: str) -> str:
    return datetime.fromisoformat(s).strftime("%H:%M")


def build(events: list[dict], people: dict[str, dict], tz: ZoneInfo, now: datetime,
          days: int = 2, only: set[str] | None = None) -> dict:
    today = now.astimezone(tz).date()
    out_days = []
    for i in range(days):
        d = today + timedelta(days=i)
        d0 = datetime.combine(d, time(0), tz)
        d1 = d0 + timedelta(days=1)
        items = []
        for e in events:
            if only and not (set(e["people"]) & only):
                continue
            if e["all_day"]:
                s = datetime.combine(date.fromisoformat(e["start"]), time(0), tz)
                en = datetime.combine(date.fromisoformat(e["end"]), time(0), tz)
            else:
                s, en = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
            if not (s < d1 and en > d0):
                continue
            if i == 0 and not e["all_day"] and en <= now:
                continue  # прошедшие сегодня не показываем
            who = [p for p in e["people"] if p in people]
            esc = e.get("escort")
            note = ""
            duty = e.get("duty")
            if duty:
                # Поездка взрослого: если он в это время занят — напишем чем.
                conflicts = (duty["parent"].get("escort") or {}).get(duty["role"], {}).get("conflicts", [])
                if conflicts:
                    note = "занят(а): " + ", ".join(c["title"] for c in conflicts)
            if esc:
                if esc["mode"] == "home":
                    note = "дома"
                elif esc["mode"] == "together":
                    note = "все вместе"
                else:
                    parts = []
                    for role, arrow in (("dropoff", "→"), ("pickup", "←")):
                        r = esc[role]
                        if r["skip"]:
                            continue
                        name = people.get(r["person"], {}).get("name") if r["person"] else "кто?"
                        parts.append(f"{arrow} {name}")
                    note = "  ".join(parts)
            items.append({
                "id": e["id"],
                "title": e["title"],
                "time": "весь день" if e["all_day"] else f"{_hm(e['start'])}–{_hm(e['end'])}",
                "start": e["start"],
                "end": e["end"],
                "all_day": e["all_day"],
                "now": (not e["all_day"]) and s <= now < en,
                "location": e.get("location", ""),
                "people": who,
                "who": ", ".join(people[p]["name"] for p in who),
                "colors": [people[p]["color"] for p in who],
                "note": note,
                "issue": e.get("escort_issue"),
                "duty": bool(e.get("duty")),
            })
        items.sort(key=lambda x: (not x["all_day"], x["start"]))
        out_days.append({"date": d.isoformat(), "label": _day_label(d, today), "events": items})
    return {
        "generated": now.isoformat(timespec="seconds"),
        "people": {pid: {"name": p["name"], "color": p["color"], "emoji": p.get("emoji", "")}
                   for pid, p in people.items()},
        "days": out_days,
    }
