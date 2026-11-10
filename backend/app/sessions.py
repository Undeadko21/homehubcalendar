"""Устройства, вошедшие в календарь: у каждого свой секрет в cookie `homecal_auth` (`s.<секрет>`), в базе хранится только его хэш.

Список можно просматривать и отключать устройства по одному. Старые cookie (общий HMAC пароля) принимаются, пока их не отключат
кнопкой «Отключить все», и при первом же запросе заменяются личной сессией. Смена пароля (PIN) отключает всех."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from datetime import datetime, timedelta

from .db import Database

KEY = "auth:sessions"      # префикс auth: — хранится зашифрованным
LEGACY_KEY = "auth:legacy_off"
MAX = 100
TOUCH = timedelta(minutes=10)    # как часто обновлять «последний визит» (чтобы не писать в базу на каждый запрос)


def pin_fingerprint(pin: str) -> str:
    return hmac.new(pin.encode(), b"session-v1", hashlib.sha256).hexdigest()[:16]


def _key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:32]


def device_label(ua: str) -> str:
    """«iPhone · Safari», «Android · приложение», «Mac · Chrome» — по User-Agent, чтобы человек узнал своё устройство."""
    ua = ua or ""
    low = ua.lower()
    if "iphone" in low:
        os_ = "iPhone"
    elif "ipad" in low:
        os_ = "iPad"
    elif "android" in low:
        os_ = "Android"
    elif "macintosh" in low or "mac os" in low or "darwin" in low:
        os_ = "Mac"
    elif "windows" in low:
        os_ = "Windows"
    elif "linux" in low:
        os_ = "Linux"
    else:
        os_ = "Устройство"
    if "homehubapp" in low:
        app = "приложение"
    elif "edg/" in low:
        app = "Edge"
    elif "firefox" in low:
        app = "Firefox"
    elif "chrome" in low or "crios" in low:
        app = "Chrome"
    elif "safari" in low:
        app = "Safari"
    else:
        app = "браузер"
    return f"{os_} · {app}"


class Sessions:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._d: dict | None = None

    def _data(self) -> dict:
        if self._d is None:
            value, _ = self.db.kv_get(KEY)
            self._d = dict(value or {})
        return self._d

    def _save(self) -> None:
        self.db.kv_set(KEY, self._d or {})

    # --- старые cookie ---
    def legacy_ok(self) -> bool:
        value, _ = self.db.kv_get(LEGACY_KEY)
        return not value

    def create(self, pinfp: str, label: str, ip: str, via: str, now: datetime | None = None) -> str:
        now = now or datetime.now()
        secret = secrets.token_urlsafe(32)
        with self._lock:
            d = self._data()
            d[_key(secret)] = {"label": label[:60], "ip": ip[:64], "via": via, "pin": pinfp,
                               "created": now.isoformat(timespec="seconds"), "last": now.isoformat(timespec="seconds")}
            if len(d) > MAX:
                for k in sorted(d, key=lambda k: d[k]["last"])[: len(d) - MAX]:
                    d.pop(k, None)
            self._save()
        return secret

    def check(self, secret: str, pinfp: str, ip: str = "", now: datetime | None = None) -> str | None:
        """Ключ сессии, если секрет действителен для текущего пароля; иначе None."""
        k = _key(secret)
        rec = self._data().get(k)
        if not rec or not hmac.compare_digest(rec.get("pin", ""), pinfp):
            return None
        now = now or datetime.now()
        try:
            stale = now - datetime.fromisoformat(rec["last"]) > TOUCH
        except ValueError:
            stale = True
        if stale:
            with self._lock:
                rec["last"] = now.isoformat(timespec="seconds")
                if ip:
                    rec["ip"] = ip[:64]
                self._save()
        return k

    def listing(self, current: str | None) -> list[dict]:
        d = self._data()
        out = [{"id": k[:12], "label": v.get("label", ""), "ip": v.get("ip", ""), "via": v.get("via", ""),
                "created": v.get("created"), "last": v.get("last"), "current": k == current} for k, v in d.items()]
        return sorted(out, key=lambda r: r["last"] or "", reverse=True)

    def revoke(self, pub_id: str) -> bool:
        with self._lock:
            d = self._data()
            hit = [k for k in d if k[:12] == pub_id]
            for k in hit:
                d.pop(k, None)
            if hit:
                self._save()
            return bool(hit)

    def revoke_all(self, keep: str | None = None) -> int:
        """Отключает все сессии (кроме `keep`) и старые общие cookie."""
        with self._lock:
            d = self._data()
            gone = [k for k in d if k != keep]
            for k in gone:
                d.pop(k, None)
            self._save()
            self.db.kv_set(LEGACY_KEY, True)
            return len(gone)
