"""Обратный отсчёт до важных событий: событие отмечено звёздочкой в карточке (`kv event_stars {uid: true}`, на все повторы)."""
from __future__ import annotations

import time as _time
from datetime import date, datetime, time, timedelta

KEY = "event_stars"
HORIZON = 366
_cache: dict = {"key": None, "at": 0.0, "items": []}


def stars(db) -> dict:
    return db.kv_get(KEY)[0] or {}


def set_star(db, uid: str, on: bool) -> None:
    data = dict(stars(db))
    if on:
        data[uid] = True
    else:
        data.pop(uid, None)
    db.kv_set(KEY, data)
    _cache["key"] = None


def upcoming(svc, db, tz, today: date | None = None, horizon: int = HORIZON) -> list[dict]:
    """Ближайшее вхождение каждого отмеченного события: [{uid, title, start, days, all_day}] по дате.
    Год вперёд считается не дёшево, поэтому результат держим 10 минут (и сбрасываем при смене звёздочек)."""
    marked = stars(db)
    if not marked:
        return []
    today = today or datetime.now(tz).date()
    key = (today, tuple(sorted(marked)))
    if _cache["key"] == key and _time.monotonic() - _cache["at"] < 600:
        return _cache["items"]
    start = datetime.combine(today, time(0), tz)
    found: dict[str, dict] = {}
    for e in svc.events(start, start + timedelta(days=horizon)):
        uid = e.get("uid")
        if uid not in marked or e.get("duty") or uid in found:
            continue
        d = datetime.fromisoformat(e["start"]).astimezone(tz).date() if not e.get("all_day") else date.fromisoformat(e["start"][:10])
        found[uid] = {"uid": uid, "id": e["id"], "title": e["title"], "start": e["start"], "all_day": bool(e.get("all_day")),
                      "days": (d - today).days}
    items = sorted(found.values(), key=lambda x: x["start"])
    _cache.update(key=key, at=_time.monotonic(), items=items)
    return items


def invalidate() -> None:
    _cache["key"] = None
