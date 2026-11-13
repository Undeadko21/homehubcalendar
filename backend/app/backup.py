"""Резервная копия базы на Яндекс.Диск: раз в сутки, зашифрованная ключом облака, хранится последние N штук.

В базе лежат пароль приложения CalDAV и токен Диска, поэтому файл шифруется (AES-256-GCM, AAD `homehub-backup-v1`).
Ключ — тот же, что в коде подключения приложения и в переменной HOMEHUB_KEY навыка Алисы: потеряв сервер, его
можно взять оттуда. Восстановление: `python backend/tools/restore_backup.py файл ключ выход.db`.
"""
from __future__ import annotations

import gzip
import logging
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .cloud import CloudError, CloudSync, YandexDisk
from .db import Database

log = logging.getLogger(__name__)

DIR = "app:/backups"
FILES_DIR = "app:/files"          # вложения событий и дел: по файлу на вложение, имя = id, тот же шифр, что у копии базы
PREFIX, SUFFIX = "homehub-", ".db.gz.enc"
KEEP = 14
AAD = b"homehub-backup-v1"


def snapshot_db(path: Path, db: Database | None = None) -> bytes:
    """Согласованная копия SQLite (во время работы сервера) — через backup API, затем gzip.
    Если передан db, секреты в копии расшифровываются: локальный ключ secret.key в копию не попадает,
    а сама копия зашифрована ключом облака; после восстановления секреты шифруются заново."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "copy.db"
        src = sqlite3.connect(str(path))
        dst = sqlite3.connect(str(out))
        try:
            src.backup(dst)
            if db is not None:
                import json
                for key, value in dst.execute("SELECT key, value FROM kv").fetchall():
                    if db._is_secret(key) and value.startswith('"enc1:'):
                        dst.execute("UPDATE kv SET value=? WHERE key=?", (db._unseal(json.loads(value)), key))
                dst.commit()
        finally:
            dst.close()
            src.close()
        return gzip.compress(out.read_bytes(), 6)


def seal(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, AAD)


def unseal(key: bytes, blob: bytes) -> bytes:
    """Файл копии → байты SQLite."""
    return gzip.decompress(AESGCM(key).decrypt(blob[:12], blob[12:], AAD))


def check_db(gz_or_raw: bytes) -> dict:
    """Проверить байты копии (gzip или сырой SQLite): открывается ли, цела ли, что внутри."""
    raw = gz_or_raw
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "check.db"
        f.write_bytes(raw)
        con = sqlite3.connect(str(f))
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("файл базы повреждён")
            def n(table: str) -> int:
                try:
                    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    return 0
            return {"people": n("people"), "calendars": n("calendars"), "objects": n("objects")}
        finally:
            con.close()


class BackupService:
    def __init__(self, db: Database, cloud: CloudSync, tz: ZoneInfo,
                 client_factory: Callable[[str], YandexDisk] = YandexDisk):
        self.db, self.cloud, self.tz = db, cloud, tz
        self.client_factory = client_factory

    def status(self) -> dict:
        st = self.db.kv_get("backup:state")[0] or {}
        return {"configured": bool(self.cloud._token()), "last_ok": st.get("last_ok"), "last_error": st.get("last_error"),
                "size": st.get("size"), "name": st.get("name"), "count": st.get("count"), "keep": KEEP, "drill": st.get("drill"), "files": st.get("files"),
                "verified": st.get("verified")}

    def run(self) -> dict:
        token = self.cloud._token()
        if not token:
            return self.status()
        st = self.db.kv_get("backup:state")[0] or {}
        try:
            raw = snapshot_db(Path(self.db.path), self.db)
            blob = seal(self.cloud.key(), raw)
            check_db(unseal(self.cloud.key(), blob))   # копия должна расшифровываться и открываться
            name = f"{PREFIX}{datetime.now(self.tz):%Y%m%d-%H%M}{SUFFIX}"
            disk = self.client_factory(token)
            disk.mkdir(DIR)
            disk.upload(blob, f"{DIR}/{name}")
            files = sorted(f["name"] for f in disk.ls(DIR) if f["name"].startswith(PREFIX) and f["name"].endswith(SUFFIX))
            for old in files[:-KEEP]:
                disk.rm(f"{DIR}/{old}")
            st.update(last_ok=datetime.now(self.tz).isoformat(timespec="seconds"), last_error=None, size=len(blob),
                      name=name, count=min(len(files), KEEP))
            log.info("Резервная копия %s (%d КБ)", name, len(blob) // 1024)
            try:
                st["files"] = self.sync_files(disk)
            except Exception as e:  # noqa: BLE001 — база сохранена, вложения догоним в следующий раз
                st["files"] = {**(st.get("files") or {}), "error": "Вложения скопированы не полностью"}
                log.warning("Копия вложений: %s", e)
        except CloudError as e:
            st["last_error"] = str(e)
            log.warning("Резервная копия не сделана: %s", e)
        except Exception as e:  # noqa: BLE001
            st["last_error"] = "Не удалось сделать копию"
            log.warning("Резервная копия не сделана: %s", e)
        self.db.kv_set("backup:state", st)
        return self.status()

    def sync_files(self, disk) -> dict:
        """Вложения (data/files) → app:/files на Диске: новые загружаются, удалённые на сервере убираются.
        Каждый файл — gzip + AES-GCM ключом облака (расшифровка тем же restore_backup.py)."""
        local_dir = Path(self.db.path).parent / "files"
        local = {r["id"]: r for r in self.db.query("SELECT id, size FROM event_files WHERE url IS NULL")}
        disk.mkdir(FILES_DIR)
        remote = {f["name"] for f in disk.ls(FILES_DIR)}
        sent = 0
        for fid in local:
            path = local_dir / fid
            if fid in remote or not path.is_file():
                continue
            disk.upload(seal(self.cloud.key(), gzip.compress(path.read_bytes(), 6)), f"{FILES_DIR}/{fid}")
            sent += 1
        for name in remote - set(local):
            disk.rm(f"{FILES_DIR}/{name}")
        return {"count": len(local), "sent": sent, "bytes": sum(int(r["size"] or 0) for r in local.values()), "error": None}

    # --- восстановление ---------------------------------------------------------------------------

    def files(self) -> list[dict]:
        """Копии на Диске, новые сверху."""
        token = self.cloud._token()
        if not token:
            return []
        items = self.client_factory(token).ls(DIR)
        out = [{"name": f["name"], "size": f.get("size"), "modified": f.get("modified")} for f in items
               if f["name"].startswith(PREFIX) and f["name"].endswith(SUFFIX)]
        return sorted(out, key=lambda f: f["name"], reverse=True)

    def _load(self, name: str) -> bytes:
        if "/" in name or not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
            raise CloudError("Неверное имя копии")
        token = self.cloud._token()
        if not token:
            raise CloudError("Не подключён Яндекс.Диск")
        blob = self.client_factory(token).download_path(f"{DIR}/{name}")
        try:
            return unseal(self.cloud.key(), blob)
        except Exception as e:  # noqa: BLE001
            raise CloudError("Копию не удалось расшифровать — ключ облака не тот, что при создании") from e

    def verify(self, name: str | None = None) -> dict:
        """Скачать копию (по умолчанию самую свежую), расшифровать и открыть. Результат запоминается."""
        st = self.db.kv_get("backup:state")[0] or {}
        try:
            if not name:
                fl = self.files()
                if not fl:
                    raise CloudError("На Диске нет копий")
                name = fl[0]["name"]
            info = check_db(self._load(name))
            res = {"ok": True, "name": name, **info}
        except (CloudError, ValueError, sqlite3.Error, OSError) as e:
            res = {"ok": False, "name": name, "error": str(e)}
        res["at"] = datetime.now(self.tz).isoformat(timespec="seconds")
        st["verified"] = res
        self.db.kv_set("backup:state", st)
        return res

    def drill(self) -> dict:
        """Учебное восстановление (раз в месяц): скачать свежую копию, расшифровать, развернуть во временную базу,
        проверить целостность и сравнить с живой базой — копия, в которой заметно меньше событий, считается плохой."""
        res = self.verify()
        if res.get("ok"):
            live = self.db.query("SELECT COUNT(*) AS n FROM objects")[0]["n"]
            got = res.get("objects", 0)
            res["live_objects"] = live
            if live >= 20 and got < live * 0.5:
                res.update(ok=False, error=f"в копии {got} записей календаря, а в базе {live} — копия неполная")
        st = self.db.kv_get("backup:state")[0] or {}
        st["drill"] = res
        self.db.kv_set("backup:state", st)
        return res

    def restore(self, name: str) -> dict:
        """Заменить текущую базу содержимым копии. Перед этим — страховочная копия рядом с базой."""
        raw = self._load(name)
        info = check_db(raw)
        raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        safety = Path(self.db.path).with_name("before-restore.db.gz")
        safety.write_bytes(snapshot_db(Path(self.db.path)))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "restore.db"
            f.write_bytes(raw)
            src = sqlite3.connect(str(f))
            try:
                with self.db._lock:
                    src.backup(self.db._conn)
                    self.db._conn.commit()
                    self.db._migrate()
                    self.db.encrypt_secrets()
            finally:
                src.close()
        log.warning("База восстановлена из %s", name)
        return {"ok": True, "name": name, **info, "safety": safety.name}
