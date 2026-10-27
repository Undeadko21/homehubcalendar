"""Напоминания для телефона: сервер считает, приложение показывает локальными уведомлениями.

Виды:
  duty   — «пора ехать»: за lead минут до начала окна поездки (только для выбранных людей);
  digest — вечером накануне: у завтрашних событий детей конфликт поездок или не назначен водитель;
  bday   — утром в день рождения и накануне.
Идентификатор стабилен, поэтому приложение не показывает одно и то же дважды.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .birthdays import upcoming


def build(events: list[dict], birthdays_manual: list[dict], now: datetime, tz: ZoneInfo,
          people: set[str] | None, lead: int = 30) -> list[dict]:
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
        out.append({"id": f"duty:{e['id']}:{e['start']}", "kind": "duty",
                    "at": (start - timedelta(minutes=lead)).isoformat(),
                    "title": f"{head} — в {start.strftime('%H:%M')}", "text": text})

    tomorrow = today + timedelta(days=1)
    problems = []
    for e in events:
        if e.get("duty") or e["all_day"] or not e.get("escort_issue"):
            continue
        if datetime.fromisoformat(e["start"]).date() != tomorrow:
            continue
        label = "Конфликт" if e["escort_issue"] == "conflict" else "Нет водителя"
        hm = datetime.fromisoformat(e["start"]).strftime("%H:%M")
        problems.append(f"{label}: {e['title']} ({hm})")
    if problems:
        at = datetime.combine(today, time(20, 0), tz)
        out.append({"id": f"digest:{tomorrow.isoformat()}", "kind": "digest",
                    "at": max(at, now).isoformat(timespec="seconds"),
                    "title": f"Завтра: проблемы с поездками ({len(problems)})",
                    "text": "\n".join(problems)})

    for b in upcoming(birthdays_manual, events, today, 1):
        when = datetime.combine(today, time(9, 0), tz)
        age = f" ({b['turns']})" if b.get("turns") else ""
        phrase = "Сегодня" if b["days"] == 0 else "Завтра"
        out.append({"id": f"bday:{b['name']}:{b['date']}:{b['days']}", "kind": "bday",
                    "at": max(when, now).isoformat(timespec="seconds") if b["days"] == 0 else
                          datetime.combine(today, time(18, 0), tz).isoformat(),
                    "title": f"{phrase} день рождения: {b['name']}{age}", "text": ""})
    out.sort(key=lambda r: r["at"])
    return out
