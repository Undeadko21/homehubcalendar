"""Уведомления в браузере (Web Push): шифрование по RFC 8291, подпись VAPID, подписки, отбор по людям и времени."""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app import webpush


def _browser():
    """Ключи «браузера»: как pushManager.subscribe отдаёт p256dh и auth."""
    k = ec.generate_private_key(ec.SECP256R1())
    raw = webpush._raw_public(k.public_key())
    auth = os.urandom(16)
    return k, {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": webpush.b64u(raw), "auth": webpush.b64u(auth)}}


def _decrypt(body: bytes, ua_key, auth: bytes) -> bytes:
    """Расшифровка, как в браузере (RFC 8291/8188) — независимо от encrypt()."""
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_pub = body[21:21 + idlen]
    ct = body[21 + idlen:]
    assert rs == 4096 and idlen == 65
    ua_raw = webpush._raw_public(ua_key.public_key())
    shared = ua_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))
    h = lambda salt, ikm, info, n: HKDF(hashes.SHA256(), n, salt, info).derive(ikm)  # noqa: E731
    ikm = h(auth, shared, b"WebPush: info\x00" + ua_raw + as_pub, 32)
    cek, nonce = h(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16), h(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    pt = AESGCM(cek).decrypt(nonce, ct, None)
    assert pt.endswith(b"\x02")
    return pt[:-1]


def test_encrypt_roundtrip():
    k, sub = _browser()
    msg = json.dumps({"title": "Пора выезжать", "body": "Бассейн"}, ensure_ascii=False).encode()
    body = webpush.encrypt(msg, sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert _decrypt(body, k, webpush.unb64u(sub["keys"]["auth"])) == msg


def test_encrypt_matches_http_ece_if_installed():
    import pytest
    ece = pytest.importorskip("http_ece")
    k, sub = _browser()
    body = webpush.encrypt(b"hello", sub["keys"]["p256dh"], sub["keys"]["auth"])
    assert ece.decrypt(body, private_key=k, auth_secret=webpush.unb64u(sub["keys"]["auth"]), version="aes128gcm") == b"hello"


def test_vapid_jwt_is_valid_es256(api):
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    key = webpush._vapid(api.core.db)
    assert webpush._vapid(api.core.db).private_numbers() == key.private_numbers()   # ключ один и хранится
    jwt = webpush._jwt(key, "https://fcm.googleapis.com/fcm/send/xyz", 1_700_000_000)
    head, body, sig = jwt.split(".")
    claims = json.loads(webpush.unb64u(body))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["sub"].startswith("https://")
    raw = webpush.unb64u(sig)
    key.public_key().verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                            f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    assert len(webpush.unb64u(webpush.public_key(api.core.db))) == 65
    v, _ = api.core.db.kv_get("push:vapid")
    raw_row = api.core.db.conn.execute("SELECT value FROM kv WHERE key='push:vapid'").fetchone()[0] \
        if hasattr(api.core.db, "conn") else None
    assert "PRIVATE KEY" in v and (raw_row is None or "PRIVATE KEY" not in raw_row)   # в базе — зашифрован


def test_subscribe_api_and_people_filter(api):
    _, sub = _browser()
    assert api.post("/api/push/subscribe", json={"subscription": {"endpoint": "http://x", "keys": {}}}).status_code == 400
    assert api.post("/api/push/subscribe", json={"subscription": sub, "people": ["anna"], "name": "Ноутбук"}).status_code == 200
    st = api.post("/api/push/status", json={"endpoint": sub["endpoint"]}).json()
    assert st == {"subscribed": True, "people": ["anna"], "count": 1}
    s = webpush.find(api.core.db, sub["endpoint"])
    assert webpush.wanted(s, {"id": "go:1", "people": ["anna"]})
    assert not webpush.wanted(s, {"id": "ev:1", "people": ["mark"]})
    assert webpush.wanted(s, {"id": "alert:1", "people": ["mark"]})      # срочное — всем
    assert webpush.wanted(s, {"id": "ev:2", "people": []})
    api.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    assert webpush.subs(api.core.db) == []


def test_tick_sends_due_once_and_drops_dead(api, monkeypatch):
    _, sub = _browser()
    webpush.subscribe(api.core.db, sub, [], "ПК")
    sent = []
    codes = iter([201, 410])

    class R:
        def __init__(self, c):
            self.status_code = c

    monkeypatch.setattr(webpush.httpx, "post", lambda url, **kw: sent.append(kw["headers"]) or R(next(codes)))
    now = datetime(2026, 11, 20, 17, 0, tzinfo=timezone(timedelta(hours=5)))
    items = [{"id": "go:a", "at": (now - timedelta(minutes=1)).isoformat(), "title": "Пора", "text": "", "people": []},
             {"id": "ev:b", "at": (now + timedelta(minutes=5)).isoformat(), "title": "Позже", "people": []},
             {"id": "ev:c", "at": (now - timedelta(hours=1)).isoformat(), "title": "Давно", "people": []}]
    assert webpush.tick(api.core.db, items, now) == 1
    assert sent[0]["Urgency"] == "high" and sent[0]["Authorization"].startswith("vapid t=")
    assert webpush.tick(api.core.db, items, now) == 0            # второй раз то же не шлём
    items.append({"id": "ev:d", "at": now.isoformat(), "title": "Ещё", "people": []})
    webpush.tick(api.core.db, items, now)                        # служба ответила 410 — подписка удалена
    assert webpush.subs(api.core.db) == []


def test_endpoint_allowlist(api):
    _, sub = _browser()
    for bad in ("https://192.168.1.1/x", "https://localhost/x", "http://fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x",
                "https://evil.com/fcm.googleapis.com", "https://fcm.googleapis.com.evil.com/x", "https://xpush.services.mozilla.com.evil/x"):
        r = api.post("/api/push/subscribe", json={"subscription": {**sub, "endpoint": bad}})
        assert r.status_code == 400, bad
    for good in ("https://fcm.googleapis.com/fcm/send/a", "https://updates.push.services.mozilla.com/wpush/v2/a",
                 "https://web.push.apple.com/QK", "https://wns2-par02p.notify.windows.com/w/?token=a"):
        assert webpush.allowed_endpoint(good), good


def test_bad_key_rejected_and_broken_sub_does_not_block_others(api, monkeypatch):
    _, sub = _browser()
    bad = {**sub, "keys": {"p256dh": webpush.b64u(b"\x04" + b"\x01" * 64), "auth": sub["keys"]["auth"]}}
    assert api.post("/api/push/subscribe", json={"subscription": bad}).status_code == 400          # не точка кривой
    assert api.post("/api/push/subscribe", json={"subscription": {**sub, "keys": []}}).status_code == 400
    # битая подписка в базе (прошлые версии / ручная правка) не мешает хорошей
    webpush.subscribe(api.core.db, sub, [], "хорошая")
    api.core.db.kv_set(webpush.KEY_SUBS, [{**webpush.subs(api.core.db)[0], "endpoint": "https://fcm.googleapis.com/bad",
                                          "p256dh": bad["keys"]["p256dh"]}] + webpush.subs(api.core.db))
    calls = []

    class R:
        status_code = 201
    monkeypatch.setattr(webpush.httpx, "post", lambda url, **kw: calls.append(url) or R())
    now = datetime(2026, 11, 20, 17, 0, tzinfo=timezone(timedelta(hours=5)))
    items = [{"id": "ev:x", "at": now.isoformat(), "title": "t", "people": []}]
    assert webpush.tick(api.core.db, items, now) == 1 and calls == [sub["endpoint"]]
    assert webpush.tick(api.core.db, items, now) == 0                                             # отмечено — не повторяется


def test_network_failure_retried_next_minute(api, monkeypatch):
    _, sub = _browser()
    webpush.subscribe(api.core.db, sub, [], "ПК")
    seq = iter([webpush.httpx.ConnectError("x"), None])

    class R:
        status_code = 201

    def post(url, **kw):
        e = next(seq)
        if e:
            raise e
        return R()
    monkeypatch.setattr(webpush.httpx, "post", post)
    now = datetime(2026, 11, 20, 17, 0, tzinfo=timezone(timedelta(hours=5)))
    items = [{"id": "go:y", "at": now.isoformat(), "title": "t", "people": []}]
    assert webpush.tick(api.core.db, items, now) == 0
    assert webpush.tick(api.core.db, items, now + timedelta(minutes=1)) == 1


def test_revoked_session_drops_subscription(api):
    _, sub = _browser()
    webpush.subscribe(api.core.db, sub, [], "ноутбук", session="sess-1")
    webpush.tick(api.core.db, [], datetime.now(timezone.utc), alive=lambda s: s == "sess-1")
    assert len(webpush.subs(api.core.db)) == 1
    webpush.tick(api.core.db, [], datetime.now(timezone.utc), alive=lambda s: False)              # «Выйти отовсюду»
    assert webpush.subs(api.core.db) == []
