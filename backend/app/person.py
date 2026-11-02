"""Сводка по одному человеку: ближайшее, регулярное, поездки, дела."""
from __future__ import annotations

from datetime import datetime, time, timedelta

DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def build(person: dict, events, lists: list[dict], people: dict[str, dict], tz, days: int = 14) -> dict:
    pid = person["id"]
    today = datetime.combine(datetime.now(tz).date(), time(0), tz)
    evs = [e for e in events.events(today, today + timedelta(days=days)) if pid in e["people"]]
    now = datetime.now(tz)

    def at(e):
        return datetime.fromisoformat(e["start"] if not e["all_day"] else e["start"] + "T00:00:00")

    def aware(d):
        return d if d.tzinfo else d.replace(tzinfo=tz)

    upcoming = [e for e in evs if not e.get("duty") and aware(at(e)) + timedelta(hours=1) >= now]
    nxt = upcoming[:8]   # полные события: из профиля их можно открыть карточкой

    # Регулярное: серии, сгруппированные по UID.
    series: dict[str, dict] = {}
    for e in evs:
        if e.get("duty") or not e.get("recurring") or e["all_day"]:
            continue
        d = aware(at(e)).astimezone(tz)
        s = series.setdefault(e["uid"], {"title": e["title"], "days": set(), "time": d.strftime("%H:%M"), "drivers": {}})
        s["days"].add(d.weekday())
        esc = e.get("escort") or {}
        for role in ("dropoff", "pickup"):
            who = (esc.get(role) or {}).get("person")
            if who and who in people:
                s["drivers"][role] = people[who]["name"]
    regular = [{"title": s["title"], "days": [DAYS[i] for i in sorted(s["days"])], "time": s["time"],
                "dropoff": s["drivers"].get("dropoff"), "pickup": s["drivers"].get("pickup")}
               for s in series.values()]
    regular.sort(key=lambda r: (min(DAYS.index(d) for d in r["days"]), r["time"]))

    # Поездки взрослого (события с duty) на неделю.
    week_end = today + timedelta(days=7)
    duties = [{"title": e["title"], "start": e["start"]} for e in evs
              if e.get("duty") and aware(at(e)) >= now and aware(at(e)) < week_end]

    todos = [{"id": i["id"], "text": i["text"], "due": i.get("due"), "list": l["name"]}
             for l in lists for i in l["items"] if not i["done"] and i.get("person_id") == pid]

    return {"person": {k: person.get(k) for k in ("id", "name", "emoji", "color", "needs_escort")},
            "next": nxt, "regular": regular, "duties": duties[:8], "duties_count": len(duties), "todos": todos}
