"""Школьные каникулы: диапазоны дат задаёт семья (у каждого региона свои), показываются рядом с праздниками."""
from __future__ import annotations

from datetime import date, timedelta

from .db import Database

KEY = "settings:school"


def load(db: Database) -> list[dict]:
    return (db.kv_get(KEY)[0] or {}).get("breaks", [])


DEFAULT_WORDS = "школ"


def settings(db: Database) -> dict:
    v = db.kv_get(KEY)[0] or {}
    return {"hide": v.get("hide", True), "hide_words": v.get("hide_words", DEFAULT_WORDS)}


def save_settings(db: Database, hide: bool | None, words: str | None) -> dict:
    v = dict(db.kv_get(KEY)[0] or {})
    if hide is not None:
        v["hide"] = bool(hide)
    if words is not None:
        v["hide_words"] = ", ".join(w.strip().lower() for w in words.split(",") if w.strip())[:200]
    db.kv_set(KEY, v)
    return settings(db)


def hidden_filter(db: Database):
    """Функция «скрыть ли событие»: во время каникул не показываем школьные события (по словам в названии/месте)."""
    cfg = settings(db)
    words = [w.strip().lower() for w in str(cfg["hide_words"]).split(",") if w.strip()]
    breaks = [(date.fromisoformat(b["from"]), date.fromisoformat(b["to"])) for b in load(db)]
    if not cfg["hide"] or not words or not breaks:
        return None

    def hide(e: dict) -> bool:
        try:
            d = date.fromisoformat(str(e["start"])[:10])
        except ValueError:
            return False
        if not any(a <= d <= z for a, z in breaks):
            return False
        text = f"{e.get('title') or ''} {e.get('location') or ''}".lower()
        return any(w in text for w in words)

    return hide


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
    db.kv_set(KEY, {**(db.kv_get(KEY)[0] or {}), "breaks": clean})
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
