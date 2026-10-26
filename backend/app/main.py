"""HTTP API и раздача веб-интерфейса."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
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
    if any(c["person_id"] not in {p["id"] for p in people} for c in cals if not c["hidden"]):
        people = people + [{"id": UNASSIGNED, "name": "Без владельца", "color": "#8a94a6",
                            "emoji": "", "sort": 999, "hidden": 0}]
    return {
        "title": settings.title,
        "timezone": settings.timezone,
        "version": __version__,
        "people": people,
        "calendars": cals,
        "weather": settings.weather,
        "pin_enabled": bool(settings.pin),
        "accounts": engine.accounts(),
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
    person_id: str | None = None
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


# ---------- веб-интерфейс ----------
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
