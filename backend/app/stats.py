"""Итоги семьи за период: сколько у кого встреч и часов, кто сколько возил, самый загруженный день."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from .events import UNASSIGNED, _norm_title

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def build(evs: list[dict], people: list[dict], start: datetime, end: datetime) -> dict:
    by_id = {p["id"]: p for p in people if not p.get("hidden")}
    per = {pid: {"id": pid, "name": p["name"], "color": p.get("color"), "emoji": p.get("emoji") or "",
                 "events": 0, "minutes": 0, "dropoff": 0, "pickup": 0} for pid, p in by_id.items()}
    weekdays = [0] * 7
    days: Counter = Counter()
    titles: Counter = Counter()
    shown: dict[str, str] = {}
    total_events, total_min = 0, 0
    for e in evs:
        if e.get("all_day"):
            continue
        s, en = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
        if not (start <= s < end):
            continue
        if e.get("duty"):  # поездка: считаем водителю, но не как отдельную встречу
            p = per.get((e.get("people") or [None])[0])
            if p and e["duty"]["role"] in ("dropoff", "pickup"):
                p[e["duty"]["role"]] += 1
            continue
        minutes = max(0, int((en - s).total_seconds() // 60))
        who = [pid for pid in e.get("people") or [] if pid in per and pid != UNASSIGNED]
        if not who:
            continue
        total_events += 1
        total_min += minutes
        weekdays[s.weekday()] += 1
        days[s.date().isoformat()] += 1
        key = _norm_title(e["title"])
        if key:
            titles[key] += 1
            shown.setdefault(key, e["title"])
        for pid in who:
            per[pid]["events"] += 1
            per[pid]["minutes"] += minutes
    busiest = days.most_common(1)
    rows = sorted(per.values(), key=lambda r: (-r["events"], r["name"]))
    return {
        "start": start.date().isoformat(), "end": end.date().isoformat(),
        "events": total_events, "hours": round(total_min / 60, 1),
        "trips": sum(r["dropoff"] + r["pickup"] for r in rows),
        "people": rows,
        "weekdays": [{"name": n, "events": c} for n, c in zip(WEEKDAYS, weekdays)],
        "busiest_day": {"date": busiest[0][0], "events": busiest[0][1]} if busiest else None,
        "top_titles": [{"title": shown[k], "count": c} for k, c in titles.most_common(5) if c > 1],
    }
