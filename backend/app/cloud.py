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
import re
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


def clean_token(token: str | None) -> str:
    """Токен часто вставляют вместе с хвостом адреса: «…#access_token=y0_…&token_type=bearer&expires_in=…» или «OAuth y0_…».
    Оставляем только сам токен."""
    t = (token or "").strip().strip("\"'")
    if "access_token=" in t:
        t = t.split("access_token=", 1)[1]
    t = t.split("&", 1)[0].split("#", 1)[0]
    if t[:6].lower() == "oauth ":
        t = t[6:]
    return t.strip()


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
        # Подсказка для сообщений об ошибке: по длине и началу видно, что именно ушло в Яндекс (сам токен не показываем).
        self.hint = f"{token[:4]}…{token[-2:]}, {len(token)} зн." if len(token) > 8 else f"{len(token)} зн."

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.status_code == 401:
            raise CloudError(f"Токен Яндекс.Диска не подошёл или истёк ({self.hint}; {what}). Получите новый и проверьте, что он скопирован целиком, без лишнего")
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
            "path": "app:/", "limit": 200, "fields": "_embedded.items.name,_embedded.items.md5,_embedded.items.modified"}, headers=self.h),
            "список файлов")
        items = (r.json().get("_embedded") or {}).get("items") or []
        return [i for i in items if i.get("name", "").startswith("ops-") and i["name"].endswith(".bin")]

    def download(self, name: str) -> bytes:
        return self.download_path(f"app:/{name}")

    def download_path(self, path: str) -> bytes:
        r = self._check(self.c.get(f"{API}/resources/download", params={"path": path}, headers=self.h),
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
            token = clean_token(token)
            if not token_ok(token):
                raise CloudError(BAD_TOKEN)
            self.db.kv_set("cloud:token", {"token": token})
        else:
            self.db.kv_set("cloud:token", {})
            self.db.kv_set("cloud:state", {})

    def code(self) -> str | None:
        url = self._state().get("public_url")
        if not url or not token_ok(self._token()):
            return None
        # t — токен записи: нужен приложению, чтобы вне дома класть команды в папку на Диске
        payload = {"u": url, "k": _b64(self.key()), "t": self._token()}
        # s и w — публичный адрес сервера и токен «только чтение»: по ним приложения и виджеты берут свежие данные
        # напрямую с сервера, когда он доступен из интернета, и сами выбирают «дом / интернет».
        from . import access
        pub = access.public_url(self.db)
        if pub and access.enabled(self.db, "widget"):
            payload["s"] = pub
            payload["w"] = access.token(self.db, "widget")
        return "hhc1." + _b64(json.dumps(payload).encode())

    def client_id(self) -> str:
        value, _ = self.db.kv_get("settings:yandex_client")
        return str((value or {}).get("id") or "")

    def set_client_id(self, cid: str) -> None:
        cid = (cid or "").strip().lower()
        if cid and not re.fullmatch(r"[0-9a-f]{32}", cid):
            raise CloudError("ID приложения — 32 знака из цифр и латинских букв a–f (oauth.yandex.ru → ваше приложение → ClientID)")
        self.db.kv_set("settings:yandex_client", {"id": cid})

    def status(self) -> dict:
        st = self._state()
        return {"configured": bool(self._token()), "client_id": self.client_id(), "last_ok": st.get("last_ok"), "last_error": st.get("last_error"),
                "ops_error": st.get("ops_error"), "ops_bad": st.get("ops_bad") or [], "code": self.code(),
                # для навыка Алисы: url и ключ — чтение снимка; token — только если хотите голосовое «добавь…» (запись в папку)
                "alice": {"url": st.get("public_url"), "key": _b64(self.key()),
                          "token": self._token() if token_ok(self._token()) else None} if st.get("public_url") else None}

    # --- команды с телефонов ---
    def poll_ops(self, apply: Callable[[list[dict]], list[str]]) -> bool:
        """Забирает новые файлы команд, применяет их. True, если что-то применилось (нужно обновить снимок)."""
        token = self._token()
        if not token or not self._state().get("public_url"):
            return False
        st = self._state()
        seen: dict = st.get("ops_md5") or {}
        changed = False
        bad: dict = {b["name"]: b for b in st.get("ops_bad") or []}
        try:
            disk = self.client_factory(token)
            for f in disk.list_ops():
                name = f["name"]
                if seen.get(name) == f.get("md5"):
                    continue
                once = name.startswith(("ops-alice-", "ops-once-"))   # одноразовые файлы (Алиса, кнопки в уведомлениях iPhone/Mac)
                blob = disk.download(name)                              # сбой сети здесь — попробуем весь опрос через минуту
                try:
                    if len(blob) > 400_000:
                        raise ValueError("файл слишком большой")
                    ops = json.loads(decrypt(self.key(), blob))
                    if not isinstance(ops, list):
                        raise ValueError("не список команд")
                except Exception as e:  # noqa: BLE001 — один нечитаемый файл не должен останавливать остальные устройства
                    why = "файл слишком большой" if "большой" in str(e) else \
                        "они зашифрованы другим ключом — подключите это устройство заново (Настройки → Связь вне дома)"
                    log.warning("Команды из облака: %s не читается (%s)", name, type(e).__name__)
                    seen[name] = f.get("md5")                           # к этому же файлу не возвращаемся, пока он не изменится
                    if once:
                        try:
                            disk.rm(f"app:/{name}")
                            seen.pop(name, None)
                        except CloudError:
                            pass
                    else:
                        code, _, model = name[4:-4].partition("~")   # ops-<код>~<Модель>.bin (Android 2.11+)
                        bad[name] = {"name": name, "device": code[:40], "model": model.replace("-", " ")[:40] or None,
                                     "why": why, "modified": f.get("modified"),
                                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                    continue
                bad.pop(name, None)
                if apply(ops):
                    changed = True
                seen[name] = f.get("md5")
                if once:
                    try:
                        disk.rm(f"app:/{name}")
                        seen.pop(name, None)
                    except CloudError:
                        pass
            st["ops_md5"] = seen
            st["ops_error"] = None
        except CloudError as e:
            st["ops_error"] = str(e)
        except Exception as e:  # noqa: BLE001 — сеть
            st["ops_error"] = f"Не удалось прочитать команды из облака ({type(e).__name__})"
            log.warning("Команды из облака: %s", e)
        st["ops_bad"] = list(bad.values())[-8:]
        self.db.kv_set("cloud:state", st)
        return changed

    def forget_ops(self, name: str) -> None:
        """Убрать нечитаемый файл команд с Диска и из списка замечаний (устройство после переподключения создаст новый)."""
        st = self._state()
        if name not in {b["name"] for b in st.get("ops_bad") or []}:
            raise CloudError("Такого файла в списке нет")
        try:
            self.client_factory(self._token()).rm(f"app:/{name}")
        except CloudError:
            pass       # уже удалён — тем лучше
        st["ops_bad"] = [b for b in st.get("ops_bad") or [] if b["name"] != name]
        (st.get("ops_md5") or {}).pop(name, None)
        self.db.kv_set("cloud:state", st)

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
