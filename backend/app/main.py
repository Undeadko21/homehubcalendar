"""HTTP API и раздача веб-интерфейса."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import load_settings
from .db import Database
from .events import UNASSIGNED, EventService
from .freetime import find_free
from . import widget
from .holidays import HolidayService
from .sync import SyncEngine

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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

# Приложение для Android: собранный APK и его версия (android/release в репозитории).
APP_DIR = Path(os.environ.get("HOMECAL_APP_DIR", Path(__file__).resolve().parents[2] / "android" / "release"))

STATIC_DIR = Path(os.environ.get("HOMECAL_STATIC", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("HOMECAL_NO_SCHEDULER") != "1":
        scheduler.add_job(engine.run, "interval", minutes=settings.sync.interval_minutes,
                          next_run_time=datetime.now(tz), id="sync", max_instances=1, coalesce=True)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="HomeHub Calendar", version=__version__, lifespan=lifespan)


# ---------- простая защита PIN-кодом (включается переменной HOMECAL_PIN) ----------
def _token() -> str:
    return hmac.new(settings.pin.encode(), b"homecal", hashlib.sha256).hexdigest()


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    path = request.url.path
    if settings.pin and path.startswith("/api/") and path not in ("/api/login", "/api/health"):
        if not hmac.compare_digest(request.cookies.get("homecal_auth", ""), _token()):
            return JSONResponse({"detail": "auth_required"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    pin: str


@app.post("/api/login")
def login(body: Login, response: Response):
    if not settings.pin:
        return {"ok": True}
    if not hmac.compare_digest(body.pin, settings.pin):
        raise HTTPException(401, "Неверный PIN")
    response.set_cookie("homecal_auth", _token(), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return {"ok": True}


# ---------- API ----------
def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/config")
def get_config():
    people = db.list_people()
    cals = db.list_calendars()
    known = {p["id"] for p in people}
    if any(not (set(c["people"]) & known) for c in cals if not c["hidden"]):
        people = people + [{"id": UNASSIGNED, "name": "Без владельца", "color": "#8a94a6",
                            "emoji": "", "sort": 999, "hidden": 0, "keywords": ""}]
    return {
        "title": settings.title,
        "timezone": settings.timezone,
        "version": __version__,
        "people": people,
        "calendars": cals,
        "weather": settings.weather,
        "pin_enabled": bool(settings.pin),
        "accounts": engine.accounts(),
        "escort": events.escort_settings(),
    }


@app.get("/api/events")
def get_events(start: str, end: str, people: str | None = None):
    s, e = _parse_dt(start), _parse_dt(end)
    if e <= s or (e - s) > timedelta(days=400):
        raise HTTPException(400, "Некорректный диапазон")
    items = events.events(s, e)
    if people:
        wanted = set(people.split(","))
        items = [i for i in items if wanted & set(i["people"])]
    return items


@app.get("/api/holidays")
def get_holidays(start: str, end: str):
    return holidays.between(date.fromisoformat(start[:10]), date.fromisoformat(end[:10]))


@app.get("/api/status")
def get_status():
    return {"running": engine.running, "sources": db.sync_status(),
            "configured_sources": [s.get("id") for s in settings.sources]}


@app.post("/api/sync")
def trigger_sync():
    return engine.run()


class AccountIn(BaseModel):
    username: str
    password: str | None = None  # пусто — оставить прежний


@app.put("/api/accounts/{source_id}")
def put_account(source_id: str, body: AccountIn):
    try:
        engine.set_credentials(source_id, body.username, body.password)
    except KeyError:
        raise HTTPException(404, "Источник не найден")
    return engine.run().get(source_id, {"ok": False, "error": "источник выключен"})


class PersonIn(BaseModel):
    id: str
    name: str
    color: str = "#6b7280"
    emoji: str = ""
    sort: int = 0
    hidden: bool = False
    keywords: str = ""  # слова автопривязки через запятую
    needs_escort: bool = False  # ребёнок: его отвозят и забирают


@app.get("/api/people")
def list_people():
    return db.list_people()


@app.put("/api/people/{person_id}")
def put_person(person_id: str, body: PersonIn):
    if person_id != body.id or person_id == UNASSIGNED:
        raise HTTPException(400, "Некорректный id")
    db.upsert_person(body.model_dump())
    events.invalidate()
    return {"ok": True}


@app.delete("/api/people/{person_id}")
def delete_person(person_id: str):
    db.delete_person(person_id)
    events.invalidate()
    return {"ok": True}


class CalendarPatch(BaseModel):
    people: list[str] | None = None
    person_id: str | None = None  # устаревшее: один владелец
    color: str | None = None
    hidden: bool | None = None
    private: bool | None = None


@app.patch("/api/calendars/{key:path}")
def patch_calendar(key: str, body: CalendarPatch):
    if not db.get_calendar(key):
        raise HTTPException(404, "Календарь не найден")
    db.update_calendar(key, body.model_dump(exclude_unset=True))
    events.invalidate()
    return {"ok": True}


class EventPeople(BaseModel):
    uid: str
    people: list[str] | None = None  # None — вернуть участников по умолчанию


@app.post("/api/event-people")
def set_event_people(body: EventPeople):
    if body.people is not None:
        known = {p["id"] for p in db.list_people()}
        unknown = [p for p in body.people if p not in known]
        if unknown:
            raise HTTPException(400, f"Неизвестные люди: {', '.join(unknown)}")
    db.set_event_people(body.uid, body.people)
    events.invalidate()
    return {"ok": True}


class EscortIn(BaseModel):
    uid: str
    occurrence: str | None = None  # время начала вхождения; None — вся серия
    role: str                      # dropoff | pickup | mode
    person: str | None = None      # id взрослого, '-' — не нужно, None — снять назначение;
                                   # для role=mode: escort | together | home | None (автоматически)


@app.post("/api/escort")
def set_escort(body: EscortIn):
    if body.role not in ("dropoff", "pickup", "mode"):
        raise HTTPException(400, "role: dropoff, pickup или mode")
    if body.role == "mode":
        if body.person not in (None, "escort", "together", "home"):
            raise HTTPException(400, "mode: escort, together или home")
    elif body.person not in (None, "-") and body.person not in {p["id"] for p in db.list_people()}:
        raise HTTPException(400, "Неизвестный человек")
    # Разовые замены важнее назначения на серию и при его смене сохраняются.
    db.set_escort(body.uid, body.occurrence or "*", body.role, body.person)
    events.invalidate()
    return {"ok": True}


class EscortSettings(BaseModel):
    before_minutes: int = 30
    after_minutes: int = 30
    home_words: str = "дома"   # через запятую; событие с таким словом — «дома»
    home_address: str = ""     # часть адреса: событие в этом месте — «дома»


@app.put("/api/settings/escort")
def put_escort_settings(body: EscortSettings):
    if not (0 <= body.before_minutes <= 240 and 0 <= body.after_minutes <= 240):
        raise HTTPException(400, "От 0 до 240 минут")
    db.kv_set("settings:escort", {**events.escort_settings(), **body.model_dump(exclude_unset=True)})
    events.invalidate()
    return {"ok": True}


@app.get("/api/free")
def get_free(people: str, start: str, end: str, day_from: str = "08:00", day_to: str = "22:00",
             min_minutes: int = 60, all_day: bool = False):
    ids = [p for p in people.split(",") if p]
    if not ids:
        raise HTTPException(400, "Выберите хотя бы одного человека")
    d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if d1 <= d0 or (d1 - d0).days > 62:
        raise HTTPException(400, "Период от 1 до 62 дней")
    s = datetime.combine(d0, time(0), tz)
    e = datetime.combine(d1, time(0), tz)
    return find_free(events.events(s, e), ids, d0, d1, tz,
                     time.fromisoformat(day_from), time.fromisoformat(day_to), max(15, min_minutes), all_day)


@app.get("/api/widget")
def get_widget(days: int = 2, people: str | None = None):
    """Готовые к показу события для виджета: сегодня (оставшиеся) и следующие дни."""
    days = max(1, min(days, 7))
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time(0), tz)
    plist = {p["id"]: p for p in db.list_people() if not p["hidden"]}
    only = set(people.split(",")) if people else None
    return widget.build(events.events(start, start + timedelta(days=days)), plist, tz, now, days, only)


# ---------- ошибки из браузеров и приложения (для диагностики) ----------
CLIENT_LOG: list[dict] = []


class ClientLog(BaseModel):
    message: str
    stack: str = ""
    url: str = ""
    ua: str = ""
    kind: str = "error"


@app.post("/api/client-log")
def post_client_log(body: ClientLog, request: Request):
    entry = {**body.model_dump(), "at": datetime.now(tz).isoformat(timespec="seconds"),
             "ip": request.client.host if request.client else ""}
    entry = {k: (v[:2000] if isinstance(v, str) else v) for k, v in entry.items()}
    CLIENT_LOG.append(entry)
    del CLIENT_LOG[:-100]
    log.warning("Ошибка в клиенте %s: %s", entry["ip"], entry["message"])
    return {"ok": True}


@app.get("/api/client-log")
def get_client_log():
    return list(reversed(CLIENT_LOG))


@app.get("/api/app")
def get_app():
    """Последняя версия приложения для Android, которую раздаёт этот сервер."""
    meta = APP_DIR / "version.json"
    apk = APP_DIR / "homehub-calendar.apk"
    if not (meta.exists() and apk.exists()):
        return {"available": False}
    import json
    info = json.loads(meta.read_text(encoding="utf-8"))
    return {"available": True, "url": "/app.apk", "size": apk.stat().st_size, **info}


@app.get("/app.apk", include_in_schema=False)
def download_app():
    apk = APP_DIR / "homehub-calendar.apk"
    if not apk.exists():
        raise HTTPException(404, "Приложение ещё не собрано")
    return FileResponse(apk, media_type="application/vnd.android.package-archive",
                        filename="homehub-calendar.apk")


# ---------- веб-интерфейс ----------
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
