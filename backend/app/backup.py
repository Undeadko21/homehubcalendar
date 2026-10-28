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
PREFIX, SUFFIX = "homehub-", ".db.gz.enc"
KEEP = 14
AAD = b"homehub-backup-v1"


def snapshot_db(path: Path) -> bytes:
    """Согласованная копия SQLite (во время работы сервера) — через backup API, затем gzip."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "copy.db"
        src = sqlite3.connect(str(path))
        dst = sqlite3.connect(str(out))
        try:
            src.backup(dst)
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


class BackupService:
    def __init__(self, db: Database, cloud: CloudSync, tz: ZoneInfo,
                 client_factory: Callable[[str], YandexDisk] = YandexDisk):
        self.db, self.cloud, self.tz = db, cloud, tz
        self.client_factory = client_factory

    def status(self) -> dict:
        st = self.db.kv_get("backup:state")[0] or {}
        return {"configured": bool(self.cloud._token()), "last_ok": st.get("last_ok"), "last_error": st.get("last_error"),
                "size": st.get("size"), "name": st.get("name"), "count": st.get("count"), "keep": KEEP}

    def run(self) -> dict:
        token = self.cloud._token()
        if not token:
            return self.status()
        st = self.db.kv_get("backup:state")[0] or {}
        try:
            blob = seal(self.cloud.key(), snapshot_db(Path(self.db.path)))
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
        except CloudError as e:
            st["last_error"] = str(e)
            log.warning("Резервная копия не сделана: %s", e)
        except Exception as e:  # noqa: BLE001
            st["last_error"] = "Не удалось сделать копию"
            log.warning("Резервная копия не сделана: %s", e)
        self.db.kv_set("backup:state", st)
        return self.status()
