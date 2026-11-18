"""Погода для утренней сводки «мой день»: дневной прогноз Open-Meteo (тот же источник, что у экрана «Сегодня»).

Без ключа, кэш на час; не отвечает — сводка просто без погоды. Координаты — `weather` в config.yaml.
"""
from __future__ import annotations

import time
from datetime import date

import httpx

CODES = {0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно", 45: "туман", 48: "туман",
         51: "морось", 53: "морось", 55: "морось", 56: "ледяная морось", 57: "ледяная морось",
         61: "небольшой дождь", 63: "дождь", 65: "сильный дождь", 66: "ледяной дождь", 67: "ледяной дождь",
         71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
         80: "ливень", 81: "ливень", 82: "сильный ливень", 85: "снегопад", 86: "сильный снегопад",
         95: "гроза", 96: "гроза с градом", 99: "гроза с градом"}
TTL = 3600
_cache: dict = {"at": 0.0, "key": None, "days": {}}


def _fmt(v: float) -> str:
    n = round(v)
    return f"+{n}" if n > 0 else str(n).replace("-", "−")


def cached(cfg: dict) -> dict[date, str]:
    """Только из кэша (для сборки снимка — без сети, чтобы приложения не ждали). Обновляет планировщик (`daily`)."""
    lat, lon = (cfg or {}).get("latitude"), (cfg or {}).get("longitude")
    return _cache["days"] if _cache["key"] == (lat, lon) else {}


def daily(cfg: dict, client: httpx.Client | None = None) -> dict[date, str]:
    """{дата: «−5…−1°, снег, осадки 70 % — тёплая обувь»} на 3 дня; {} при любой ошибке или без координат."""
    lat, lon = (cfg or {}).get("latitude"), (cfg or {}).get("longitude")
    if lat is None or lon is None:
        return {}
    key = (lat, lon)
    if _cache["key"] == key and time.time() - _cache["at"] < TTL:
        return _cache["days"]
    try:
        with (client or httpx.Client(timeout=8)) as c:
            r = c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
            r.raise_for_status()
        d = r.json()["daily"]
        days: dict[date, str] = {}
        for i, ds in enumerate(d["time"]):
            lo, hi = d["temperature_2m_min"][i], d["temperature_2m_max"][i]
            code = d["weather_code"][i]
            rain = (d.get("precipitation_probability_max") or [0] * len(d["time"]))[i] or 0
            text = f"{_fmt(lo)}…{_fmt(hi)}°, {CODES.get(code, '')}".rstrip(", ")
            if rain >= 50:
                snowy = code in (71, 73, 75, 77, 85, 86) or hi <= 0
                text += f", осадки {rain} % — " + ("тёплая обувь" if snowy else "возьмите зонт")
            elif hi <= -15:
                text += " — очень холодно, потеплее"
            days[date.fromisoformat(ds)] = text
    except Exception:  # noqa: BLE001 — погода не критична; повторим не раньше чем через 10 минут (не тормозим снимок)
        old = _cache["days"] if _cache["key"] == key else {}
        _cache.update(at=time.time() - TTL + 600, key=key, days=old)
        return old
    _cache.update(at=time.time(), key=key, days=days)
    return days
