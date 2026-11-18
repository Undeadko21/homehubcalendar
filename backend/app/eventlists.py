"""Список вещей у события: «Плавание» → список «Плавание: взять» (шапочка, очки, полотенце).

Привязка — kv `event_lists`: {uid: {"list": id, "occ": последнее вхождение, для которого сбрасывали отметки}}.
У повторяющегося события отметки «взял» сбрасываются, когда открывают следующее вхождение (`for_occurrence`).
В напоминаниях о событии, поездке и «Пора выезжать» — «Взять: …» (ещё не отмеченное).
"""
from __future__ import annotations

import threading
from datetime import datetime

from .db import Database

KEY = "event_lists"
_lock = threading.Lock()


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def load(db: Database) -> dict[str, dict]:
    return dict(db.kv_get(KEY)[0] or {})


def attach(db: Database, uid: str, list_id: int | None, own: bool = False) -> dict:
    """own — список создан для этого события: только у таких отметки сбрасываются к следующему разу
    (привязанный общий список — например покупки — не трогаем)."""
    with _lock:
        m = load(db)
        if list_id is None:
            m.pop(uid, None)
        else:
            m[uid] = {"list": int(list_id), "occ": (m.get(uid) or {}).get("occ"), "own": bool(own)}
        db.kv_set(KEY, m)
        return m


def for_occurrence(db: Database, uid: str, occurrence: str | None, now: datetime | None = None) -> dict | None:
    """Список события. Для повторяющегося: если открыли более позднее вхождение, а прошлое уже прошло,
    отметки «взял» снимаются (только у своего списка). Просмотр будущих недель заранее ничего не сбрасывает."""
    with _lock:
        m = load(db)
        link = m.get(uid)
        if not link:
            return None
        lst = next((l for l in db.lists() if l["id"] == link["list"]), None)
        if lst is None:            # список удалили — привязка больше не нужна
            m.pop(uid, None)
            db.kv_set(KEY, m)
            return None
        new, old = _dt(occurrence), _dt(link.get("occ"))
        if new is None:
            return lst
        now = now or datetime.now(new.tzinfo)
        if old is None:
            link["occ"] = new.isoformat()
        elif new > old and old < now:
            if link.get("own"):
                for i in lst["items"]:
                    if i["done"]:
                        db.update_item(i["id"], {"done": False})
                lst = next(l for l in db.lists() if l["id"] == link["list"])
            link["occ"] = new.isoformat()
        else:
            return lst
        m[uid] = link
        db.kv_set(KEY, m)
        return lst


def todo_texts(db: Database) -> dict[str, list[str]]:
    """{uid: [что ещё не отмечено]} — для напоминаний."""
    m = load(db)
    if not m:
        return {}
    lists = {l["id"]: l for l in db.lists()}
    return {uid: [i["text"] for i in lists[v["list"]]["items"] if not i["done"]][:8]
            for uid, v in m.items() if v.get("list") in lists}
