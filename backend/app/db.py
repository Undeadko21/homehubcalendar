"""Хранилище на SQLite.

Храним «сырые» данные календарей (iCalendar-текст каждого объекта), а
повторяющиеся события разворачиваем уже при запросе нужного диапазона.
Так синхронизация остаётся простой, а логику отображения можно менять,
не пересинхронизируя данные.

Схема мигрирует через список MIGRATIONS: чтобы изменить схему, допишите
новый шаг в конец списка (старые шаги не трогать).
"""
from __future__ import annotations

import base64
import json
import os
import re
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
    # 3 — кто отвозит/забирает ребёнка
    """
    ALTER TABLE people ADD COLUMN needs_escort INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE escorts (
        uid TEXT NOT NULL,
        occurrence TEXT NOT NULL,   -- '*' — вся серия, иначе время начала вхождения (ISO)
        role TEXT NOT NULL,         -- dropoff | pickup
        person_id TEXT NOT NULL,    -- id взрослого или '-' — сопровождение не нужно
        updated TEXT NOT NULL,
        PRIMARY KEY (uid, occurrence, role)
    );
    """,
    # 4 — шаблоны поездок по дням недели, дни рождения, списки дел и покупок
    """
    CREATE TABLE escort_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        child_id TEXT NOT NULL,
        weekday INTEGER NOT NULL,            -- 0 — понедельник
        match TEXT NOT NULL DEFAULT '',      -- слова в названии через запятую; пусто — любое событие
        dropoff TEXT NOT NULL DEFAULT '',    -- id взрослого, '-' — не нужно, '' — не задано
        pickup TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE birthdays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        month INTEGER NOT NULL,
        day INTEGER NOT NULL,
        year INTEGER
    );
    CREATE TABLE lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        sort INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE list_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        list_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        person_id TEXT,
        created TEXT NOT NULL,
        done_at TEXT
    );
    INSERT INTO lists (name, sort) VALUES ('Покупки', 0), ('Дела', 1);
    """,
    # срок дела (YYYY-MM-DD); исполнитель уже есть — person_id
    """
    ALTER TABLE list_items ADD COLUMN due TEXT;
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
        self.encrypt_secrets()

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
                """INSERT INTO people (id, name, color, emoji, sort, hidden, keywords, needs_escort)
                   VALUES (:id, :name, :color, :emoji, :sort, :hidden, :keywords, :needs_escort)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, color=excluded.color,
                   emoji=excluded.emoji, sort=excluded.sort, hidden=excluded.hidden,
                   keywords=excluded.keywords, needs_escort=excluded.needs_escort""",
                {
                    "id": p["id"],
                    "name": p.get("name", p["id"]),
                    "color": p.get("color", "#6b7280"),
                    "emoji": p.get("emoji", ""),
                    "sort": int(p.get("sort", 0)),
                    "hidden": int(bool(p.get("hidden", False))),
                    "keywords": str(p.get("keywords", "") or ""),
                    "needs_escort": int(bool(p.get("needs_escort", False))),
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

    # ---------- кто отвозит/забирает ----------
    def escorts(self) -> dict[tuple[str, str, str], str]:
        return {(r["uid"], r["occurrence"], r["role"]): r["person_id"]
                for r in self.query("SELECT uid, occurrence, role, person_id FROM escorts")}

    def set_escort(self, uid: str, occurrence: str, role: str, person_id: str | None) -> None:
        """person_id=None — снять назначение (для вхождения вернётся назначение серии)."""
        with self.tx() as c:
            if person_id is None:
                c.execute("DELETE FROM escorts WHERE uid=? AND occurrence=? AND role=?", (uid, occurrence, role))
            else:
                c.execute(
                    "INSERT INTO escorts (uid, occurrence, role, person_id, updated) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(uid, occurrence, role) DO UPDATE SET person_id=excluded.person_id, "
                    "updated=excluded.updated",
                    (uid, occurrence, role, person_id, now_iso()),
                )

    # ---------- шаблоны поездок ----------
    def templates(self) -> list[dict]:
        return self.query("SELECT * FROM escort_templates ORDER BY weekday, child_id, id")

    def save_template(self, t: dict) -> int:
        vals = (t["child_id"], int(t["weekday"]), (t.get("match") or "").strip(),
                t.get("dropoff") or "", t.get("pickup") or "")
        with self.tx() as c:
            if t.get("id"):
                c.execute("UPDATE escort_templates SET child_id=?, weekday=?, match=?, dropoff=?, pickup=? WHERE id=?",
                          (*vals, t["id"]))
                return int(t["id"])
            cur = c.execute("INSERT INTO escort_templates (child_id, weekday, match, dropoff, pickup) VALUES (?,?,?,?,?)", vals)
            return int(cur.lastrowid)

    def delete_template(self, tid: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM escort_templates WHERE id=?", (tid,))

    # ---------- дни рождения ----------
    def birthdays(self) -> list[dict]:
        return self.query("SELECT * FROM birthdays ORDER BY month, day, name")

    def save_birthday(self, b: dict) -> int:
        vals = (b["name"].strip(), int(b["month"]), int(b["day"]), b.get("year"))
        with self.tx() as c:
            if b.get("id"):
                c.execute("UPDATE birthdays SET name=?, month=?, day=?, year=? WHERE id=?", (*vals, b["id"]))
                return int(b["id"])
            return int(c.execute("INSERT INTO birthdays (name, month, day, year) VALUES (?,?,?,?)", vals).lastrowid)

    def delete_birthday(self, bid: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM birthdays WHERE id=?", (bid,))

    # ---------- списки ----------
    def lists(self) -> list[dict]:
        lists = self.query("SELECT * FROM lists ORDER BY sort, id")
        items = self.query("SELECT * FROM list_items ORDER BY done, id")
        for l in lists:
            l["items"] = [dict(i, done=bool(i["done"])) for i in items if i["list_id"] == l["id"]]
        return lists

    def add_list(self, name: str) -> int:
        with self.tx() as c:
            n = c.execute("SELECT COALESCE(MAX(sort), -1) + 1 FROM lists").fetchone()[0]
            return int(c.execute("INSERT INTO lists (name, sort) VALUES (?,?)", (name.strip(), n)).lastrowid)

    def rename_list(self, lid: int, name: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE lists SET name=? WHERE id=?", (name.strip(), lid))

    def delete_list(self, lid: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM list_items WHERE list_id=?", (lid,))
            c.execute("DELETE FROM lists WHERE id=?", (lid,))

    def add_item(self, lid: int, text: str, person_id: str | None = None, due: str | None = None) -> int:
        with self.tx() as c:
            return int(c.execute("INSERT INTO list_items (list_id, text, person_id, due, created) VALUES (?,?,?,?,?)",
                                 (lid, text.strip(), person_id or None, due or None, now_iso())).lastrowid)

    def update_item(self, iid: int, fields: dict) -> None:
        sets, vals = [], []
        if "text" in fields:
            sets.append("text=?"); vals.append(fields["text"].strip())
        if "person_id" in fields:
            sets.append("person_id=?"); vals.append(fields["person_id"] or None)
        if "due" in fields:
            sets.append("due=?"); vals.append(fields["due"] or None)
        if "done" in fields:
            sets += ["done=?", "done_at=?"]; vals += [int(bool(fields["done"])), now_iso() if fields["done"] else None]
        if sets:
            with self.tx() as c:
                c.execute(f"UPDATE list_items SET {', '.join(sets)} WHERE id=?", (*vals, iid))

    def delete_item(self, iid: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM list_items WHERE id=?", (iid,))

    def clear_done(self, lid: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM list_items WHERE list_id=? AND done=1", (lid,))

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

    def remove_source(self, source_id: str) -> None:
        """Убирает календари источника вместе с их событиями (для подписок, которые пользователь удалил)."""
        with self.tx() as c:
            keys = [r["key"] for r in c.execute("SELECT key FROM calendars WHERE source_id=?", (source_id,)).fetchall()]
            for k in keys:
                c.execute("DELETE FROM objects WHERE calendar_key=?", (k,))
                c.execute("DELETE FROM calendar_people WHERE calendar_key=?", (k,))
            c.execute("DELETE FROM calendars WHERE source_id=?", (source_id,))
            c.execute("DELETE FROM sync_status WHERE source_id=?", (source_id,))

    # ---------- объекты ----------
    def replace_objects(self, calendar_key: str, objects: dict[str, str]) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM objects WHERE calendar_key=?", (calendar_key,))
            c.executemany(
                "INSERT INTO objects (calendar_key, href, ics) VALUES (?,?,?)",
                [(calendar_key, href, ics) for href, ics in objects.items()],
            )

    def objects_map(self, calendar_key: str) -> dict[str, str]:
        return {r["href"]: r["ics"] for r in self.query("SELECT href, ics FROM objects WHERE calendar_key=?", (calendar_key,))}

    def put_object(self, calendar_key: str, href: str, ics: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO objects (calendar_key, href, ics) VALUES (?,?,?) "
                      "ON CONFLICT(calendar_key, href) DO UPDATE SET ics=excluded.ics",
                      (calendar_key, href, ics))

    def delete_object(self, calendar_key: str, href: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM objects WHERE calendar_key=? AND href=?", (calendar_key, href))

    def find_object(self, uid: str, calendar_key: str | None = None) -> tuple[str, str, str] | None:
        """(calendar_key, href, ics) объекта с таким UID."""
        sql = "SELECT calendar_key, href, ics FROM objects WHERE ics LIKE ?"
        params: list = [f"%UID:{uid}%"]
        if calendar_key:
            sql += " AND calendar_key=?"
            params.append(calendar_key)
        for r in self.query(sql, tuple(params)):
            if re.search(rf"^UID:{re.escape(uid)}\s*$", r["ics"], re.M):
                return r["calendar_key"], r["href"], r["ics"]
        return None

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
    # Секреты (пароли приложений, токен и ключ облака) лежат в базе зашифрованными ключом из файла secret.key
    # рядом с базой (создаётся при первом запуске, права 0600). Так утекшая копия самой базы секретов не раскрывает.
    # В резервной копии на Диске секреты открыты — она целиком зашифрована ключом облака (см. backup.snapshot_db),
    # а после восстановления при запуске шифруются заново.
    SECRET_KEYS = ("auth:", "cloud:token", "cloud:key", "ics:feeds")

    def _is_secret(self, key: str) -> bool:
        return key.startswith(self.SECRET_KEYS)

    def _box(self):
        if getattr(self, "_aes", None) is None:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            path = Path(self.path).with_name("secret.key")
            if path.exists():
                key = path.read_bytes()
            else:
                key = os.urandom(32)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(key)
            self._aes = AESGCM(key)
        return self._aes

    def _seal(self, text: str) -> str:
        nonce = os.urandom(12)
        return "enc1:" + base64.b64encode(nonce + self._box().encrypt(nonce, text.encode(), b"homehub-kv")).decode()

    def _unseal(self, text: str) -> str:
        raw = base64.b64decode(text[5:])
        return self._box().decrypt(raw[:12], raw[12:], b"homehub-kv").decode()

    def encrypt_secrets(self) -> int:
        """Шифрует секреты, лежащие открытым текстом (после обновления или восстановления из копии)."""
        n = 0
        for r in self.query("SELECT key, value FROM kv"):
            if self._is_secret(r["key"]) and not r["value"].startswith('"enc1:'):
                with self.tx() as c:
                    c.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(self._seal(r["value"])), r["key"]))
                n += 1
        return n

    def kv_get(self, key: str):
        rows = self.query("SELECT value, updated FROM kv WHERE key=?", (key,))
        if not rows:
            return None, None
        value = json.loads(rows[0]["value"])
        if isinstance(value, str) and value.startswith("enc1:") and self._is_secret(key):
            value = json.loads(self._unseal(value))
        return value, rows[0]["updated"]

    def kv_set(self, key: str, value) -> None:
        text = json.dumps(value, ensure_ascii=False)
        if self._is_secret(key):
            text = json.dumps(self._seal(text))
        with self.tx() as c:
            c.execute(
                "INSERT INTO kv (key, value, updated) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, text, now_iso()),
            )
