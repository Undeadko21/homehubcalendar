"""Тренды для дозора (v0.21): раз в день — короткий итог (скорость маршрутов, ошибки экранов), сравнение с прошлой неделей.

Медленное ухудшение («лента стала на 60% медленнее за две недели») не видно по одному утру — его видно по истории.
kv `trend:days`: [{date, routes: {маршрут: [p95, n]}, errors}] — 60 дней. Только счётчики, без запросов и текстов.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median

from .db import Database

KEY = "trend:days"
SLOWER = 1.5        # p95 последних 3 дней больше недели назад в 1,5 раза…
MIN_MS = 400        # …и сам не меньше 400 мс — тогда «Тренд: медленнее»
ERR_X, ERR_MIN = 2.0, 3


def days(db: Database) -> list[dict]:
    return list(db.kv_get(KEY)[0] or [])


def record(db: Database, perf_routes: list[dict], client_errors: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    since = datetime.combine(today, datetime.min.time())
    errs = 0
    for e in client_errors:
        try:
            if datetime.fromisoformat(str(e.get("at"))[:19]) >= since:
                errs += 1
        except ValueError:
            pass
    row = {"date": today.isoformat(), "errors": errs,
           "routes": {r["route"]: [r["p95"], r["n"]] for r in perf_routes if r.get("n", 0) >= 5}}
    db.kv_set(KEY, ([d for d in days(db) if d["date"] != row["date"]] + [row])[-60:])
    return row


def problems(db: Database) -> list[str]:
    """«Тренд: …» — что заметно ухудшилось: последние 3 дня против дней 4–10 назад (нужно по 3 дня с данными)."""
    hist = sorted(days(db), key=lambda d: d["date"])
    if len(hist) < 6:
        return []
    recent, base = hist[-3:], hist[-10:-3]
    out = []
    routes = set().union(*(d["routes"].keys() for d in recent))
    for r in sorted(routes):
        now_v = [d["routes"][r][0] for d in recent if r in d["routes"]]
        was_v = [d["routes"][r][0] for d in base if r in d["routes"]]
        if len(now_v) >= 2 and len(was_v) >= 3:
            a, b = median(now_v), median(was_v)
            if a >= MIN_MS and a > b * SLOWER:
                out.append(f"Тренд: {r} медленнее — p95 ~{round(a)} мс, неделю назад ~{round(b)} мс")
    ea, eb = sum(d["errors"] for d in recent) / len(recent), sum(d["errors"] for d in base) / max(1, len(base))
    if ea >= ERR_MIN and ea > eb * ERR_X:
        out.append(f"Тренд: ошибок экранов больше — ~{ea:.0f} в день, неделю назад ~{eb:.0f}")
    return out


def summary(db: Database) -> list[dict]:
    """Для /api/watch: 14 дней — дата, ошибки, три самых медленных маршрута."""
    out = []
    for d in sorted(days(db), key=lambda d: d["date"])[-14:]:
        top = sorted(d["routes"].items(), key=lambda kv: -kv[1][0])[:3]
        out.append({"date": d["date"], "errors": d["errors"], "slowest": {k: v[0] for k, v in top}})
    return out
