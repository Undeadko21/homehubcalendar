"""Напоминания для телефона: сервер считает, приложение показывает локальными уведомлениями.

Виды:
  duty   — «пора ехать»: за lead минут до начала окна поездки (только для выбранных людей);
  digest — вечером накануне: у событий детей на следующий день конфликт поездок или не назначен водитель;
  event  — перед обычной встречей: у каждого человека свои интервалы (kv settings:event_reminders),
           `people` — те, кому нужно именно это напоминание, `at` посчитан сервером;
  bday   — утром в день рождения и накануне вечером.
Идентификатор стабилен, поэтому приложение не показывает одно и то же дважды.

Для облачного снимка (lead=None) у duty-напоминаний отдаётся `start` и `people`, а `at` не считается:
время «за N минут» и фильтр по людям определяет само приложение — у каждого телефона они свои.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .birthdays import AUTO_RE, upcoming
from .db import Database

EVENT_KEY = "settings:event_reminders"
LEAD_CHOICES = (5, 10, 15, 30, 45, 60, 120, 1440)


def load_rules(db: Database) -> dict[str, list[int]]:
    """{человек: [за сколько минут напомнить, ...]}"""
    return (db.kv_get(EVENT_KEY)[0] or {}).get("people", {})


def save_rules(db: Database, people: dict, known: set[str]) -> dict[str, list[int]]:
    clean: dict[str, list[int]] = {}
    for pid, leads in (people or {}).items():
        if pid not in known:
            continue
        vals = sorted({int(x) for x in leads or [] if 1 <= int(x) <= 10080}, reverse=True)[:4]
        if vals:
            clean[pid] = vals
    cur = db.kv_get(EVENT_KEY)[0] or {}
    cur["people"] = clean
    db.kv_set(EVENT_KEY, cur)
    return clean


def load_allday(db: Database) -> dict:
    """События на весь день: {people: [id…], time: "HH:MM"} — вечером накануне напомнить выбранным людям."""
    v = (db.kv_get(EVENT_KEY)[0] or {}).get("allday") or {}
    t = v.get("time") or "19:00"
    return {"people": list(v.get("people") or []), "time": t}


def save_allday(db: Database, people: list, time_: str, known: set[str]) -> dict:
    try:
        h, m = (int(x) for x in str(time_ or "19:00").split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        time_ = "19:00"
    else:
        time_ = f"{h:02d}:{m:02d}"
    cur = db.kv_get(EVENT_KEY)[0] or {}
    cur["allday"] = {"people": [p for p in dict.fromkeys(people or []) if p in known], "time": time_}
    db.kv_set(EVENT_KEY, cur)
    return load_allday(db)


def _lead_text(m: int) -> str:
    if m % 1440 == 0:
        d = m // 1440
        return "завтра" if d == 1 else f"через {d} дн."
    if m % 60 == 0:
        h = m // 60
        return "через 1 час" if h == 1 else f"через {h} ч"
    return f"через {m} мин"


def build(events: list[dict], birthdays_manual: list[dict], now: datetime, tz: ZoneInfo,
          people: set[str] | None, lead: int | None = 30, horizon_days: int = 2,
          event_rules: dict[str, list[int]] | None = None,
          allday: dict | None = None) -> list[dict]:
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

    # Обычные встречи: у каждого человека свои интервалы.
    if event_rules:
        for e in events:
            if e.get("duty") or e["all_day"] or e.get("private"):
                continue
            start = datetime.fromisoformat(e["start"])
            by_lead: dict[int, list[str]] = {}
            for pid in e["people"]:
                for m in event_rules.get(pid, []):
                    by_lead.setdefault(m, []).append(pid)
            for m, who in by_lead.items():
                if people is not None and not (set(who) & people):
                    continue
                at = start - timedelta(minutes=m)
                if at < now - timedelta(hours=3) or start < now:
                    continue
                text = f"в {start.strftime('%H:%M')}"
                if e.get("location"):
                    text += f" · {e['location']}"
                out.append({"id": f"event:{e['id']}:{e['start']}:{m}", "kind": "event", "at": at.isoformat(timespec="seconds"),
                            "start": e["start"], "people": who,
                            "title": f"{e['title']} — {_lead_text(m)}", "text": text})

    # События на весь день: накануне вечером (дни рождения напоминает блок bday ниже).
    if allday and allday.get("people"):
        wanted_ad = set(allday["people"])
        hh, mm = (int(x) for x in (allday.get("time") or "19:00").split(":"))
        for e in events:
            if not e["all_day"] or e.get("duty") or e.get("private") or AUTO_RE.search(e["title"]):
                continue
            who = [p for p in e["people"] if p in wanted_ad]
            if not who or (people is not None and not (set(who) & people)):
                continue
            day = datetime.fromisoformat(e["start"]).date()
            if day <= today:
                continue
            at = datetime.combine(day - timedelta(days=1), time(hh, mm), tz)
            if at < now - timedelta(hours=3):
                continue
            out.append({"id": f"allday:{e['id']}:{e['start']}", "kind": "event", "at": at.isoformat(timespec="seconds"),
                        "start": e["start"], "people": who, "title": f"Завтра: {e['title']}",
                        "text": e.get("location") or "на весь день"})

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
