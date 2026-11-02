"""Счётчик изменений для живого обновления экранов (GET /api/stream, Server-Sent Events).

Любое изменение данных (синхронизация, запись, настройки, списки) увеличивает номер; открытые экраны получают его по
SSE и перезагружают данные. Счётчик в памяти одного процесса — сервер работает одним процессом (uvicorn).
"""
import threading

_lock = threading.Lock()
rev = 0


def bump() -> int:
    global rev
    with _lock:
        rev += 1
        return rev


# Кто сделал изменение: устройство, записавшее данные, уже перезагрузилось само — ему сигнал не нужен.
_origin: dict[int, str] = {}


def mark(lo: int, hi: int, client: str) -> None:
    """Версии (lo, hi] вызваны записью устройства client."""
    with _lock:
        for r in range(lo + 1, hi + 1):
            _origin[r] = client
        for r in [r for r in _origin if r < hi - 200]:
            del _origin[r]


def origin(r: int) -> str | None:
    return _origin.get(r)
