"""Доступ из интернета: токены (виджеты — только чтение, VPS — отчёты и копия настроек), вход по одноразовой ссылке,
отчёты VPS-агента (`deploy/vps/`), напоминание о сторожевом уведомлении (ntfy).

Токены лежат в `kv` под ключами `auth:*` — они шифруются ключом data/secret.key, как пароль Яндекса."""
from __future__ import annotations

import base64
import hmac
import logging
import re
import secrets
import threading
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
        db.kv_set("settings:ntfy", {"topic": t, "login": True})
    return t


def login_alerts(db: Database) -> bool:
    """Сообщать ли о новых входах и подборе пароля (по умолчанию да, когда ntfy включён)."""
    value, _ = db.kv_get("settings:ntfy")
    return bool((value or {}).get("topic")) and (value or {}).get("login", True) is not False


def set_login_alerts(db: Database, on: bool) -> None:
    value, _ = db.kv_get("settings:ntfy")
    if (value or {}).get("topic"):
        db.kv_set("settings:ntfy", {**value, "login": bool(on)})


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
    dc = report.get("db_copy")
    if isinstance(dc, dict) and dc.get("at"):
        # Время копии агент берёт по часам VPS (там может быть другой пояс) — надёжнее время, когда сервер её отдал.
        served = (db.kv_get("vps:dbcopy_served")[0] or {}).get("at")
        clean["db_copy"] = {"at": served or str(dc["at"])[:25], "count": int(dc.get("count") or 0), "size": int(dc.get("size") or 0)}
    fc = report.get("files_copy")
    if isinstance(fc, dict):
        clean["files_copy"] = {"count": int(fc.get("count") or 0)}
    db.kv_set("vps:report", clean)
    if backup:
        if len(backup) > MAX_BACKUP:
            raise ValueError("Копия настроек слишком большая")
        db.kv_set("vps:backup", {"at": clean["at"], "size": len(backup), "data": base64.b64encode(backup).decode()})


def mark_dbcopy_served(db: Database) -> None:
    """Агент забрал копию базы (GET /api/vps/db-backup) — запоминаем время по часам сервера."""
    db.kv_set("vps:dbcopy_served", {"at": datetime.now().isoformat(timespec="seconds")})


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
        age = now - (_naive(r["at"]) or now)
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
    if str(r.get("agent") or "0") >= "2":
        dc = r.get("db_copy")
        try:
            dage = now - (_naive(dc["at"]) or now) if dc else None
        except (ValueError, KeyError):
            dage = None
        if not dc:
            out.append("На VPS ещё нет копии базы (агент заберёт её в течение суток)")
        elif dage is not None and dage > timedelta(days=3):
            out.append(f"Копия базы на VPS старше {dage.days} дн.")
    return out


# ---------- журнал безопасности и уведомления о входах ----------
log = logging.getLogger("homecal")
LOG_KEY = "auth:log"          # зашифрован: внутри адреса
IPS_KEY = "auth:ips"
_lock = threading.Lock()


def _post_ntfy(topic: str, title: str, text: str, priority: str = "default") -> None:
    import httpx
    try:
        httpx.post(f"https://ntfy.sh/{topic}", content=text.encode(), headers={"Title": title.encode("utf-8"), "Priority": priority}, timeout=15)
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy: %s", type(e).__name__)


def event(db: Database, kind: str, text: str, ip: str = "", alert: bool = False, title: str = "HomeHub: безопасность",
          priority: str = "default", now: datetime | None = None) -> None:
    """Запись в журнал безопасности; при alert — ещё и уведомление на телефон (в фоне, вход не задерживаем)."""
    now = now or datetime.now()
    with _lock:
        value, _ = db.kv_get(LOG_KEY)
        items = list(value or [])
        items.append({"at": now.isoformat(timespec="seconds"), "kind": kind, "text": text[:200], "ip": ip[:64]})
        db.kv_set(LOG_KEY, items[-60:])
    if alert and login_alerts(db):
        threading.Thread(target=_post_ntfy, args=(ntfy_topic(db), title, text, priority), daemon=True).start()


def notify(db: Database, title: str, text: str, priority: str = "default") -> bool:
    """Уведомление на телефон о работе сервера (сбои, обновления, копии) — при включённом ntfy, независимо от «Сообщать о входах»."""
    topic = ntfy_topic(db)
    if not topic:
        return False
    threading.Thread(target=_post_ntfy, args=(topic, title, text, priority), daemon=True).start()
    return True


def security_log(db: Database, limit: int = 15) -> list[dict]:
    value, _ = db.kv_get(LOG_KEY)
    return list(reversed(list(value or [])))[:limit]


def fails_last_day(db: Database, now: datetime | None = None) -> int:
    now = now or datetime.now()
    value, _ = db.kv_get(LOG_KEY)
    n = 0
    for e in value or []:
        if e.get("kind") == "fail":
            try:
                if now - _naive(e["at"]) < timedelta(days=1):
                    n += 1
            except (ValueError, TypeError):
                pass
    return n


def remember_ip(db: Database, ip: str) -> bool:
    """Запоминает адрес входа; True, если с этого адреса ещё не входили."""
    if not ip or ip == "?":
        return False
    with _lock:
        value, _ = db.kv_get(IPS_KEY)
        ips = list(value or [])
        if ip in ips:
            return False
        ips.append(ip)
        db.kv_set(IPS_KEY, ips[-200:])
    return True


# ---------- чтение виджетов по токену: когда последний раз ----------
_seen_at = 0.0


def touch_widget(db: Database) -> None:
    global _seen_at
    now = time.time()
    if now - _seen_at < 120:
        return
    _seen_at = now
    db.kv_set("settings:widget_seen", {"at": datetime.now().isoformat(timespec="seconds")})


def widget_seen(db: Database) -> str | None:
    value, _ = db.kv_get("settings:widget_seen")
    return (value or {}).get("at")


# ---------- проверка публичного адреса снаружи ----------
WATCH = {"fails": 0, "down": False, "last": None, "alerted": 0.0}


def probe_public(db: Database, timeout: float = 8.0) -> dict:
    """Обращается к публичному адресу так же, как телефон вне дома: DNS → Caddy → туннель → сервер."""
    import httpx
    url = public_url(db)
    if not url:
        return {"ok": False, "error": "адрес не задан", "at": datetime.now().isoformat(timespec="seconds")}
    t0 = time.time()
    try:
        r = httpx.get(url + "/api/health", timeout=timeout, follow_redirects=False)
        ok = r.status_code == 200 and bool(r.json().get("ok"))
        res = {"ok": ok, "status": r.status_code, "ms": int((time.time() - t0) * 1000)}
        if not ok:
            res["error"] = f"ответ {r.status_code}"
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "error": type(e).__name__}
    res["at"] = datetime.now().isoformat(timespec="seconds")
    return res


def watch(db: Database) -> None:
    """Раз в 5 минут: отвечает ли публичный адрес. Три неудачи подряд — уведомление, потом напоминание раз в 6 часов и сообщение о восстановлении.
    Дополняет агента на VPS: если упадёт сам VPS, его агент ничего не скажет, а домашний сервер — скажет."""
    if not public_url(db):
        return
    res = probe_public(db)
    WATCH["last"] = res
    if res["ok"]:
        if WATCH["down"]:
            WATCH.update(down=False, fails=0, alerted=0.0)
            event(db, "net", "Публичный адрес снова отвечает", alert=True, title="HomeHub: связь восстановлена")
        WATCH["fails"] = 0
        return
    WATCH["fails"] += 1
    if WATCH["fails"] >= 3 and (not WATCH["down"] or time.time() - WATCH["alerted"] > 6 * 3600):
        first = not WATCH["down"]
        WATCH["down"] = True
        WATCH["alerted"] = time.time()
        event(db, "net", f"Публичный адрес не отвечает снаружи ({res.get('error')}): проверьте VPS, туннель и домен" + ("" if first else " — всё ещё"),
              alert=True, title="HomeHub: нет связи снаружи", priority="high")


# ---------- сводка состояния доступа ----------

def _naive(iso: str | None) -> datetime | None:
    """Время из базы бывает с поясом (облако пишет +05:00) и без; приводим к местному времени без пояса, чтобы их можно было вычитать."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def _ago(iso: str | None, now: datetime) -> str:
    d = _naive(iso)
    if not d:
        return ""
    m = int((now - d).total_seconds() // 60)
    if m < 1:
        return "только что"
    if m < 90:
        return f"{m} мин назад"
    if m < 48 * 60:
        return f"{m // 60} ч назад"
    return f"{m // 1440} дн. назад"


def checks(db: Database, cloud_status: dict, sessions_count: int, now: datetime | None = None) -> list[dict]:
    """Сводка не должна ронять страницу настроек: при любой неожиданности отдаём одну строку «не удалось собрать»."""
    try:
        return _checks(db, cloud_status, sessions_count, now)
    except Exception as e:  # noqa: BLE001
        log.exception("access.checks")
        return [{"id": "error", "level": "warn", "title": "Не удалось собрать сводку", "detail": type(e).__name__}]


def _checks(db: Database, cloud_status: dict, sessions_count: int, now: datetime | None = None) -> list[dict]:
    """Единый список «всё ли в порядке с доступом вне дома»: level = ok | warn | bad | info."""
    now = now or datetime.now()
    out: list[dict] = []

    def add(id_: str, level: str, title: str, detail: str = "") -> None:
        out.append({"id": id_, "level": level, "title": title, "detail": detail})

    url = public_url(db)
    if url:
        add("public", "ok", "Публичный адрес задан", url)
    else:
        add("public", "warn", "Публичный адрес не задан", "приложения вне дома смогут читать только облако Яндекс.Диска")

    last = WATCH.get("last")
    if not url:
        pass
    elif not last:
        add("probe", "info", "Проверка снаружи ещё не выполнялась", "делается каждые 5 минут или кнопкой ниже")
    elif last["ok"]:
        add("probe", "ok", "Снаружи сервер отвечает", f"{last.get('ms', '?')} мс · {_ago(last['at'], now)}")
    else:
        add("probe", "bad", "Снаружи сервер не отвечает", f"{last.get('error', '')} · {_ago(last['at'], now)}: проверьте VPS, туннель и домен")

    if not enabled(db, "vps"):
        add("vps", "info", "Агент на VPS не подключён", "включите «Следить за VPS» ниже — получите отчёты о диске и сертификате")
    else:
        r = last_report(db)
        if not r:
            add("vps", "warn", "От агента на VPS не было отчётов", "выполните команду установки на VPS")
        else:
            try:
                old = now - _naive(r["at"]) > timedelta(hours=3)
            except (ValueError, TypeError):
                old = False
            certs = r.get("certs") or {}
            cert = f", сертификат {min(certs.values())} дн." if certs else ""
            detail = f"отчёт {_ago(r['at'], now)} · диск {r.get('disk_pct', 0)}%{cert}"
            bad = old or r.get("caddy") is False or any(d < 5 for d in certs.values())
            warn = r.get("disk_pct", 0) >= 85 or any(d < 14 for d in certs.values())
            add("vps", "bad" if bad else "warn" if warn else "ok", "Агент на VPS", detail)
        b = backup_info(db)
        if b:
            try:
                stale = now - _naive(b["at"]) > timedelta(hours=48)
            except (ValueError, TypeError):
                stale = False
            add("vps-backup", "warn" if stale else "ok", "Копия настроек VPS", _ago(b["at"], now))

    if enabled(db, "widget"):
        seen = widget_seen(db)
        add("widget", "ok" if seen else "info", "Виджеты читают сервер вне дома",
            f"последнее чтение {_ago(seen, now)}" if seen else "по токену ещё ни разу не читали — переподключите приложения новым кодом")
    else:
        add("widget", "info", "Виджеты вне дома читают облако", "токен «только чтение» выключен: данные обновляются раз в час")

    if not cloud_status.get("configured"):
        add("cloud", "warn", "Облако Яндекс.Диска не подключено", "без него нет запасного пути и копий")
    elif cloud_status.get("last_error"):
        add("cloud", "bad", "Облако Яндекс.Диска: ошибка", str(cloud_status["last_error"])[:120])
    else:
        add("cloud", "ok", "Облако Яндекс.Диска", f"снимок записан {_ago(cloud_status.get('last_ok'), now)}")

    if ntfy_topic(db):
        add("ntfy", "ok", "Уведомления на телефон включены", "в том числе о новых входах" if login_alerts(db) else "о входах — выключены")
    else:
        add("ntfy", "info", "Уведомления на телефон выключены", "включите ntfy ниже, чтобы узнавать о сбоях и новых входах")

    fails = fails_last_day(db, now)
    add("devices", "warn" if fails >= 5 else "ok", f"Устройств с входом: {sessions_count}",
        f"неверных паролей за сутки: {fails}" if fails else "неверных паролей за сутки не было")
    return out


# ---------- переход на свой домен ----------
_DOMAIN_RE = re.compile(r"(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}")


def _ips(host: str) -> set[str]:
    import socket
    try:
        return {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return set()


def check_domain(db: Database, domain: str) -> dict:
    """Готов ли домен стать публичным адресом: указывает туда же, куда текущий адрес, и отдаёт календарь по https с верным сертификатом."""
    import httpx
    d = (domain or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if not _DOMAIN_RE.fullmatch(d):
        return {"domain": d, "ok": False, "steps": [{"id": "name", "ok": False, "text": "Это не похоже на имя домена: нужно вроде calendar.ru"}]}
    steps = []
    ips = _ips(d)
    cur = public_url(db)
    cur_host = cur.removeprefix("https://").split("/")[0].split(":")[0] if cur else ""
    want = _ips(cur_host) if cur_host else set()
    if not ips:
        steps.append({"id": "dns", "ok": False, "text": "Домен пока никуда не указывает (DNS). Добавьте у регистратора A-запись на адрес VPS и подождите до нескольких часов"})
    elif want and not (ips & want):
        steps.append({"id": "dns", "ok": False, "text": f"Домен указывает на {', '.join(sorted(ips))}, а сервер сейчас на {', '.join(sorted(want))}. Исправьте A-запись у регистратора"})
    else:
        steps.append({"id": "dns", "ok": True, "text": f"Домен указывает на {', '.join(sorted(ips))}"})
    https_ok = False
    if ips:
        try:
            r = httpx.get(f"https://{d}/api/health", timeout=8)
            https_ok = r.status_code == 200 and bool(r.json().get("ok"))
            steps.append({"id": "https", "ok": https_ok,
                          "text": "Календарь открывается по https, сертификат в порядке" if https_ok else f"Сервер ответил {r.status_code}: проверьте настройку Caddy на VPS"})
        except httpx.ConnectError as e:
            cert = "certificate" in str(e).lower() or "ssl" in str(e).lower()
            steps.append({"id": "https", "ok": False, "text": "Сертификат ещё не выписан или не подходит: добавьте домен в Caddyfile на VPS и перезагрузите Caddy" if cert
                          else "Не удалось подключиться по https: на VPS не открыт порт 443 или Caddy не запущен"})
        except Exception as e:  # noqa: BLE001
            steps.append({"id": "https", "ok": False, "text": f"Не удалось проверить https ({type(e).__name__})"})
    ok = all(s["ok"] for s in steps) and https_ok
    return {"domain": d, "ok": ok, "url": f"https://{d}", "current": cur, "steps": steps}
