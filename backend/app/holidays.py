"""Производственный календарь (праздники, переносы, сокращённые дни).

Провайдеры:
  - isdayoff — https://isdayoff.ru (официальные переносы на каждый год)
  - fixed    — только праздники из ТК РФ, без переносов (работает офлайн)
  - none     — выключено
Результат по году кэшируется в базе на неделю; при недоступности сайта
используется кэш, а без кэша — провайдер fixed.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from .db import Database

log = logging.getLogger(__name__)

RU_HOLIDAYS = {
    (1, 1): "Новогодние каникулы", (1, 2): "Новогодние каникулы", (1, 3): "Новогодние каникулы",
    (1, 4): "Новогодние каникулы", (1, 5): "Новогодние каникулы", (1, 6): "Новогодние каникулы",
    (1, 7): "Рождество Христово", (1, 8): "Новогодние каникулы",
    (2, 23): "День защитника Отечества",
    (3, 8): "Международный женский день",
    (5, 1): "Праздник Весны и Труда",
    (5, 9): "День Победы",
    (6, 12): "День России",
    (11, 4): "День народного единства",
}

CACHE_TTL = timedelta(days=7)


def _days_of_year(year: int):
    d = date(year, 1, 1)
    while d.year == year:
        yield d
        d += timedelta(days=1)


def _fixed_codes(year: int) -> str:
    """0 — рабочий, 1 — выходной, 2 — сокращённый (как у isdayoff)."""
    return "".join(
        "1" if d.weekday() >= 5 or (d.month, d.day) in RU_HOLIDAYS else "0" for d in _days_of_year(year)
    )


def _fetch_isdayoff(year: int, country: str) -> str:
    r = httpx.get(
        "https://isdayoff.ru/api/getdata",
        params={"year": year, "pre": 1, "cc": country},
        timeout=5,
    )
    r.raise_for_status()
    codes = r.text.strip()
    expected = len(list(_days_of_year(year)))
    if len(codes) != expected or not set(codes) <= set("01234"):
        raise ValueError(f"Неожиданный ответ isdayoff: {codes[:40]!r}")
    return codes


class HolidayService:
    def __init__(self, db: Database, cfg: dict):
        self.db = db
        self.provider = (cfg or {}).get("provider", "isdayoff")
        self.country = (cfg or {}).get("country", "ru")
        self._fail: dict[int, float] = {}      # год -> когда последний раз не удалось скачать
        self._refreshing: set[int] = set()

    def _codes(self, year: int) -> str:
        if self.provider == "fixed":
            return _fixed_codes(year)
        key = f"holidays:{self.provider}:{self.country}:{year}"
        cached, updated = self.db.kv_get(key)
        fresh = updated and datetime.fromisoformat(updated) > datetime.now(timezone.utc) - CACHE_TTL
        if cached and fresh:
            return cached
        if cached:
            # Устарел, но показывать можно: обновляем в фоне, чтобы не задерживать открытие календаря.
            self._refresh_async(year, key)
            return cached
        if time.time() - self._fail.get(year, 0) < 1800:   # недавно не вышло — не ждём сайт на каждом запросе
            return _fixed_codes(year)
        try:
            codes = _fetch_isdayoff(year, self.country)
            self.db.kv_set(key, codes)
            return codes
        except Exception as e:  # noqa: BLE001
            self._fail[year] = time.time()
            log.warning("Производственный календарь недоступен (%s), использую фиксированные праздники", e)
            return _fixed_codes(year)

    def _refresh_async(self, year: int, key: str) -> None:
        if year in self._refreshing or time.time() - self._fail.get(year, 0) < 1800:
            return
        self._refreshing.add(year)

        def job():
            try:
                self.db.kv_set(key, _fetch_isdayoff(year, self.country))
            except Exception as e:  # noqa: BLE001
                self._fail[year] = time.time()
                log.warning("Не удалось обновить производственный календарь (%s), остаётся кэш", e)
            finally:
                self._refreshing.discard(year)
        threading.Thread(target=job, daemon=True).start()

    def between(self, start: date, end: date) -> list[dict]:
        """Особые дни в диапазоне [start, end). Обычные выходные не возвращаются."""
        if self.provider == "none":
            return []
        out = []
        years: dict[int, str] = {}
        d = start
        while d < end:
            codes = years.setdefault(d.year, self._codes(d.year))
            code = codes[d.timetuple().tm_yday - 1]
            weekend = d.weekday() >= 5
            name = RU_HOLIDAYS.get((d.month, d.day)) if self.country == "ru" else None
            if name and code == "1":
                out.append({"date": d.isoformat(), "type": "holiday", "name": name})
            elif code == "1" and not weekend:
                out.append({"date": d.isoformat(), "type": "dayoff", "name": "Выходной (перенос)"})
            elif code == "0" and weekend:
                out.append({"date": d.isoformat(), "type": "workday", "name": "Рабочий день (перенос)"})
            elif code == "2":
                out.append({"date": d.isoformat(), "type": "short", "name": "Сокращённый день"})
            d += timedelta(days=1)
        return out
