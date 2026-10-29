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
Самые поздние применяются последними — побеждает последнее изменение.
"""
from __future__ import annotations

import logging

from .db import Database

log = logging.getLogger(__name__)

KEEP_APPLIED = 1000
MAX_OPS = 200


def applied_ids(db: Database) -> list[str]:
    return (db.kv_get("cloud:applied")[0] or {}).get("ids", [])


def _valid_escort(db: Database, op: dict) -> bool:
    role, person = op.get("role"), op.get("person")
    if not op.get("uid") or role not in ("dropoff", "pickup", "mode", "travel"):
        return False
    if person is None:
        return True
    if role == "travel":
        return str(person).isdigit() and int(person) <= 240
    if role == "mode":
        return person in ("escort", "together", "home")
    return person == "-" or person in {p["id"] for p in db.list_people()}


def _reject(db: Database, op: dict, why: str) -> None:
    """Запоминаем отклонённые команды: их видно в «Состоянии» (красная точка), иначе голосовая просьба пропадёт молча."""
    from datetime import datetime
    cur = (db.kv_get("ops:rejected")[0] or {}).get("items", [])
    cur.append({"at": datetime.now().isoformat(timespec="seconds"), "type": op.get("type"), "why": why[:200],
                "text": str(op.get("text") or op.get("title") or "")[:100]})
    db.kv_set("ops:rejected", {"items": cur[-10:]})


def apply(db: Database, ops: list[dict], handlers: dict | None = None) -> list[str]:
    """Применяет новые команды, возвращает id применённых (в том числе отклонённых как некорректные)."""
    done = applied_ids(db)
    seen = set(done)
    new: list[str] = []
    for op in sorted(ops[:MAX_OPS], key=lambda o: o.get("t", 0)):
        oid = str(op.get("id") or "")
        if not oid or oid in seen:
            continue
        try:
            kind = op.get("type")
            if kind == "escort" and _valid_escort(db, op):
                p = op.get("person")
                db.set_escort(op["uid"], op.get("occurrence") or "*", op["role"], None if p is None else str(p))
            elif kind == "item_add" and str(op.get("text", "")).strip():
                db.add_item(int(op["list_id"]), str(op["text"])[:300], op.get("person_id"))
            elif kind == "item_done":
                db.update_item(int(op["item_id"]), {"done": bool(op.get("done"))})
            elif kind == "item_delete":
                db.delete_item(int(op["item_id"]))
            elif handlers and kind in handlers:
                handlers[kind](op)
            else:
                log.warning("Команда из облака отклонена: %s", {k: op.get(k) for k in ("id", "type")})
        except Exception as e:  # битая команда не должна блокировать остальные
            log.warning("Команда из облака не применена (%s): %s", oid, e)
            if op.get("type") in ("event_add", "event_quick"):
                _reject(db, op, str(getattr(e, "detail", None) or e))
        seen.add(oid)
        new.append(oid)
    if new:
        db.kv_set("cloud:applied", {"ids": (done + new)[-KEEP_APPLIED:]})
    return new
