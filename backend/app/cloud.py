"""Снимок на Яндекс.Диске: когда телефон вне дома, он читает его вместо домашнего сервера.

Схема: сервер собирает снимок (snapshot.py), шифрует AES-256-GCM ключом, который знают только сервер и
приложения, кладёт в папку приложения на Диске и публикует файл по секретной ссылке. Приложение скачивает его
по ссылке без аккаунта и расшифровывает. Даже при утечке ссылки без ключа прочитать снимок нельзя.

Код подключения для приложения: «hhc1.» + base64url(JSON {"u": публичная ссылка, "k": ключ base64}).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import Database

log = logging.getLogger(__name__)

API = "https://cloud-api.yandex.net/v1/disk"
FILE = "app:/homehub-snapshot.bin"
REFRESH_EVERY = timedelta(minutes=60)  # раз в час обновляем снимок, даже если ничего не менялось


class CloudError(Exception):
    pass


BAD_TOKEN = "Это не похоже на токен Яндекс.Диска: нужна одна длинная строка из латинских букв, цифр и знаков (обычно начинается с y0_)"


def token_ok(token: str | None) -> bool:
    t = (token or "").strip()
    return len(t) >= 20 and t.isascii() and not any(c.isspace() for c in t)


def encrypt(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, b"homehub-v1")


def decrypt(key: bytes, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], b"homehub-v1")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class YandexDisk:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.c = client or httpx.Client(timeout=30)
        self.h = {"Authorization": f"OAuth {token}"}

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code == 401:
            raise CloudError("Токен Яндекс.Диска не подошёл или истёк — получите новый")
        if r.status_code == 403:
            raise CloudError("У токена нет доступа к папке приложения на Диске")
        if r.status_code == 507:
            raise CloudError("На Яндекс.Диске нет места")
        if r.status_code >= 400:
            raise CloudError(f"{what}: Яндекс.Диск ответил {r.status_code}")
        return r

    def upload(self, data: bytes, path: str = FILE) -> None:
        r = self._check(self.c.get(f"{API}/resources/upload", params={"path": path, "overwrite": "true"}, headers=self.h),
                        "запрос загрузки")
        href = r.json()["href"]
        self._check(self.c.put(href, content=data), "загрузка файла")

    def mkdir(self, path: str) -> None:
        r = self.c.put(f"{API}/resources", params={"path": path}, headers=self.h)
        if r.status_code != 409:  # 409 — папка уже есть
            self._check(r, "создание папки")

    def ls(self, path: str) -> list[dict]:
        """Файлы папки: name, size, modified."""
        r = self.c.get(f"{API}/resources", params={
            "path": path, "limit": 200, "fields": "_embedded.items.name,_embedded.items.size,_embedded.items.modified"},
            headers=self.h)
        if r.status_code == 404:
            return []
        items = (self._check(r, "список файлов").json().get("_embedded") or {}).get("items") or []
        return items

    def rm(self, path: str) -> None:
        r = self.c.delete(f"{API}/resources", params={"path": path, "permanently": "true"}, headers=self.h)
        if r.status_code != 404:
            self._check(r, "удаление файла")

    def _meta(self) -> dict:
        r = self._check(self.c.get(f"{API}/resources", params={"path": FILE, "fields": "public_key,public_url"},
                                   headers=self.h), "чтение сведений о файле")
        return r.json()

    def list_ops(self) -> list[dict]:
        """Файлы команд с телефонов (ops-*.bin) в папке приложения: имя и md5."""
        r = self._check(self.c.get(f"{API}/resources", params={
            "path": "app:/", "limit": 200, "fields": "_embedded.items.name,_embedded.items.md5"}, headers=self.h),
            "список файлов")
        items = (r.json().get("_embedded") or {}).get("items") or []
        return [i for i in items if i.get("name", "").startswith("ops-") and i["name"].endswith(".bin")]

    def download(self, name: str) -> bytes:
        r = self._check(self.c.get(f"{API}/resources/download", params={"path": f"app:/{name}"}, headers=self.h),
                        "запрос скачивания")
        return self._check(self.c.get(r.json()["href"]), "скачивание файла").content

    def public_url(self) -> str:
        """Публичная ссылка на файл; публикует, если ещё не опубликован."""
        meta = self._meta()
        if not meta.get("public_url"):
            self._check(self.c.put(f"{API}/resources/publish", params={"path": FILE}, headers=self.h), "публикация")
            meta = self._meta()
        if not meta.get("public_url"):
            raise CloudError("Яндекс.Диск не вернул публичную ссылку")
        return meta["public_url"]


class CloudSync:
    def __init__(self, db: Database, build_snapshot: Callable[[], dict],
                 client_factory: Callable[[str], YandexDisk] = YandexDisk):
        self.db = db
        self.build_snapshot = build_snapshot
        self.client_factory = client_factory

    # --- настройки ---
    def _token(self) -> str:
        return (self.db.kv_get("cloud:token")[0] or {}).get("token", "")

    def key(self) -> bytes:
        stored = self.db.kv_get("cloud:key")[0]
        if stored:
            return _unb64(stored["key"])
        key = os.urandom(32)
        self.db.kv_set("cloud:key", {"key": _b64(key)})
        return key

    def _state(self) -> dict:
        return self.db.kv_get("cloud:state")[0] or {}

    def set_token(self, token: str | None) -> None:
        if token:
            if not token_ok(token):
                raise CloudError(BAD_TOKEN)
            self.db.kv_set("cloud:token", {"token": token.strip()})
        else:
            self.db.kv_set("cloud:token", {})
            self.db.kv_set("cloud:state", {})

    def code(self) -> str | None:
        url = self._state().get("public_url")
        if not url or not token_ok(self._token()):
            return None
        # t — токен записи: нужен приложению, чтобы вне дома класть команды в папку на Диске
        payload = {"u": url, "k": _b64(self.key()), "t": self._token()}
        return "hhc1." + _b64(json.dumps(payload).encode())

    def status(self) -> dict:
        st = self._state()
        return {"configured": bool(self._token()), "last_ok": st.get("last_ok"), "last_error": st.get("last_error"),
                "ops_error": st.get("ops_error"), "code": self.code(),
                # для навыка Алисы: читает снимок, писать в папку ему не нужно (токена здесь нет)
                "alice": {"url": st.get("public_url"), "key": _b64(self.key())} if st.get("public_url") else None}

    # --- команды с телефонов ---
    def poll_ops(self, apply: Callable[[list[dict]], list[str]]) -> bool:
        """Забирает новые файлы команд, применяет их. True, если что-то применилось (нужно обновить снимок)."""
        token = self._token()
        if not token or not self._state().get("public_url"):
            return False
        st = self._state()
        seen: dict = st.get("ops_md5") or {}
        changed = False
        try:
            disk = self.client_factory(token)
            for f in disk.list_ops():
                if seen.get(f["name"]) == f.get("md5"):
                    continue
                blob = disk.download(f["name"])
                if len(blob) > 400_000:
                    raise CloudError("Файл команд слишком большой")
                ops = json.loads(decrypt(self.key(), blob))
                if isinstance(ops, list) and apply(ops):
                    changed = True
                seen[f["name"]] = f.get("md5")
            st["ops_md5"] = seen
            st["ops_error"] = None
        except CloudError as e:
            st["ops_error"] = str(e)
        except Exception as e:  # сеть, битый файл, чужой ключ
            st["ops_error"] = "Не удалось прочитать команды из облака"
            log.warning("Команды из облака: %s", e)
        self.db.kv_set("cloud:state", st)
        return changed

    # --- отправка ---
    def tick(self, force: bool = False) -> dict:
        """Обновляет снимок на Диске, если он изменился или устарел. Возвращает статус."""
        token = self._token()
        if not token:
            return self.status()
        st = self._state()
        if not token_ok(token):  # когда-то сохранили не токен (например, заголовок раздела)
            st["last_error"] = BAD_TOKEN
            self.db.kv_set("cloud:state", st)
            return self.status()
        snap = self.build_snapshot()
        digest = hashlib.sha256(json.dumps({k: v for k, v in snap.items() if k != "generated"},
                                           sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        now = datetime.now(timezone.utc)
        last = datetime.fromisoformat(st["last_ok"]) if st.get("last_ok") else None
        if not force and st.get("digest") == digest and last and now - last < REFRESH_EVERY and st.get("public_url"):
            return self.status()
        try:
            disk = self.client_factory(token)
            disk.upload(encrypt(self.key(), json.dumps(snap, ensure_ascii=False).encode()))
            url = disk.public_url()
            st.update(digest=digest, last_ok=now.isoformat(timespec="seconds"), last_error=None, public_url=url)
            log.info("Снимок обновлён на Яндекс.Диске")
        except CloudError as e:
            st["last_error"] = str(e)
            log.warning("Снимок не обновлён: %s", e)
        except Exception as e:  # сеть, таймауты
            st["last_error"] = "Нет связи с Яндекс.Диском"
            log.warning("Снимок не обновлён: %s", e)
        self.db.kv_set("cloud:state", st)
        return self.status()
