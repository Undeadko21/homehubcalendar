"""Перенос настроек одним файлом: люди, привязки календарей, поездки, шаблоны, дни рождения, списки, настройки.

Не входят: события (их возвращает синхронизация), пароли и токены (auth:*, cloud:*), очередь записи.
"""
from __future__ import annotations

import json
from datetime import datetime

from .db import Database

VERSION = 1
TABLES = ["people", "calendars", "calendar_people", "event_people", "escorts", "escort_templates",
          "birthdays", "lists", "list_items"]
KV_PREFIXES = ("settings:",)


def export(db: Database, app_version: str) -> dict:
    data = {t: db.query(f"SELECT * FROM {t}") for t in TABLES}
    kv = {}
    for r in db.query("SELECT key, value FROM kv"):
        if r["key"].startswith(KV_PREFIXES):
            kv[r["key"]] = json.loads(r["value"])
    return {"format": "homehub-settings", "v": VERSION, "app": app_version,
            "exported": datetime.now().astimezone().isoformat(timespec="seconds"), "tables": data, "kv": kv}


def import_(db: Database, blob: dict) -> dict:
    if blob.get("format") != "homehub-settings" or int(blob.get("v", 0)) > VERSION:
        raise ValueError("Это не файл настроек календаря или он от более новой версии")
    tables = blob.get("tables") or {}
    counts = {}
    with db.tx() as c:
        for t in TABLES:
            rows = tables.get(t)
            if rows is None:
                continue
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({t})")}
            if t == "calendars":
                # календари создаёт синхронизация: переносим только настройки существующих + недостающие строки
                for row in rows:
                    row = {k: v for k, v in row.items() if k in cols}
                    c.execute("INSERT OR REPLACE INTO calendars (" + ",".join(row) + ") VALUES (" + ",".join("?" * len(row)) + ")",
                              tuple(row.values()))
            else:
                c.execute(f"DELETE FROM {t}")
                for row in rows:
                    row = {k: v for k, v in row.items() if k in cols}
                    if row:
                        c.execute(f"INSERT INTO {t} (" + ",".join(row) + ") VALUES (" + ",".join("?" * len(row)) + ")",
                                  tuple(row.values()))
            counts[t] = len(rows)
        for k, v in (blob.get("kv") or {}).items():
            if k.startswith(KV_PREFIXES):
                c.execute("INSERT INTO kv (key, value, updated) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                          "value=excluded.value, updated=excluded.updated",
                          (k, json.dumps(v, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
    return counts
