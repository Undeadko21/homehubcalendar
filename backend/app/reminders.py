"""Напоминания для телефона: сервер считает, приложение показывает локальными уведомлениями.

Виды:
  duty   — «пора ехать»: за lead минут до начала окна поездки (только для выбранных людей);
  digest — вечером накануне: у событий детей на следующий день конфликт поездок или не назначен водитель;
  bday   — утром в день рождения и накануне вечером.
Идентификатор стабилен, поэтому приложение не показывает одно и то же дважды.

Для облачного снимка (lead=None) у duty-напоминаний отдаётся `start` и `people`, а `at` не считается:
время «за N минут» и фильтр по людям определяет само приложение — у каждого телефона они свои.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .birthdays import upcoming


def build(events: list[dict], birthdays_manual: list[dict], now: datetime, tz: ZoneInfo,
          people: set[str] | None, lead: int | None = 30, horizon_days: int = 2) -> list[dict]:
    now = now.astimezone(tz)
    today = now.date()
    out: list[dict] = []

    for e in events:
        duty = e.get("duty")
        if not duty or e["all_day"]:
            continue
        if people is not None and not (set(e["people"]) & people):
            continue
        start = datetime.fromisoformat(e["start"])
        head, _, rest = e["title"].partition(": ")
        conflicts = (duty["parent"].get("escort") or {}).get(duty["role"], {}).get("conflicts", [])
        text = rest or e["title"]
        if e.get("location"):
            text += f" · {e['location']}"
        if conflicts:
            text += " · занят(а): " + ", ".join(c["title"] for c in conflicts)
        item = {"id": f"duty:{e['id']}:{e['start']}", "kind": "duty", "start": e["start"],
                "people": [p for p in e["people"] if not p.startswith("_")],
                "title": f"{head} — в {start.strftime('%H:%M')}", "text": text}
        if lead is not None:
            item["at"] = (start - timedelta(minutes=lead)).isoformat()
        out.append(item)

    # Дайджест проблем с поездками: накануне в 20:00 для каждого из ближайших дней.
    for d in range(1, max(1, horizon_days) + 1):
        day = today + timedelta(days=d)
        problems = []
        for e in events:
            if e.get("duty") or e["all_day"] or not e.get("escort_issue"):
                continue
            s = datetime.fromisoformat(e["start"])
            if s.date() != day:
                continue
            label = "Конфликт" if e["escort_issue"] == "conflict" else "Нет водителя"
            problems.append(f"{label}: {e['title']} ({s.strftime('%H:%M')})")
        if problems:
            at = max(datetime.combine(day - timedelta(days=1), time(20, 0), tz), now)
            out.append({"id": f"digest:{day.isoformat()}", "kind": "digest", "at": at.isoformat(timespec="seconds"),
                        "title": f"Завтра: проблемы с поездками ({len(problems)})", "text": "\n".join(problems)})

    for b in upcoming(birthdays_manual, events, today, horizon_days):
        day = date_of(b)
        age = f" ({b['turns']})" if b.get("turns") else ""
        # Утром в сам день и накануне вечером.
        out.append({"id": f"bday:{b['name']}:{b['date']}:0", "kind": "bday",
                    "at": max(datetime.combine(day, time(9, 0), tz), now).isoformat(timespec="seconds"),
                    "title": f"Сегодня день рождения: {b['name']}{age}", "text": ""})
        if b["days"] >= 1:
            out.append({"id": f"bday:{b['name']}:{b['date']}:1", "kind": "bday",
                        "at": datetime.combine(day - timedelta(days=1), time(18, 0), tz).isoformat(timespec="seconds"),
                        "title": f"Завтра день рождения: {b['name']}{age}", "text": ""})
    out.sort(key=lambda r: r.get("at") or r["start"])
    return out


def date_of(b: dict):
    from datetime import date
    return date.fromisoformat(b["date"])
