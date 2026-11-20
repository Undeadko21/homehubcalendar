"""Уведомления в браузере на компьютере (Web Push, v0.21).

Те же напоминания, что получают телефоны (snapshot → reminders: «Пора выезжать», событие, срочное, сводка, «кто что
изменил»), раз в минуту уходят подписанным браузерам. Без сторонних библиотек: подпись VAPID (ES256, RFC 8292) и
шифрование aes128gcm (RFC 8291) — на `cryptography`.

Хранение (kv, секретные — шифруются и вырезаются из копий базы):
- `push:vapid`  — закрытый ключ сервера (PEM); открытый отдаётся браузеру при подписке;
- `push:subs`   — подписки: [{endpoint, p256dh, auth, people: [id], name, at}];
- `webpush:sent` — что уже отправлено: {id напоминания: время} (двое суток).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import struct
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .db import Database

log = logging.getLogger(__name__)
KEY_VAPID, KEY_SUBS, KEY_SENT = "push:vapid", "push:subs", "webpush:sent"
SUBJECT = "https://github.com/Undeadko21/homehubcalendar"
WINDOW = timedelta(minutes=10)   # напоминание, чьё время прошло не раньше этого, ещё отправляем (сервер мог быть занят)
_lock = threading.Lock()
# Службы уведомлений браузеров: сервер шлёт POST только туда (адрес приходит от браузера — не дать направить его во
# внутреннюю сеть). Chrome/Edge(Chromium) — FCM, Firefox — Mozilla, Safari — Apple, старый Edge — Windows.
PUSH_HOSTS = ("fcm.googleapis.com", ".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")


def allowed_endpoint(endpoint: str) -> bool:
    u = urlsplit(endpoint or "")
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.port and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS)


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _raw_public(pub: ec.EllipticCurvePublicKey) -> bytes:
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------- ключ сервера (VAPID) ----------

def _vapid(db: Database) -> ec.EllipticCurvePrivateKey:
    with _lock:
        pem, _ = db.kv_get(KEY_VAPID)
        if not pem:
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            db.kv_set(KEY_VAPID, pem)
        return serialization.load_pem_private_key(pem.encode(), password=None)


def public_key(db: Database) -> str:
    """Открытый ключ сервера для pushManager.subscribe (applicationServerKey)."""
    return b64u(_raw_public(_vapid(db).public_key()))


def _jwt(key: ec.EllipticCurvePrivateKey, endpoint: str, now: float) -> str:
    u = urlsplit(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(now) + 12 * 3600, "sub": SUBJECT},
                           separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{body}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


# ---------- шифрование (RFC 8291, aes128gcm) ----------

def _hkdf(salt: bytes, ikm: bytes, info: bytes, n: int) -> bytes:
    return HKDF(hashes.SHA256(), n, salt, info).derive(ikm)


def encrypt(payload: bytes, p256dh: str, auth: str, salt: bytes | None = None,
            server_key: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    ua_pub_raw, auth_secret = unb64u(p256dh), unb64u(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = _raw_public(as_key.public_key())
    shared = as_key.exchange(ec.ECDH(), ua_pub)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)   # одна запись, разделитель последней — 0x02
    return salt + struct.pack("!IB", 4096, len(as_pub_raw)) + as_pub_raw + body


# ---------- подписки ----------

def subs(db: Database) -> list[dict]:
    return list(db.kv_get(KEY_SUBS)[0] or [])


def subscribe(db: Database, sub: dict, people: list[str], name: str, session: str | None = None) -> None:
    """session — ключ сессии входа браузера: «Отключить устройство» / «Выйти отовсюду» снимают и его подписку."""
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    endpoint, p256dh, auth = sub.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", "")
    if not allowed_endpoint(endpoint):
        raise ValueError("подписка не от службы уведомлений браузера")
    try:   # ключ браузера — настоящая точка кривой P-256 (иначе шифрование упадёт при отправке)
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(p256dh))
        ok = len(unb64u(auth)) == 16
    except (ValueError, TypeError):
        ok = False
    if not ok:
        raise ValueError("неверная подписка браузера")
    with _lock:
        rest = [s for s in subs(db) if s["endpoint"] != endpoint]
        rest.append({"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "people": [str(p)[:40] for p in (people or [])][:20],
                     "session": session,
                     "name": (name or "Компьютер")[:40], "at": datetime.now().isoformat(timespec="seconds")})
        db.kv_set(KEY_SUBS, rest[-20:])


def unsubscribe(db: Database, endpoint: str) -> None:
    with _lock:
        db.kv_set(KEY_SUBS, [s for s in subs(db) if s["endpoint"] != endpoint])


def find(db: Database, endpoint: str) -> dict | None:
    return next((s for s in subs(db) if s["endpoint"] == endpoint), None)


def send(db: Database, sub: dict, title: str, text: str, tag: str, urgent: bool = False) -> int:
    """Отправить одно уведомление. Код ответа службы push; 404/410 — подписка умерла и удаляется."""
    if not allowed_endpoint(sub.get("endpoint", "")):   # подписки из прошлых версий / ручной правки базы
        return 0
    payload = json.dumps({"title": title, "body": text[:1500], "tag": tag}, ensure_ascii=False).encode()
    key = _vapid(db)
    now = time.time()
    try:
        r = httpx.post(sub["endpoint"], content=encrypt(payload, sub["p256dh"], sub["auth"]), timeout=15, follow_redirects=False, headers={
            "Content-Encoding": "aes128gcm", "TTL": "3600", "Urgency": "high" if urgent else "normal",
            "Authorization": f"vapid t={_jwt(key, sub['endpoint'], now)}, k={b64u(_raw_public(key.public_key()))}"})
    except httpx.HTTPError as e:
        log.warning("web push: %s", type(e).__name__)
        return 0
    if r.status_code in (404, 410):
        unsubscribe(db, sub["endpoint"])
    elif r.status_code >= 400:
        log.warning("web push: ответ %s", r.status_code)
    return r.status_code


def wanted(sub: dict, item: dict) -> bool:
    """Как на Android: срочное и сводка — всем; остальное — если у подписки не выбраны люди или пересечение есть."""
    if str(item.get("id", "")).split(":")[0] in ("alert", "digest"):
        return True
    mine, who = set(sub.get("people") or []), set(item.get("people") or [])
    return not mine or not who or bool(mine & who)


def due(items: list[dict], sent: dict, now: datetime) -> list[dict]:
    out = []
    for r in items:
        try:
            at = datetime.fromisoformat(r["at"])
        except (KeyError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=now.tzinfo)
        if now - WINDOW <= at <= now and r.get("id") and r["id"] not in sent:
            out.append(r)
    return out


def prune(db: Database, alive) -> None:
    """Подписки браузеров, чья сессия входа отключена («Отключить устройство», «Выйти отовсюду»), — удалить."""
    with _lock:
        cur = subs(db)
        keep = [s for s in cur if alive(s.get("session"))]
        if len(keep) != len(cur):
            db.kv_set(KEY_SUBS, keep)


def tick(db: Database, reminders: list[dict], now: datetime, alive=lambda s: True) -> int:
    """Раз в минуту: что подошло по времени — подписанным браузерам. Возвращает число отправленных.
    Отметка «отправлено» — когда служба ответила (2xx/4xx); сеть или 5xx — повтор в следующую минуту (в пределах окна)."""
    prune(db, alive)
    all_subs = subs(db)
    if not all_subs:
        return 0
    sent = dict(db.kv_get(KEY_SENT)[0] or {})
    n = 0
    for r in due(reminders, sent, now):
        kind = str(r["id"]).split(":")[0]
        answered = False
        for s in all_subs:
            if not wanted(s, r):
                continue
            try:
                code = send(db, s, r.get("title") or "Календарь", r.get("text") or "", r["id"], urgent=kind in ("go", "alert", "duty"))
            except Exception:  # noqa: BLE001 — одна битая подписка не мешает остальным
                log.exception("web push: отправка")
                code = 400
            answered = answered or 200 <= code < 500
            n += 200 <= code < 300
        if answered or not any(wanted(s, r) for s in all_subs):
            sent[r["id"]] = now.isoformat(timespec="seconds")
    old = (now - timedelta(days=2)).isoformat()
    db.kv_set(KEY_SENT, {k: v for k, v in sent.items() if v >= old})
    return n
