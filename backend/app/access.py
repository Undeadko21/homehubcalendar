"""Доступ из интернета: токены (виджеты — только чтение, VPS — отчёты и копия настроек), вход по одноразовой ссылке,
отчёты VPS-агента (`deploy/vps/`), напоминание о сторожевом уведомлении (ntfy).

Токены лежат в `kv` под ключами `auth:*` — они шифруются ключом data/secret.key, как пароль Яндекса."""
from __future__ import annotations

import base64
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta

from .db import Database

KEYS = {"widget": "auth:widget", "vps": "auth:vps"}
MAX_BACKUP = 512 * 1024
QR_TTL = 600
_QR: dict[str, float] = {}


def _stored(db: Database, which: str) -> str:
    value, _ = db.kv_get(KEYS[which])
    return str((value or {}).get("token") or "")


def enabled(db: Database, which: str) -> bool:
    return bool(_stored(db, which))


def token(db: Database, which: str) -> str:
    """Токен нужного вида; при первом обращении создаётся."""
    t = _stored(db, which)
    if not t:
        t = secrets.token_urlsafe(24)
        db.kv_set(KEYS[which], {"token": t})
    return t


def rotate(db: Database, which: str) -> str:
    t = secrets.token_urlsafe(24)
    db.kv_set(KEYS[which], {"token": t})
    return t


def disable(db: Database, which: str) -> None:
    db.kv_set(KEYS[which], {})


def check(db: Database, which: str, given: str) -> bool:
    stored = _stored(db, which)
    return bool(stored) and bool(given) and hmac.compare_digest(stored.encode(), given.encode())


def bearer(header: str) -> str:
    return header[7:].strip() if header[:7].lower() == "bearer " else ""


# ---------- публичный адрес (попадает в код подключения: приложения сами выбирают «дом / интернет») ----------

def public_url(db: Database) -> str:
    value, _ = db.kv_get("settings:public_url")
    return str(value or "")


def set_public_url(db: Database, url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and not re.fullmatch(r"https://[A-Za-z0-9.-]+(:\d{1,5})?", url):
        raise ValueError("Адрес должен быть вида https://имя.ru")
    db.kv_set("settings:public_url", url)
    return url


# ---------- одноразовая ссылка входа (QR) ----------

def new_login_link() -> str:
    now = time.time()
    for k in [k for k, t in _QR.items() if t < now]:
        _QR.pop(k, None)
    if len(_QR) > 50:
        _QR.clear()
    t = secrets.token_urlsafe(24)
    _QR[t] = now + QR_TTL
    return t


def use_login_link(t: str) -> bool:
    exp = _QR.pop(t, 0)
    return exp > time.time()


# ---------- ntfy: уведомление «дом недоступен» с VPS ----------

def ntfy_topic(db: Database) -> str:
    value, _ = db.kv_get("settings:ntfy")
    return str((value or {}).get("topic") or "")


def enable_ntfy(db: Database) -> str:
    t = ntfy_topic(db)
    if not t:
        t = "homehub-" + secrets.token_hex(8)
        db.kv_set("settings:ntfy", {"topic": t})
    return t


def disable_ntfy(db: Database) -> None:
    db.kv_set("settings:ntfy", {})


# ---------- отчёты VPS ----------

def save_report(db: Database, report: dict, backup: bytes | None) -> None:
    clean = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "disk_pct": int(report.get("disk_pct") or 0),
        "caddy": bool(report.get("caddy", True)),
        "certs": {str(k)[:80]: int(v) for k, v in list((report.get("certs") or {}).items())[:8] if isinstance(v, (int, float))},
        "load": str(report.get("load") or "")[:40],
        "uptime_days": int(report.get("uptime_days") or 0),
        "agent": str(report.get("agent") or "")[:20],
    }
    db.kv_set("vps:report", clean)
    if backup:
        if len(backup) > MAX_BACKUP:
            raise ValueError("Копия настроек слишком большая")
        db.kv_set("vps:backup", {"at": clean["at"], "size": len(backup), "data": base64.b64encode(backup).decode()})


def last_report(db: Database) -> dict | None:
    value, _ = db.kv_get("vps:report")
    return value or None


def backup_info(db: Database) -> dict | None:
    value, _ = db.kv_get("vps:backup")
    return {"at": value["at"], "size": value["size"]} if value else None


def backup_bytes(db: Database) -> bytes | None:
    value, _ = db.kv_get("vps:backup")
    return base64.b64decode(value["data"]) if value else None


def problems(db: Database, now: datetime | None = None) -> list[str]:
    """Что показать красной точкой в «Состоянии»: отчёты VPS перестали приходить, мало места, сертификат на исходе."""
    if not enabled(db, "vps"):
        return []
    now = now or datetime.now()
    r = last_report(db)
    if not r:
        return ["VPS подключён, но отчётов ещё не было (установите агента на VPS)"]
    out: list[str] = []
    try:
        age = now - datetime.fromisoformat(r["at"])
        if age > timedelta(hours=3):
            out.append(f"VPS не присылал отчёт {int(age.total_seconds() // 3600)} ч (туннель или VPS недоступны)")
    except ValueError:
        pass
    if r.get("disk_pct", 0) >= 85:
        out.append(f"На VPS занято {r['disk_pct']}% диска")
    for name, days in (r.get("certs") or {}).items():
        if days < 14:
            out.append(f"Сертификат {name} истекает через {days} дн.")
    if r.get("caddy") is False:
        out.append("На VPS не запущен Caddy")
    return out
