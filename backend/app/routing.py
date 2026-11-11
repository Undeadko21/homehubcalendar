"""Время в дороге по карте: адрес → координаты (Nominatim, OpenStreetMap) → маршрут на машине (OSRM).

Оба сервиса бесплатные и без ключа, пробок не знают — поэтому к времени без пробок добавляется запас TRAFFIC и
результат округляется вверх до 5 минут. Наружу уходят только два адреса (дом и место события), поэтому режим
включается в настройках поездок (`settings:escort.map_travel`) и работает, только если задан адрес дома для карты (`map_home`).

Ответы кэшируются в `kv route:cache` (ключ — место в нижнем регистре): запрос ленты в сеть не ходит никогда,
новые места досчитывает фоновая задача (`refresh`) или кнопка «По карте» в карточке события.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

import httpx

KEY = "route:cache"
TRAFFIC = 1.3            # запас на пробки и парковку к времени «по пустой дороге»
KEEP_DAYS = 90           # найденный маршрут
RETRY_DAYS = 3           # ненайденный адрес — пробуем снова через столько дней
LIMIT = 300              # мест в кэше
UA = {"User-Agent": "HomeHubCalendar/1 (family calendar; travel time estimate)"}
GEOCODE = "https://nominatim.openstreetmap.org/search"
ROUTE = "https://router.project-osrm.org/route/v1/driving/{a};{b}"


def norm(location: str) -> str:
    return " ".join((location or "").lower().split())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh(entry: dict, home: str) -> bool:
    if entry.get("home") != norm(home):
        return False
    try:
        age = _now() - datetime.fromisoformat(entry["at"])
    except (KeyError, ValueError):
        return False
    return age < timedelta(days=KEEP_DAYS if entry.get("minutes") is not None else RETRY_DAYS)


def cached(db, home: str) -> dict[str, int]:
    """{место: минуты} — только найденные и не устаревшие; для разметки ленты."""
    data = db.kv_get(KEY)[0] or {}
    return {k: v["minutes"] for k, v in data.items() if v.get("minutes") is not None and _fresh(v, home)}


def _geocode(client, address: str) -> tuple[float, float] | None:
    r = client.get(GEOCODE, params={"q": address, "format": "jsonv2", "limit": 1, "accept-language": "ru"})
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    return float(rows[0]["lon"]), float(rows[0]["lat"])


def estimate(home: str, dest: str, client=None, pause: float = 1.1) -> int | None:
    """Минуты на машине от дома до места (None — адрес не нашёлся). Сетевые ошибки пробрасываются."""
    own = client is None
    client = client or httpx.Client(timeout=10, headers=UA)
    try:
        a = _geocode(client, home)
        if a is None:
            return None
        if pause:
            time.sleep(pause)        # Nominatim просит не чаще запроса в секунду
        b = _geocode(client, dest)
        if b is None:
            return None
        r = client.get(ROUTE.format(a=f"{a[0]:.6f},{a[1]:.6f}", b=f"{b[0]:.6f},{b[1]:.6f}"), params={"overview": "false"})
        r.raise_for_status()
        routes = r.json().get("routes") or []
        if not routes:
            return None
        minutes = routes[0]["duration"] / 60 * TRAFFIC
        return min(240, max(5, int(math.ceil(minutes / 5.0)) * 5))
    finally:
        if own:
            client.close()


def resolve(db, home: str, location: str, client=None, pause: float = 1.1, force: bool = False) -> int | None:
    """Минуты до места: из кэша или посчитать и запомнить (и «не нашлось» тоже — чтобы не спрашивать каждый раз)."""
    key = norm(location)
    if not key or not norm(home):
        return None
    data = dict(db.kv_get(KEY)[0] or {})
    hit = data.get(key)
    if hit and _fresh(hit, home) and not force:
        return hit.get("minutes")
    minutes = estimate(home, location, client=client, pause=pause)
    data[key] = {"minutes": minutes, "at": _now().isoformat(timespec="seconds"), "home": norm(home)}
    if len(data) > LIMIT:
        for k in sorted(data, key=lambda k: data[k].get("at", ""))[:len(data) - LIMIT]:
            data.pop(k, None)
    db.kv_set(KEY, data)
    return minutes


def refresh(db, events: list[dict], home: str, limit: int = 6, client=None, pause: float = 1.1) -> int:
    """Досчитать места ближайших событий детей, которых ещё нет в кэше. Возвращает число новых найденных маршрутов."""
    if not norm(home):
        return 0
    data = db.kv_get(KEY)[0] or {}
    todo: list[str] = []
    for e in events:
        esc = e.get("escort")
        loc = (e.get("location") or "").strip()
        if not esc or e.get("duty") or esc.get("mode") != "escort" or not loc:
            continue
        hit = data.get(norm(loc))
        if (hit and _fresh(hit, home)) or loc in todo:
            continue
        todo.append(loc)
    found = 0
    for loc in todo[:limit]:
        try:
            if resolve(db, home, loc, client=client, pause=pause) is not None:
                found += 1
        except Exception:  # noqa: BLE001 — сеть недоступна: попробуем в следующий раз
            break
        if pause:
            time.sleep(pause)
    return found
