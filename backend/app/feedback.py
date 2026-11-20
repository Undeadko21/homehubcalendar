"""«Сообщить о проблеме» (v0.21): сообщения семьи разработчику — хранятся дома, видит их утренний дозор (/api/watch).

Текст пишет человек (может быть с именами) — поэтому он только дома и в сводке дозора по токену; в публичный репозиторий
(issue, PR, журналы GitHub) не попадает: дозор пересказывает суть своими словами без имён.
kv `feedback`: [{id, at, text, screen, version, device, errors: [строки], handled}] — последние 50.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from .db import Database

KEY = "feedback"
SHOW_DAYS = 14


def items(db: Database) -> list[dict]:
    return list(db.kv_get(KEY)[0] or [])


def add(db: Database, text: str, screen: str = "", version: str = "", device: str = "", errors: list[str] | None = None) -> dict:
    text = " ".join((text or "").split())[:1000]
    if len(text) < 3:
        raise ValueError("Опишите, что случилось")
    it = {"id": secrets.token_hex(4), "at": datetime.now().isoformat(timespec="seconds"), "text": text,
          "screen": (screen or "")[:80], "version": (version or "")[:40], "device": (device or "")[:60],
          "errors": [str(e)[:200] for e in (errors or [])][:5]}
    db.kv_set(KEY, (items(db) + [it])[-50:])
    return it


def delete(db: Database, fid: str) -> None:
    db.kv_set(KEY, [f for f in items(db) if f["id"] != fid])


def problems(db: Database, now: datetime | None = None) -> list[str]:
    """Для /api/watch: свежие сообщения — строки «Сообщение: …» (дозор разбирает; postcheck не откатывает из-за них)."""
    now = now or datetime.now()
    out = []
    for f in items(db):
        try:
            if now - datetime.fromisoformat(f["at"]) > timedelta(days=SHOW_DAYS):
                continue
        except ValueError:
            continue
        where = ", ".join(x for x in (f.get("screen"), f.get("device"), f.get("version")) if x)
        err = f" · ошибки: {' | '.join(f['errors'][:2])}" if f.get("errors") else ""
        out.append(f"Сообщение [{f['id']}] {f['at'][:16]}: «{f['text'][:300]}» ({where}){err}")
    return out
