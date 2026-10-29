"""Журнал времени ответов API: видно, какие запросы медленные и когда. Хранится в памяти (до перезапуска)."""
from __future__ import annotations

import threading
from collections import defaultdict, deque
from datetime import datetime

SLOW_MS = 700          # медленным считаем запрос дольше этого
KEEP_SLOW = 100
KEEP_SAMPLES = 200     # последних замеров на маршрут


class PerfLog:
    def __init__(self):
        self._lock = threading.Lock()
        self._samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=KEEP_SAMPLES))
        self._slow: deque = deque(maxlen=KEEP_SLOW)
        self._errors: dict[str, int] = defaultdict(int)

    def record(self, method: str, route: str, ms: float, status: int, query: str = "", at: datetime | None = None) -> None:
        key = f"{method} {route}"
        with self._lock:
            self._samples[key].append(ms)
            if status >= 500:
                self._errors[key] += 1
            if ms >= SLOW_MS:
                self._slow.append({"at": (at or datetime.now()).isoformat(timespec="seconds"), "route": key,
                                   "ms": round(ms), "status": status, "query": query[:200]})

    def summary(self) -> dict:
        with self._lock:
            rows = []
            for key, d in self._samples.items():
                v = sorted(d)
                rows.append({"route": key, "n": len(v), "avg": round(sum(v) / len(v)),
                             "p95": round(v[min(len(v) - 1, int(len(v) * 0.95))]), "max": round(v[-1]),
                             "errors": self._errors.get(key, 0)})
            rows.sort(key=lambda r: r["p95"], reverse=True)
            return {"slow_ms": SLOW_MS, "routes": rows, "slow": list(reversed(self._slow))}

    def slow_count(self) -> int:
        with self._lock:
            return len(self._slow)
