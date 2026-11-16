"""Частые и недавние события для кнопки «+»: плашки, которые открывают форму с уже заполненными
названием, длительностью, участниками и местом. Берём только то, что семья создаёт сама (пишущие календари)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from .events import _norm_title


def build(evs: list[dict], writable: set[str], now: datetime, limit: int = 6) -> list[dict]:
    groups: dict[str, dict] = {}
    for e in evs:
        if e.get("all_day") or e.get("private") or e.get("duty") or e.get("birthday"):
            continue
        cals = [c for c in e.get("calendars") or [] if c in writable]
        key = _norm_title(e.get("title") or "")
        if not cals or not key:
            continue
        s, en = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
        minutes = int((en - s).total_seconds() // 60)
        if minutes <= 0 or minutes > 12 * 60:
            continue
        g = groups.setdefault(key, {"title": e["title"], "uids": set(), "last": "", "series": False, "minutes": Counter(),
                                    "people": Counter(), "location": Counter(), "calendar": Counter(), "time": Counter()})
        g["uids"].add(e.get("uid") or e["id"])
        g["series"] = g["series"] or bool(e.get("recurring"))
        if e["start"] >= g["last"] and s.replace(tzinfo=None) <= now.replace(tzinfo=None):
            g["last"], g["title"] = e["start"], e["title"]
        g["minutes"][minutes] += 1
        g["time"][s.strftime("%H:%M")] += 1
        g["calendar"][cals[0]] += 1
        if e.get("location"):
            g["location"][e["location"]] += 1
        if e.get("people_override"):
            g["people"][tuple(sorted(p for p in e.get("people") or [] if not p.startswith("_")))] += 1

    def top(c: Counter, default=None):
        return c.most_common(1)[0][0] if c else default

    # Сначала то, что заводили несколько раз отдельными событиями; затем последние разовые. Серии повторять незачем.
    often = [g for g in groups.values() if len(g["uids"]) >= 2]
    often.sort(key=lambda g: (len(g["uids"]), g["last"]), reverse=True)
    lately = sorted((g for g in groups.values() if len(g["uids"]) == 1 and not g["series"] and g["last"]),
                    key=lambda g: g["last"], reverse=True)
    out = []
    for g in (often + lately)[:limit]:
        out.append({"title": g["title"], "count": len(g["uids"]), "minutes": top(g["minutes"], 60), "time": top(g["time"]),
                    "people": list(top(g["people"], ())), "location": top(g["location"], ""), "calendar": top(g["calendar"], "")})
    return out
