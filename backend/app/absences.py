"""«Болеет / не идёт»: человек пропускает свои события в диапазоне дат (болезнь, отъезд, отгул).

Событие, все участники которого в эти дни отсутствуют, помечается `absent = {"note", "people"}`:
показывается приглушённым, не занимает человека (не конфликтует), а у события ребёнка
режим поездки становится «absent» — водитель не нужен, поездка у взрослого не создаётся.
Хранится в kv `absences`: [{id, person, from, to, note}] (даты включительно).
"""
from __future__ import annotations

import secrets
from datetime import date

from .db import Database

KEY = "absences"
NOTES = ("болеет", "уехал(а)", "не идёт")


def load(db: Database) -> list[dict]:
    return list(db.kv_get(KEY)[0] or [])


def clean(items: list[dict], known: set[str]) -> list[dict]:
    out = []
    for a in items or []:
        try:
            d0, d1 = date.fromisoformat(str(a["from"])[:10]), date.fromisoformat(str(a.get("to") or a["from"])[:10])
        except (KeyError, ValueError):
            continue
        if a.get("person") not in known:
            continue
        if d1 < d0:
            d0, d1 = d1, d0
        if (d1 - d0).days > 366:
            continue
        out.append({"id": str(a.get("id") or secrets.token_hex(4))[:16], "person": a["person"],
                    "from": d0.isoformat(), "to": d1.isoformat(), "note": str(a.get("note") or "не идёт").strip()[:40]})
    out.sort(key=lambda a: (a["from"], a["person"]))
    return out[:200]


def save(db: Database, items: list[dict], known: set[str]) -> list[dict]:
    v = clean(items, known)
    db.kv_set(KEY, v)
    return v


def prune(items: list[dict], today: date) -> list[dict]:
    """Прошедшие больше месяца назад — не нужны."""
    return [a for a in items if (today - date.fromisoformat(a["to"])).days <= 31]


def _ranges(items: list[dict]) -> dict[str, list[tuple[date, date, str]]]:
    by: dict[str, list[tuple[date, date, str]]] = {}
    for a in items:
        by.setdefault(a["person"], []).append((date.fromisoformat(a["from"]), date.fromisoformat(a["to"]), a["note"]))
    return by


def _days(e: dict) -> tuple[date, date]:
    d0 = date.fromisoformat(e["start"][:10])
    d1 = date.fromisoformat((e.get("end") or e["start"])[:10])
    if e.get("all_day") and d1 > d0:
        d1 = d1.fromordinal(d1.toordinal() - 1)   # конец «весь день» не включается
    return d0, max(d0, d1)


def mark(events: list[dict], items: list[dict], children: set[str] | None = None) -> None:
    """Ставит событию `absent`, если в его дни отсутствуют все его участники; у события с детьми смотрим только детей
    (ребёнок болеет — секция отменяется, даже если с ним ходит взрослый). Многодневное — по пересечению дат."""
    if not items:
        return
    by = _ranges(items)
    children = children or set()
    for e in events:
        who = [p for p in e.get("people", []) if not p.startswith("_")]
        if not who or e.get("duty"):
            continue
        kids = [p for p in who if p in children]
        check = kids or who
        e0, e1 = _days(e)
        notes = []
        for pid in check:
            hit = next((n for d0, d1, n in by.get(pid, []) if d0 <= e1 and e0 <= d1), None)
            if hit is None:
                break
            notes.append(hit)
        else:
            e["absent"] = {"note": notes[0] if len(set(notes)) == 1 else "не идут", "people": check}


def away(items: list[dict]):
    """Функция «человек отсутствует в этот день» — для подбора водителя (уехавший взрослый не свободен)."""
    by = _ranges(items)
    return lambda pid, day: any(d0 <= day <= d1 for d0, d1, _ in by.get(pid, []))
