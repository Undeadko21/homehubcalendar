"""Хранилище на SQLite.

Храним «сырые» данные календарей (iCalendar-текст каждого объекта), а
повторяющиеся события разворачиваем уже при запросе нужного диапазона.
Так синхронизация остаётся простой, а логику отображения можно менять,
не пересинхронизируя данные.

Схема мигрирует через список MIGRATIONS: чтобы изменить схему, допишите
новый шаг в конец списка (старые шаги не трогать).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

MIGRATIONS: list[str] = [
    # 1 — начальная схема
    """
    CREATE TABLE people (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        color TEXT NOT NULL DEFAULT '#6b7280',
        emoji TEXT NOT NULL DEFAULT '',
        sort INTEGER NOT NULL DEFAULT 0,
        hidden INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE calendars (
        key TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        remote_id TEXT NOT NULL,
        name TEXT NOT NULL,
        person_id TEXT,
        color TEXT,
        hidden INTEGER NOT NULL DEFAULT 0,
        private INTEGER NOT NULL DEFAULT 0,
        configured INTEGER NOT NULL DEFAULT 0,
        last_seen TEXT
    );
    CREATE TABLE objects (
        calendar_key TEXT NOT NULL,
        href TEXT NOT NULL,
        ics TEXT NOT NULL,
        PRIMARY KEY (calendar_key, href)
    );
    CREATE TABLE sync_status (
        source_id TEXT PRIMARY KEY,
        last_attempt TEXT,
        last_ok TEXT,
        last_error TEXT,
        objects_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE kv (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated TEXT NOT NULL
    );
    """,
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
                self._conn.executescript(script)
                self._conn.execute(f"PRAGMA user_version = {i}")
            self._conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # ---------- люди ----------
    def list_people(self) -> list[dict]:
        return self.query("SELECT * FROM people ORDER BY sort, name")

    def upsert_person(self, p: dict) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO people (id, name, color, emoji, sort, hidden)
                   VALUES (:id, :name, :color, :emoji, :sort, :hidden)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, color=excluded.color,
                   emoji=excluded.emoji, sort=excluded.sort, hidden=excluded.hidden""",
                {
                    "id": p["id"],
                    "name": p.get("name", p["id"]),
                    "color": p.get("color", "#6b7280"),
                    "emoji": p.get("emoji", ""),
                    "sort": int(p.get("sort", 0)),
                    "hidden": int(bool(p.get("hidden", False))),
                },
            )

    def delete_person(self, person_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM people WHERE id=?", (person_id,))
            c.execute("UPDATE calendars SET person_id=NULL WHERE person_id=?", (person_id,))

    # ---------- календари ----------
    def list_calendars(self) -> list[dict]:
        return self.query("SELECT * FROM calendars ORDER BY source_id, name")

    def get_calendar(self, key: str) -> dict | None:
        rows = self.query("SELECT * FROM calendars WHERE key=?", (key,))
        return rows[0] if rows else None

    def touch_calendar(self, key: str, source_id: str, remote_id: str, name: str, defaults: dict) -> None:
        """Регистрирует календарь, найденный при синхронизации.

        Настройки, заданные пользователем в интерфейсе (configured=1),
        не перезаписываются значениями из config.yaml.
        """
        with self.tx() as c:
            row = c.execute("SELECT configured FROM calendars WHERE key=?", (key,)).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO calendars (key, source_id, remote_id, name, person_id, color, hidden, private, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (key, source_id, remote_id, name, defaults.get("person"), defaults.get("color"),
                     int(bool(defaults.get("hidden"))), int(bool(defaults.get("private"))), now_iso()),
                )
            elif row["configured"]:
                c.execute("UPDATE calendars SET name=?, last_seen=? WHERE key=?", (name, now_iso(), key))
            else:
                c.execute(
                    """UPDATE calendars SET name=?, person_id=?, color=?, hidden=?, private=?, last_seen=?
                       WHERE key=?""",
                    (name, defaults.get("person"), defaults.get("color"), int(bool(defaults.get("hidden"))),
                     int(bool(defaults.get("private"))), now_iso(), key),
                )

    def update_calendar(self, key: str, fields: dict) -> None:
        allowed = {"person_id", "color", "hidden", "private"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        sets["configured"] = 1
        cols = ", ".join(f"{k}=:{k}" for k in sets)
        with self.tx() as c:
            c.execute(f"UPDATE calendars SET {cols} WHERE key=:key", {**sets, "key": key})

    # ---------- объекты ----------
    def replace_objects(self, calendar_key: str, objects: dict[str, str]) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM objects WHERE calendar_key=?", (calendar_key,))
            c.executemany(
                "INSERT INTO objects (calendar_key, href, ics) VALUES (?,?,?)",
                [(calendar_key, href, ics) for href, ics in objects.items()],
            )

    def objects_for(self, calendar_key: str) -> list[str]:
        return [r["ics"] for r in self.query("SELECT ics FROM objects WHERE calendar_key=?", (calendar_key,))]

    # ---------- статус синхронизации ----------
    def set_sync_status(self, source_id: str, ok: bool, error: str | None = None, count: int = 0) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO sync_status (source_id, last_attempt, last_ok, last_error, objects_count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(source_id) DO UPDATE SET last_attempt=excluded.last_attempt,
                     last_ok=COALESCE(excluded.last_ok, sync_status.last_ok),
                     last_error=excluded.last_error,
                     objects_count=CASE WHEN excluded.last_ok IS NOT NULL THEN excluded.objects_count
                                        ELSE sync_status.objects_count END""",
                (source_id, now_iso(), now_iso() if ok else None, error, count),
            )

    def sync_status(self) -> list[dict]:
        return self.query("SELECT * FROM sync_status ORDER BY source_id")

    # ---------- произвольный кэш ----------
    def kv_get(self, key: str):
        rows = self.query("SELECT value, updated FROM kv WHERE key=?", (key,))
        if not rows:
            return None, None
        return json.loads(rows[0]["value"]), rows[0]["updated"]

    def kv_set(self, key: str, value) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO kv (key, value, updated) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, json.dumps(value, ensure_ascii=False), now_iso()),
            )
