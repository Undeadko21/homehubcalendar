"""Команды с телефона, пришедшие через облако (этап 2).

Телефон вне дома не может обратиться к серверу, поэтому складывает команды в зашифрованный файл на Диске,
а сервер применяет их тем же кодом, что и обычные запросы API. Каждая команда имеет уникальный id: уже применённые
запоминаются (kv `cloud:applied`) и повторно не выполняются; попадают в снимок, чтобы телефон убрал их из очереди.

Команды:
  {"id", "t", "type": "escort", "uid", "occurrence": null|<начало>, "role": dropoff|pickup|mode|travel, "person": …}
  {"id", "t", "type": "item_add", "list_id", "text", "person_id"?}
  {"id", "t", "type": "item_done", "item_id", "done"}
  {"id", "t", "type": "item_delete", "item_id"}
  {"id", "t", "type": "event_add", "title", "date": "YYYY-MM-DD", "start"?: "HH:MM", "end"?, "all_day"?, "people"?: [id], "calendar"?, "location"?}
  {"id", "t", "type": "event_quick", "text": "Врач завтра в 18:00 Марку"}   — фраза разбирается на сервере (quick.parse); так шлёт Алиса
  {"id", "t", "type": "event_move", "text": "йогу на завтра в 19:00"}      — Алиса: ближайшее похожее событие переносится (у серии — одно вхождение)
Самые поздние применяются последними — побеждает последнее изменение.
"""
from __future__ import annotations

import logging
import sqlite3

from .db import Database

log = logging.getLogger(__name__)

KEEP_APPLIED = 1000
MAX_OPS = 200


def applied_ids(db: Database) -> list[str]:
    return (db.kv_get("cloud:applied")[0] or {}).get("ids", [])


def _valid_escort(db: Database, op: dict) -> bool:
    role, person = op.get("role"), op.get("person")
    if not isinstance(op.get("uid"), str) or not op["uid"] or role not in ("dropoff", "pickup", "mode", "travel"):
        return False
    if op.get("occurrence") is not None and not isinstance(op["occurrence"], str):
        return False
    if person is None:
        return True
    if role == "travel":
        return str(person).isdigit() and int(person) <= 240
    if role == "mode":
        return person in ("escort", "together", "home")
    return isinstance(person, str) and (person == "-" or person in {p["id"] for p in db.list_people()})


def _reject(db: Database, op: dict, why: str) -> None:
    """Запоминаем отклонённые команды: их видно в «Состоянии» (красная точка), иначе голосовая просьба пропадёт молча."""
    from datetime import datetime
    cur = (db.kv_get("ops:rejected")[0] or {}).get("items", [])
    cur.append({"at": datetime.now().isoformat(timespec="seconds"), "type": op.get("type"), "why": why[:200],
                "text": str(op.get("text") or op.get("title") or "")[:100]})
    db.kv_set("ops:rejected", {"items": cur[-10:]})


def _apply_one(db: Database, op: dict, handlers: dict) -> None:
    kind = op.get("type")
    if kind == "escort" and _valid_escort(db, op):
        person = op.get("person")
        db.set_escort(op["uid"], op.get("occurrence") or "*", op["role"], None if person is None else str(person))
    elif kind == "item_add" and str(op.get("text", "")).strip():
        person = op.get("person_id")
        if person is not None and not isinstance(person, str):
            raise ValueError("Некорректный исполнитель покупки")
        db.add_item(int(op["list_id"]), str(op["text"])[:300], person)
    elif kind == "item_done":
        db.update_item(int(op["item_id"]), {"done": bool(op.get("done"))})
    elif kind == "item_delete":
        db.delete_item(int(op["item_id"]))
    elif kind in handlers:
        handlers[kind](op)
    else:
        log.warning("Команда из облака отклонена: %s", {k: op.get(k) for k in ("id", "type")})


def apply(db: Database, ops: list[dict], handlers: dict | None = None, *,
          prepare: dict | None = None, on_commit=None) -> list[str]:
    """Для каждой команды записать результат и подтверждение в одной транзакции.

    Обработчики могут ставить внешнюю запись в локальную очередь, но не отправляют её из транзакции.
    """
    new: list[str] = []
    commands = [op for op in ops[:MAX_OPS] if isinstance(op, dict)]
    for op in sorted(commands, key=lambda o: o.get("t") if isinstance(o.get("t"), (int, float)) else 0):
        oid = str(op.get("id") or "")
        if not oid or oid in applied_ids(db):
            continue
        kind = op.get("type")
        resolve = (prepare or {}).get(kind) if isinstance(kind, str) else None
        error = None
        if resolve:
            try:
                op = resolve(op)
            except sqlite3.Error:
                raise
            except Exception as exc:
                error = exc
        with db.tx():
            done = applied_ids(db)
            if oid in done:
                continue
            try:
                with db.tx():
                    if error is not None:
                        raise error
                    _apply_one(db, op, handlers or {})
            except sqlite3.Error:
                raise   # Ошибка хранилища: не подтверждаем, клиент сможет повторить.
            except Exception as e:
                log.warning("Команда из облака не применена (%s): %s", oid, type(e).__name__)
                if op.get("type") in ("event_add", "event_quick", "event_move"):
                    _reject(db, op, str(getattr(e, "detail", None) or e))
            db.kv_set("cloud:applied", {"ids": (done + [oid])[-KEEP_APPLIED:]})
        new.append(oid)
        if on_commit and kind in ("event_add", "event_quick", "event_move"):
            on_commit()
    return new
