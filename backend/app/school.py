"""Школьные каникулы: диапазоны дат задаёт семья (у каждого региона свои), показываются рядом с праздниками."""
from __future__ import annotations

from datetime import date, timedelta

from .db import Database

KEY = "settings:school"


def load(db: Database) -> list[dict]:
    return (db.kv_get(KEY)[0] or {}).get("breaks", [])


def save(db: Database, breaks: list[dict]) -> list[dict]:
    clean = []
    for b in breaks:
        name = (b.get("name") or "").strip()[:60] or "Каникулы"
        try:
            a, z = date.fromisoformat(b["from"]), date.fromisoformat(b["to"])
        except (KeyError, ValueError, TypeError):
            continue
        if z < a or (z - a).days > 120:
            continue
        clean.append({"name": name, "from": a.isoformat(), "to": z.isoformat()})
    clean.sort(key=lambda b: b["from"])
    db.kv_set(KEY, {"breaks": clean})
    return clean


def merge(db: Database, holidays: list[dict], start: date, end: date) -> list[dict]:
    """К особым дням добавляет каникулы: полем `vacation` или отдельной записью type=vacation."""
    out = {h["date"]: dict(h) for h in holidays}
    for b in load(db):
        d = max(date.fromisoformat(b["from"]), start)
        last = min(date.fromisoformat(b["to"]), end - timedelta(days=1))
        while d <= last:
            k = d.isoformat()
            if k in out:
                out[k]["vacation"] = b["name"]
            else:
                out[k] = {"date": k, "type": "vacation", "name": b["name"], "vacation": b["name"]}
            d += timedelta(days=1)
    return [out[k] for k in sorted(out)]
