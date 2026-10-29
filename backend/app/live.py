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
