"""Ежедневная проверка данных: тихие проблемы, которые иначе заметишь только в день события.

Только то, что можно починить в самом календаре (внешние сбои синхронизации и облака показывает /api/system).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

from .events import UNASSIGNED, EventService, _norm_title


def run(db, events: EventService, tz) -> list[dict]:
    """[{level: 'warn'|'info', text}] по ближайшим дням."""
    today = datetime.combine(datetime.now(tz).date(), time(0), tz)
    evs = events.events(today, today + timedelta(days=14))
    people = {p["id"]: p for p in db.list_people()}
    out: list[dict] = []

    def day(e):
        return datetime.fromisoformat(e["start"][:19]).strftime("%d.%m")

    # 1. Поездки детей на ближайшие 3 дня: нет водителя или он занят.
    for e in evs:
        if e.get("duty") or e["all_day"] or e.get("private"):
            continue
        d = datetime.fromisoformat(e["start"]).astimezone(tz).date()
        if d > (today + timedelta(days=3)).date():
            continue
        issue = e.get("escort_issue")
        kids = ", ".join(people[c]["name"] for c in (e.get("escort") or {}).get("children", []) if c in people)
        if issue == "unassigned":
            out.append({"level": "warn", "text": f"{day(e)} «{e['title']}» ({kids}): не назначен водитель"})
        elif issue == "conflict":
            out.append({"level": "warn", "text": f"{day(e)} «{e['title']}» ({kids}): водитель занят в это время"})

    # 2. События без людей: их не видно ни в одной колонке.
    free = [e for e in evs if UNASSIGNED in e["people"] and not e.get("duty")]
    if free:
        names = ", ".join(f"«{e['title']}»" for e in free[:3])
        out.append({"level": "info", "text": f"{len(free)} событий без владельца за 2 недели (например {names}) — назначьте людей"})

    # 3. Дубли, которые склейка не поймала: одно название и начало у разных событий одного человека.
    seen: dict[tuple, dict] = {}
    dups = 0
    for e in evs:
        if e.get("duty") or e["all_day"]:
            continue
        for pid in e["people"]:
            k = (pid, _norm_title(e["title"]), e["start"])
            if k in seen and seen[k]["id"] != e["id"]:
                dups += 1
            else:
                seen[k] = e
    if dups:
        out.append({"level": "info", "text": f"Похоже на дубли: {dups} совпадений по названию и времени у одного человека"})

    # 4. Календарь без событий вообще, хотя синхронизация прошла.
    status = {s["source_id"]: s for s in db.sync_status()}
    for c in db.list_calendars():
        st = status.get(c.get("source_id"))
        if st and st.get("last_ok") and not st.get("last_error") and not db.objects_for(c["key"]) and not c["hidden"]:
            out.append({"level": "info", "text": f"Календарь «{c['name']}» пуст — проверьте, тот ли он подключён"})

    # 5. Ребёнок есть, взрослых нет: некому назначать поездки.
    kids = [p for p in people.values() if p.get("needs_escort") and not p.get("hidden")]
    adults = [p for p in people.values() if not p.get("needs_escort") and not p.get("hidden") and not p["id"].startswith("_")]
    if kids and not adults:
        out.append({"level": "warn", "text": "Есть дети, но нет ни одного взрослого — поездки назначать некому"})
    return out


def ready(db, events: EventService, tz) -> dict:
    """Минимальная проверка работоспособности для деплоя: база читается, лента собирается."""
    today = datetime.combine(datetime.now(tz).date(), time(0), tz)
    people = db.list_people()
    evs = events.events(today, today + timedelta(days=2))
    return {"ok": True, "people": len(people), "events_today": len(evs)}
