"""Общие объекты приложения: настройки, база, сервисы (события, синхронизация, облако, копии, запись) и помощники.

Маршруты лежат в app/api/*.py и обращаются сюда как `core.db`, `core.events` и т. д. (тесты подменяют `core.make_target`)."""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import HTTPException

from .config import load_settings
from .db import Database
from .events import EventService
from . import quick
from . import snapshot, writer, writeq
from .backup import BackupService
from .perf import PerfLog
from .cloud import CloudSync
from .holidays import HolidayService
from .sync import SyncEngine
log = logging.getLogger("homecal")

settings = load_settings()
tz = ZoneInfo(settings.timezone)
db = Database(settings.db_path)
events = EventService(db, tz, fuzzy_dedup=bool(settings.dedup.get("fuzzy", True)),
                      respect_event_class=bool(settings.privacy.get("respect_event_class", False)))
holidays = HolidayService(db, settings.holidays)
engine = SyncEngine(db, settings.sources, on_change=events.invalidate)
engine.seed_people(settings.people)
scheduler = BackgroundScheduler(timezone=tz)
cloud = CloudSync(db, lambda: snapshot.build(events, db, tz))
backup = BackupService(db, cloud, tz)
STARTED = datetime.now(tz)

# Приложение для Android: собранный APK и его версия (android/release в репозитории).
APP_DIR = Path(os.environ.get("HOMECAL_APP_DIR", Path(__file__).resolve().parents[2] / "android" / "release"))

MAC_DIR = Path(os.environ.get("HOMECAL_MAC_DIR", Path(__file__).resolve().parents[2] / "macos" / "release"))

IOS_DIR = Path(os.environ.get("HOMECAL_IOS_DIR", Path(__file__).resolve().parents[2] / "ios" / "release"))

STATIC_DIR = Path(os.environ.get("HOMECAL_STATIC", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


perf = PerfLog()


# ---------- API ----------
def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _source_cfg(cal_key: str) -> dict | None:
    sid = cal_key.split("/", 1)[0]
    for s in settings.sources:
        if s.get("id") == sid:
            return s
    return None


def _writable(cal_key: str) -> bool:
    s = _source_cfg(cal_key)
    return bool(s and s.get("type") == "caldav" and s.get("write", True) is not False)


def make_target(cal_key: str):
    """Цель записи для календаря; в тестах подменяется."""
    s = _source_cfg(cal_key)
    if not s or not _writable(cal_key):
        raise HTTPException(400, "В этот календарь запись невозможна (он только для чтения)")
    eff = engine.effective_config(s)
    if not (eff.get("username") and eff.get("password")):
        raise HTTPException(400, "Не указаны логин и пароль — Настройки → Учётные записи")
    return writer.CalDavTarget(eff["url"], eff["username"], eff["password"])


def _remote_id(cal_key: str) -> str:
    return cal_key.split("/", 1)[1]


def _after_write() -> None:
    _ws_changed()


def _ws_changed() -> None:
    events.invalidate()
    try:
        cloud.tick(force=True)
    except Exception:  # noqa: BLE001
        log.exception("Облако после записи")


ws = writeq.WriteService(db, lambda k: make_target(k), _ws_changed)
def _warm() -> None:
    """Прогрев: разобрать события заранее, чтобы первое открытие календаря не ждало."""
    try:
        s = datetime.combine(date.today(), time(0), tz)
        events.events(s - timedelta(days=7), s + timedelta(days=14))
    except Exception:  # noqa: BLE001
        log.exception("Прогрев")


def _synced() -> None:
    ws.reapply()
    events.invalidate()
    threading.Thread(target=_warm, daemon=True).start()


engine.on_change = _synced


def _run_write(fn):
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("Запись в Яндекс")
        raise HTTPException(400, writer.friendly(e))


def _check_people(people):
    known = {p["id"] for p in db.list_people()}
    bad = [p for p in people or [] if p not in known]
    if bad:
        raise HTTPException(400, f"Неизвестные люди: {', '.join(bad)}")


def _create_event(calendar: str, title: str, start: datetime, end: datetime | None, all_day: bool, location: str,
                  description: str, repeat: dict | None, people: list[str] | None) -> tuple[str, bool]:
    make_target(calendar)  # заранее проверяем, что в календарь можно писать
    _check_people(people)

    def go():
        uid, ics = writer.build_ics(title, start, end, all_day, tz, location, description, repeat)
        sent = ws.create(calendar, ics)
        return uid, sent
    uid, sent = _run_write(go)
    if people is not None:
        db.set_event_people(uid, people)
    _after_write()
    return uid, sent


def _today_start() -> datetime:
    return datetime.combine(datetime.now(tz).date(), time(0), tz)


# ---------- ошибки из браузеров и приложения (для диагностики) ----------
CLIENT_LOG: list[dict] = []


def _pick_calendar(people: list[str] | None) -> str:
    """Куда класть событие, пришедшее без календаря (голос, телефон вне дома): календарь одного из участников, иначе первый пишущий."""
    cals = [c for c in db.list_calendars() if not c["hidden"] and _writable(c["key"])]
    if not cals:
        raise HTTPException(400, "Нет календаря, в который можно писать")
    for c in cals:
        if set(c["people"]) & set(people or []):
            return c["key"]
    return cals[0]["key"]


def _ops_event(op: dict) -> None:
    """Команды с телефона/Алисы: event_add (готовые поля) и event_quick (фраза, разбираем здесь тем же парсером)."""
    now = datetime.now(tz)
    if op.get("type") == "event_quick":
        q = quick.parse(str(op.get("text", ""))[:300], now.replace(tzinfo=None), db.list_people())
        if not q["title"] or any("дата не указана" in n for n in q["notes"]):
            raise ValueError("не хватает названия или даты: «%s»" % op.get("text", ""))
        fields = {"title": q["title"], "date": q["date"], "start": q["start"], "end": q["end"], "all_day": q["all_day"],
                  "people": q["people"] or [p for p in (op.get("people") or []) if isinstance(p, str)], "repeat": q["repeat"]}
    else:
        fields = {k: op.get(k) for k in ("title", "date", "start", "end", "all_day", "people", "repeat", "location")}
    title = str(fields["title"] or "").strip()[:200]
    d = date.fromisoformat(str(fields["date"]))
    if not (now.date() - timedelta(days=1) <= d <= now.date() + timedelta(days=500)):
        raise ValueError("дата вне разумных пределов")
    all_day = bool(fields.get("all_day")) or not fields.get("start")
    if all_day:
        s, e = datetime.combine(d, time(0), tz), datetime.combine(d + timedelta(days=1), time(0), tz)
    else:
        s = datetime.combine(d, time.fromisoformat(fields["start"]), tz)
        e = datetime.combine(d, time.fromisoformat(fields["end"]), tz) if fields.get("end") else s + timedelta(hours=1)
        if e <= s:
            e = s + timedelta(hours=1)
    people = [p for p in (fields.get("people") or []) if isinstance(p, str)] or None
    cal = op.get("calendar") if op.get("calendar") and _writable(str(op.get("calendar"))) else _pick_calendar(people)
    rep = fields.get("repeat") if isinstance(fields.get("repeat"), dict) and fields["repeat"].get("freq") else None
    _create_event(cal, title, s, e, all_day, str(fields.get("location") or "")[:200], "", rep, people)
