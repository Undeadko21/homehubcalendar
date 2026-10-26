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
    # 2 — несколько владельцев у календаря, участники отдельных событий, слова автопривязки
    """
    CREATE TABLE calendar_people (
        calendar_key TEXT NOT NULL,
        person_id TEXT NOT NULL,
        PRIMARY KEY (calendar_key, person_id)
    );
    INSERT INTO calendar_people (calendar_key, person_id)
        SELECT key, person_id FROM calendars WHERE person_id IS NOT NULL;
    CREATE TABLE event_people (
        uid TEXT PRIMARY KEY,
        people TEXT NOT NULL,
        updated TEXT NOT NULL
    );
    ALTER TABLE people ADD COLUMN keywords TEXT NOT NULL DEFAULT '';
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
                """INSERT INTO people (id, name, color, emoji, sort, hidden, keywords)
                   VALUES (:id, :name, :color, :emoji, :sort, :hidden, :keywords)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, color=excluded.color,
                   emoji=excluded.emoji, sort=excluded.sort, hidden=excluded.hidden,
                   keywords=excluded.keywords""",
                {
                    "id": p["id"],
                    "name": p.get("name", p["id"]),
                    "color": p.get("color", "#6b7280"),
                    "emoji": p.get("emoji", ""),
                    "sort": int(p.get("sort", 0)),
                    "hidden": int(bool(p.get("hidden", False))),
                    "keywords": str(p.get("keywords", "") or ""),
                },
            )

    def delete_person(self, person_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM people WHERE id=?", (person_id,))
            c.execute("UPDATE calendars SET person_id=NULL WHERE person_id=?", (person_id,))
            c.execute("DELETE FROM calendar_people WHERE person_id=?", (person_id,))

    # ---------- календари ----------
    def _attach_people(self, rows: list[dict]) -> list[dict]:
        links: dict[str, list[str]] = {}
        for r in self.query(
            """SELECT cp.calendar_key, cp.person_id FROM calendar_people cp
               LEFT JOIN people p ON p.id = cp.person_id
               ORDER BY COALESCE(p.sort, 999), cp.person_id"""
        ):
            links.setdefault(r["calendar_key"], []).append(r["person_id"])
        for r in rows:
            r["people"] = links.get(r["key"], [])
        return rows

    def list_calendars(self) -> list[dict]:
        return self._attach_people(self.query("SELECT * FROM calendars ORDER BY source_id, name"))

    def get_calendar(self, key: str) -> dict | None:
        rows = self._attach_people(self.query("SELECT * FROM calendars WHERE key=?", (key,)))
        return rows[0] if rows else None

    @staticmethod
    def _set_people(c: sqlite3.Connection, key: str, people: list[str]) -> None:
        c.execute("DELETE FROM calendar_people WHERE calendar_key=?", (key,))
        c.executemany("INSERT OR IGNORE INTO calendar_people (calendar_key, person_id) VALUES (?,?)",
                      [(key, p) for p in dict.fromkeys(people) if p])
        c.execute("UPDATE calendars SET person_id=? WHERE key=?", (people[0] if people else None, key))

    def touch_calendar(self, key: str, source_id: str, remote_id: str, name: str, defaults: dict) -> None:
        """Регистрирует календарь, найденный при синхронизации.

        Настройки, заданные пользователем в интерфейсе (configured=1),
        не перезаписываются значениями из config.yaml.
        """
        people = list(defaults.get("people") or ([defaults["person"]] if defaults.get("person") else []))
        with self.tx() as c:
            row = c.execute("SELECT configured FROM calendars WHERE key=?", (key,)).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO calendars (key, source_id, remote_id, name, color, hidden, private, last_seen)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (key, source_id, remote_id, name, defaults.get("color"),
                     int(bool(defaults.get("hidden"))), int(bool(defaults.get("private"))), now_iso()),
                )
                self._set_people(c, key, people)
            elif row["configured"]:
                c.execute("UPDATE calendars SET name=?, last_seen=? WHERE key=?", (name, now_iso(), key))
            else:
                c.execute(
                    """UPDATE calendars SET name=?, color=?, hidden=?, private=?, last_seen=?
                       WHERE key=?""",
                    (name, defaults.get("color"), int(bool(defaults.get("hidden"))),
                     int(bool(defaults.get("private"))), now_iso(), key),
                )
                self._set_people(c, key, people)

    def update_calendar(self, key: str, fields: dict) -> None:
        fields = dict(fields)
        if "person_id" in fields and "people" not in fields:  # старый формат API
            fields["people"] = [fields["person_id"]] if fields["person_id"] else []
        sets = {k: v for k, v in fields.items() if k in {"color", "hidden", "private"}}
        sets["configured"] = 1
        cols = ", ".join(f"{k}=:{k}" for k in sets)
        with self.tx() as c:
            c.execute(f"UPDATE calendars SET {cols} WHERE key=:key", {**sets, "key": key})
            if "people" in fields:
                self._set_people(c, key, list(fields["people"] or []))

    # ---------- участники отдельных событий ----------
    def event_people(self) -> dict[str, list[str]]:
        return {r["uid"]: json.loads(r["people"]) for r in self.query("SELECT uid, people FROM event_people")}

    def set_event_people(self, uid: str, people: list[str] | None) -> None:
        """people=None — вернуть участников по умолчанию (по календарю и словам)."""
        with self.tx() as c:
            if people is None:
                c.execute("DELETE FROM event_people WHERE uid=?", (uid,))
            else:
                c.execute(
                    "INSERT INTO event_people (uid, people, updated) VALUES (?,?,?) "
                    "ON CONFLICT(uid) DO UPDATE SET people=excluded.people, updated=excluded.updated",
                    (uid, json.dumps(list(dict.fromkeys(people)), ensure_ascii=False), now_iso()),
                )

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
