"""HTTP API и раздача веб-интерфейса."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import threading
import time as time_module
from time import perf_counter
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import load_settings
from .db import Database
from .events import UNASSIGNED, EventService
from .freetime import find_free
from . import birthdays as bd, ops, reminders, school, snapshot, stats, widget, writer, writeq, quick, portable
from . import conflicts, live
from .backup import BackupService
from .perf import SLOW_MS, PerfLog
from .cloud import CloudError, CloudSync
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
cloud = CloudSync(db, lambda: snapshot.build(events, db, tz))
backup = BackupService(db, cloud, tz)
STARTED = datetime.now(tz)

# Приложение для Android: собранный APK и его версия (android/release в репозитории).
APP_DIR = Path(os.environ.get("HOMECAL_APP_DIR", Path(__file__).resolve().parents[2] / "android" / "release"))

MAC_DIR = Path(os.environ.get("HOMECAL_MAC_DIR", Path(__file__).resolve().parents[2] / "macos" / "release"))

IOS_DIR = Path(os.environ.get("HOMECAL_IOS_DIR", Path(__file__).resolve().parents[2] / "ios" / "release"))

STATIC_DIR = Path(os.environ.get("HOMECAL_STATIC", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


def poll_cloud() -> None:
    """Команды, которые телефоны оставили в облаке, применяем и сразу обновляем снимок."""
    if cloud.poll_ops(lambda items: ops.apply(db, items, {"event_add": _ops_event, "event_quick": _ops_event})):
        events.invalidate()
        cloud.tick(force=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warm, daemon=True).start()
    if os.environ.get("HOMECAL_NO_SCHEDULER") != "1":
        scheduler.add_job(engine.run, "interval", minutes=settings.sync.interval_minutes,
                          next_run_time=datetime.now(tz), id="sync", max_instances=1, coalesce=True)
        # Снимок для телефона вне дома: проверяем раз в 2 минуты, на Диск пишем при изменениях и раз в час.
        scheduler.add_job(ws.flush, "interval", minutes=2, id="writeq", max_instances=1, coalesce=True)
        scheduler.add_job(cloud.tick, "interval", minutes=2, id="cloud", max_instances=1, coalesce=True)
        scheduler.add_job(poll_cloud, "interval", minutes=1, id="cloud-ops", max_instances=1, coalesce=True)
        scheduler.add_job(backup.run, "cron", hour=3, minute=30, id="backup", max_instances=1, coalesce=True,
                          misfire_grace_time=6 * 3600)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="HomeHub Calendar", version=__version__, lifespan=lifespan)


# ---------- простая защита PIN-кодом (включается переменной HOMECAL_PIN) ----------
def _token() -> str:
    return hmac.new(settings.pin.encode(), b"homecal", hashlib.sha256).hexdigest()


perf = PerfLog()


@app.middleware("http")
async def timing(request: Request, call_next):
    """Замер времени каждого запроса к API (GET /api/perf)."""
    if not request.url.path.startswith("/api/") or request.url.path == "/api/stream":
        return await call_next(request)
    t0 = perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        # Любая успешная запись через API — повод обновить остальные открытые экраны.
        if request.method != "GET" and status < 400 and request.url.path not in ("/api/client-log", "/api/login"):
            live.bump()
        return resp
    finally:
        ms = (perf_counter() - t0) * 1000
        route = getattr(request.scope.get("route"), "path", None) or request.url.path
        perf.record(request.method, route, ms, status, request.url.query)
        if ms >= SLOW_MS:
            log.warning("Медленный запрос %s %s: %d мс", request.method, request.url.path, ms)


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    path = request.url.path
    if settings.pin and path.startswith("/api/") and path not in ("/api/login", "/api/health"):
        if not hmac.compare_digest(request.cookies.get("homecal_auth", ""), _token()):
            return JSONResponse({"detail": "auth_required"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    pin: str


_FAILS: dict[str, list] = {}   # ip -> [число неудач, до какого момента заблокирован]


def _login_wait(ip: str) -> int:
    f = _FAILS.get(ip)
    return max(0, int(f[1] - time_module.time())) if f else 0


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    if not settings.pin:
        return {"ok": True}
    ip = request.client.host if request.client else "?"
    wait = _login_wait(ip)
    if wait:
        raise HTTPException(429, f"Слишком много попыток. Подождите {wait // 60 + 1} мин.")
    if not hmac.compare_digest(body.pin, settings.pin):
        n = (_FAILS.get(ip) or [0, 0])[0] + 1
        # 5 ошибок подряд — блокировка на 1 минуту, дальше вдвое дольше (до часа)
        _FAILS[ip] = [n, time_module.time() + (min(3600, 60 * 2 ** (n - 5)) if n >= 5 else 0)]
        if len(_FAILS) > 500:
            _FAILS.clear()
        raise HTTPException(401, "Неверный PIN")
    _FAILS.pop(ip, None)
    response.set_cookie("homecal_auth", _token(), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return {"ok": True}


# ---------- API ----------
def _parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


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
        "calendars": [{**c, "writable": _writable(c["key"])} for c in cals],
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
    a, z = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    return school.merge(db, holidays.between(a, z), a, z)


class SchoolIn(BaseModel):
    breaks: list[dict]


@app.get("/api/school")
def get_school():
    return {"breaks": school.load(db)}


@app.put("/api/school")
def put_school(body: SchoolIn):
    out = school.save(db, body.breaks)
    return {"breaks": out}


class EventRemindersIn(BaseModel):
    people: dict[str, list[int]] = {}
    allday_people: list[str] | None = None
    allday_time: str | None = None


@app.get("/api/settings/event-reminders")
def get_event_reminders():
    return {"people": reminders.load_rules(db), "choices": list(reminders.LEAD_CHOICES),
            "allday": reminders.load_allday(db)}


@app.put("/api/settings/event-reminders")
def put_event_reminders(body: EventRemindersIn):
    known = {p["id"] for p in db.list_people()}
    out = reminders.save_rules(db, body.people, known)
    if body.allday_people is not None or body.allday_time is not None:
        cur = reminders.load_allday(db)
        reminders.save_allday(db, cur["people"] if body.allday_people is None else body.allday_people,
                              body.allday_time or cur["time"], known)
    cloud.tick(force=True)
    return {"people": out, "choices": list(reminders.LEAD_CHOICES), "allday": reminders.load_allday(db)}


@app.get("/api/stats")
def get_stats(start: str, end: str):
    s, e = _parse_dt(start), _parse_dt(end)
    if e <= s or (e - s) > timedelta(days=400):
        raise HTTPException(400, "Некорректный диапазон")
    people = [p for p in db.list_people()]
    return stats.build(events.events(s, e), people, s, e)


@app.get("/api/backup")
def get_backup():
    return backup.status()


@app.post("/api/backup")
def run_backup():
    return backup.run()


@app.get("/api/backup/files")
def backup_files():
    try:
        return {"files": backup.files(), "status": backup.status()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/backup/verify")
def backup_verify(body: dict | None = None):
    return backup.verify((body or {}).get("name"))


@app.post("/api/backup/restore")
def backup_restore(body: dict):
    try:
        res = backup.restore(str(body.get("name", "")))
    except Exception as e:  # noqa: BLE001
        log.exception("Восстановление")
        raise HTTPException(400, str(e))
    _synced()
    return res


@app.get("/api/stream")
async def stream(request: Request):
    """Живое обновление: отдаёт номер изменений, когда он меняется (EventSource в браузере сам переподключается)."""
    async def gen():
        last = live.rev
        yield f"retry: 5000\ndata: {last}\n\n"
        idle = 0
        while not await request.is_disconnected():
            await asyncio.sleep(1)
            if live.rev != last:
                last, idle = live.rev, 0
                yield f"data: {last}\n\n"
            else:
                idle += 1
                if idle >= 20:
                    idle = 0
                    yield ": ka\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/perf")
def get_perf():
    return perf.summary()


@app.get("/api/system")
def get_system():
    """Всё, что нужно для страницы «Состояние»: версии, синхронизация, облако, копии, ошибки клиентов."""
    now = datetime.now(tz)
    sources = db.sync_status()
    cl, bk = cloud.status(), backup.status()
    problems: list[str] = []
    if ws.pending_count():
        problems.append(f"Не отправлено в Яндекс: {ws.pending_count()} (повторю сам, когда сервер ответит)")
    if ws.last_error():
        problems.append("Запись в Яндекс отклонена: " + ws.last_error())
    for s in sources:
        if s.get("last_error"):
            problems.append(f"Синхронизация {s['source_id']}: {s['last_error']}")
        elif s.get("last_ok"):
            age = now - datetime.fromisoformat(s["last_ok"]).astimezone(tz)
            if age > timedelta(minutes=max(30, settings.sync.interval_minutes * 4)):
                problems.append(f"Календарь {s['source_id']} давно не обновлялся ({int(age.total_seconds() // 60)} мин)")
    rej = (db.kv_get("ops:rejected")[0] or {}).get("items", [])
    for r in rej[-3:]:
        if datetime.fromisoformat(r["at"]) > datetime.now() - timedelta(days=2):
            problems.append(f"Команда с телефона не выполнена: «{r['text']}» — {r['why']}")
    if cl["configured"]:
        if cl.get("last_error"):
            problems.append("Облако: " + cl["last_error"])
        if cl.get("ops_error"):
            problems.append("Команды с телефона: " + cl["ops_error"])
        if bk.get("last_error"):
            problems.append("Резервная копия: " + bk["last_error"])
        elif bk.get("last_ok") and now - datetime.fromisoformat(bk["last_ok"]).astimezone(tz) > timedelta(days=3):
            problems.append("Резервной копии не было больше 3 суток")
    jobs = {j.id: j.next_run_time.isoformat(timespec="seconds") for j in scheduler.get_jobs() if j.next_run_time}
    count = lambda sql: (db.query(sql) or [{"n": 0}])[0]["n"]  # noqa: E731
    try:
        db_size = os.path.getsize(db.path)
    except OSError:
        db_size = None
    return {
        "version": __version__, "started": STARTED.isoformat(timespec="seconds"), "now": now.isoformat(timespec="seconds"),
        "db_size": db_size,
        "counts": {"people": count("SELECT COUNT(*) n FROM people"), "calendars": count("SELECT COUNT(*) n FROM calendars"),
                   "objects": count("SELECT COUNT(*) n FROM objects"), "birthdays": count("SELECT COUNT(*) n FROM birthdays")},
        "sources": sources, "sync_interval": settings.sync.interval_minutes, "syncing": engine.running,
        "cloud": {k: cl[k] for k in ("configured", "last_ok", "last_error", "ops_error")},
        "backup": bk, "jobs": jobs, "client_errors": len(CLIENT_LOG), "slow_requests": perf.slow_count(),
        "last_client_error": CLIENT_LOG[-1] if CLIENT_LOG else None, "problems": problems,
    }


@app.get("/api/status")
def get_status():
    return {"running": engine.running, "sources": db.sync_status(),
            "configured_sources": [s.get("id") for s in settings.sources]}


@app.post("/api/sync")
def trigger_sync():
    return engine.run(full=True)


class AccountIn(BaseModel):
    username: str
    password: str | None = None  # пусто — оставить прежний


@app.put("/api/accounts/{source_id}")
def put_account(source_id: str, body: AccountIn):
    try:
        engine.set_credentials(source_id, body.username, body.password)
    except KeyError:
        raise HTTPException(404, "Источник не найден")
    return engine.run(full=True).get(source_id, {"ok": False, "error": "источник выключен"})


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


class RepeatIn(BaseModel):
    freq: str | None = None  # daily | weekly | monthly | yearly
    interval: int = 1
    count: int | None = None
    until: str | None = None
    byday: list[str] | None = None   # для weekly: MO, TU, … — несколько дней недели


class EventIn(BaseModel):
    calendar: str
    title: str
    start: str
    end: str | None = None
    all_day: bool = False
    location: str = ""
    description: str = ""
    repeat: RepeatIn | None = None
    people: list[str] | None = None


class EventEdit(BaseModel):
    calendar: str
    title: str | None = None
    start: str | None = None
    end: str | None = None
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    repeat: RepeatIn | None = None
    repeat_set: bool = False  # True — применить repeat (в т.ч. убрать повтор)
    people: list[str] | None = None
    people_set: bool = False
    occurrence: str | None = None  # начало редактируемого вхождения (для серий)
    scope: str | None = None       # series (по умолчанию) | once — только это вхождение | following — это и следующие


def _check_people(people):
    known = {p["id"] for p in db.list_people()}
    bad = [p for p in people or [] if p not in known]
    if bad:
        raise HTTPException(400, f"Неизвестные люди: {', '.join(bad)}")


class ConflictIn(BaseModel):
    calendar: str
    title: str = ""
    start: str
    end: str | None = None
    all_day: bool = False
    location: str = ""
    people: list[str] | None = None
    uid: str | None = None


@app.post("/api/conflicts")
def check_conflicts(body: ConflictIn):
    """Что не сходится, если поставить событие сюда (для предупреждения в форме и при переносе)."""
    try:
        items = conflicts.check(events, calendar=body.calendar, title=body.title, start=_parse_dt(body.start),
                                end=_parse_dt(body.end) if body.end else None, all_day=body.all_day,
                                people=body.people, uid=body.uid, location=body.location)
    except ValueError:
        raise HTTPException(400, "Неверная дата")
    return {"items": items}


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


class SelfTestIn(BaseModel):
    calendar: str


@app.post("/api/selftest/write")
def selftest_write(body: SelfTestIn):
    """Проверка записи в живой календарь: создать → перенести → прочитать с сервера → серия с исключением → удалить.
    Идёт мимо локальной базы и журнала (семья ничего не увидит), тестовые события живут секунды."""
    target = make_target(body.calendar)
    rid = _remote_id(body.calendar)
    steps: list[dict] = []
    day = datetime.now(tz).date() + timedelta(days=30)
    s0 = datetime.combine(day, time(3, 0), tz)

    def step(name: str, fn):
        t0 = perf_counter()
        try:
            out = fn()
            steps.append({"name": name, "ok": True, "ms": round((perf_counter() - t0) * 1000)})
            return out
        except Exception as e:  # noqa: BLE001
            steps.append({"name": name, "ok": False, "error": writer.friendly(e), "ms": round((perf_counter() - t0) * 1000)})
            raise

    hrefs: list[str] = []
    try:
        uid, ics = writer.build_ics("Проверка HomeHub (можно удалить)", s0, s0 + timedelta(minutes=30), False, tz)
        href = step("Создать событие", lambda: target.create(rid, ics))
        hrefs.append(href)
        back = step("Прочитать его с сервера", lambda: target.read(rid, href) or (_ for _ in ()).throw(writer.WriteError("Событие не нашлось")))
        if "Проверка HomeHub" not in back:
            raise writer.WriteError("Сервер вернул не то событие")
        moved = writer.apply_edit(ics, {"title": "Проверка HomeHub — перенос", "start": s0 + timedelta(hours=1),
                                        "end": s0 + timedelta(hours=1, minutes=30), "all_day": False}, tz)
        step("Перенести и переименовать", lambda: target.update(rid, href, moved))
        back = step("Проверить перенос", lambda: target.read(rid, href) or "")
        if "перенос" not in back or "T040000" not in back:
            raise writer.WriteError("После переноса на сервере прежнее время или название")
        uid2, series = writer.build_ics("Проверка серии HomeHub", s0, s0 + timedelta(minutes=30), False, tz,
                                        repeat={"freq": "weekly", "byday": [writer._DAYS[s0.weekday()]], "count": 4})
        h2 = step("Создать повторяющееся событие", lambda: target.create(rid, series))
        hrefs.append(h2)
        cut = writer.add_exdate(series, s0 + timedelta(days=7), tz)
        step("Убрать одно вхождение (EXDATE)", lambda: target.update(rid, h2, cut))
        if "EXDATE" not in (target.read(rid, h2) or ""):
            raise writer.WriteError("Сервер не сохранил исключение из серии")
    except Exception as e:  # noqa: BLE001
        if not steps or steps[-1]["ok"]:
            steps.append({"name": "Проверка", "ok": False, "error": writer.friendly(e)})
    finally:
        for h in hrefs:
            try:
                target.delete(rid, h)
                steps.append({"name": "Удалить тестовое событие", "ok": True})
            except Exception as e:  # noqa: BLE001
                steps.append({"name": "Удалить тестовое событие", "ok": False, "error": writer.friendly(e) + f" ({h})"})
    ok = all(x["ok"] for x in steps)
    log.info("Самопроверка записи %s: %s", body.calendar, "успешно" if ok else steps)
    return {"ok": ok, "steps": steps}


@app.post("/api/event")
def create_event(body: EventIn):
    uid, sent = _create_event(body.calendar, body.title, _parse_dt(body.start), _parse_dt(body.end) if body.end else None,
                              body.all_day, body.location, body.description,
                              body.repeat.model_dump() if body.repeat else None, body.people)
    return {"ok": True, "uid": uid, "pending": not sent}


class SectionRow(BaseModel):
    day: int                      # 0 — понедельник … 6 — воскресенье
    start: str                    # HH:MM
    end: str
    dropoff: str | None = None    # id взрослого, '-' (не нужно) или пусто (не назначать)
    pickup: str | None = None
    travel: int | None = None     # минут в дороге


class SectionIn(BaseModel):
    calendar: str
    title: str
    location: str = ""
    people: list[str] | None = None
    from_date: str                # с какой даты (YYYY-MM-DD): первое занятие — ближайший подходящий день недели
    until: str | None = None      # по какую дату включительно
    count: int | None = None
    rows: list[SectionRow]


@app.post("/api/section")
def create_section(body: SectionIn):
    """Мастер секций: «Ушу по вт и чт до мая» — недельные серии (дни с одинаковым временем и водителями — одна серия) + поездки."""
    if not body.rows:
        raise HTTPException(400, "Выберите хотя бы один день недели")
    if not body.title.strip():
        raise HTTPException(400, "Нужно название")
    try:
        d0 = date.fromisoformat(body.from_date)
        until = date.fromisoformat(body.until) if body.until else None
    except ValueError:
        raise HTTPException(400, "Неверная дата")
    if until and until < d0:
        raise HTTPException(400, "«До» раньше «С»")
    if until and (until - d0).days > 800:
        raise HTTPException(400, "Слишком длинный период")
    known = {p["id"] for p in db.list_people()}
    for r in body.rows:
        for who in (r.dropoff, r.pickup):
            if who and who != "-" and who not in known:
                raise HTTPException(400, f"Неизвестный человек: {who}")
        if not 0 <= r.day <= 6:
            raise HTTPException(400, "Неверный день недели")
        if (r.travel or 0) < 0 or (r.travel or 0) > 240:
            raise HTTPException(400, "Время в пути — от 0 до 240 минут")
    groups: dict[tuple, list[int]] = {}
    for r in body.rows:
        groups.setdefault((r.start, r.end, r.dropoff, r.pickup, r.travel), []).append(r.day)
    created, pending = [], False
    for (st, en, drop, pick, travel), days in groups.items():
        days = sorted(set(days))
        first = min(d0 + timedelta(days=(wd - d0.weekday()) % 7) for wd in days)
        try:
            s_ = datetime.combine(first, time.fromisoformat(st), tz)
            e_ = datetime.combine(first, time.fromisoformat(en), tz)
        except ValueError:
            raise HTTPException(400, "Неверное время")
        if e_ <= s_:
            raise HTTPException(400, "Конец занятия должен быть позже начала")
        rep = {"freq": "weekly", "byday": [writer._DAYS[d] for d in days],
               "until": until.isoformat() if until else None, "count": None if until else body.count}
        uid, sent = _create_event(body.calendar, body.title.strip(), s_, e_, False, body.location, "", rep, body.people)
        pending = pending or not sent
        for role, who in (("dropoff", drop), ("pickup", pick)):
            if who:
                db.set_escort(uid, "*", role, who)
        if travel:
            db.set_escort(uid, "*", "travel", str(travel))
        created.append({"uid": uid, "days": days, "start": st, "end": en})
    _after_write()
    return {"ok": True, "created": created, "pending": pending}


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


@app.put("/api/event/{uid}")
def update_event(uid: str, body: EventEdit):
    found = db.find_object(uid, body.calendar)
    if not found:
        raise HTTPException(404, "Событие не найдено (возможно, оно удалено)")
    cal_key, href, ics = found
    make_target(cal_key)
    _check_people(body.people)
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.start is not None:
        fields.update(start=_parse_dt(body.start), end=_parse_dt(body.end) if body.end else None,
                      all_day=body.all_day, occurrence=_parse_dt(body.occurrence) if body.occurrence else None)
    if body.location is not None:
        fields["location"] = body.location
    if body.description is not None:
        fields["description"] = body.description
    if body.repeat_set:
        fields["repeat"] = body.repeat.model_dump() if body.repeat else None
    if body.scope == "following":
        if not (body.occurrence and body.start):
            raise HTTPException(400, "Не указано, с какого вхождения менять")

        def split_following():
            res = writer.split_following(
                ics, _parse_dt(body.occurrence),
                {**fields, "start": _parse_dt(body.start), "end": _parse_dt(body.end) if body.end else None,
                 "all_day": body.all_day}, tz)
            if res is None:   # первое вхождение — это вся серия
                return None
            old_ics, new_uid, new_ics = res
            ok1 = ws.update(cal_key, href, ics, old_ics)
            ok2 = ws.create(cal_key, new_ics)
            ppl = body.people if body.people_set else db.event_people().get(uid)
            if ppl is not None:
                db.set_event_people(new_uid, ppl)
            for (u, occ_, role), person in db.escorts().items():   # назначения «на всю серию» переходят в новую серию
                if u == uid and occ_ == "*":
                    db.set_escort(new_uid, "*", role, person)
            return ok1 and ok2
        sent = _run_write(split_following)
        if sent is not None:
            _after_write()
            return {"ok": True, "pending": not sent}
        body.scope = None   # первое вхождение: падаем в обычную правку серии
        fields.pop("occurrence", None)
    if body.scope == "once":
        if not (body.occurrence and body.start):
            raise HTTPException(400, "Не указано, какое вхождение переносить")

        def split():
            series, new_uid, new_ics = writer.split_occurrence(
                ics, _parse_dt(body.occurrence), _parse_dt(body.start), _parse_dt(body.end) if body.end else None,
                body.all_day, tz)
            if "title" in fields or "location" in fields or "description" in fields:
                new_ics = writer.apply_edit(new_ics, {k: v for k, v in fields.items() if k in ("title", "location", "description")}, tz)
            ok1 = ws.update(cal_key, href, ics, series)
            ok2 = ws.create(cal_key, new_ics)
            ppl = db.event_people().get(uid)
            if ppl is not None:
                db.set_event_people(new_uid, ppl)
            return ok1 and ok2
        sent = _run_write(split)
        _after_write()
        return {"ok": True, "pending": not sent}
    sent = _run_write(lambda: ws.update(cal_key, href, ics, writer.apply_edit(ics, fields, tz)))
    if body.people_set:
        db.set_event_people(uid, body.people)
    _after_write()
    return {"ok": True, "pending": not sent}


@app.delete("/api/event/{uid}")
def delete_event(uid: str, calendar: str, occurrence: str | None = None):
    """occurrence — время начала вхождения: убрать только его (для серий); иначе удаляется всё событие."""
    found = db.find_object(uid, calendar)
    if not found:
        raise HTTPException(404, "Событие не найдено (возможно, оно удалено)")
    cal_key, href, ics = found
    make_target(cal_key)

    def go():
        new_ics = writer.add_exdate(ics, _parse_dt(occurrence), tz) if occurrence else None
        if new_ics:
            return ws.update(cal_key, href, ics, new_ics)
        sent = ws.delete(cal_key, href, ics)
        db.set_event_people(uid, None)
        return sent
    sent = _run_write(go)
    _after_write()
    return {"ok": True, "pending": not sent}


class QuickIn(BaseModel):
    text: str


@app.post("/api/quick")
def quick_parse(body: QuickIn):
    """Разбор фразы вроде «Йога завтра в 18:30 у Оли» в поля формы (ничего не создаёт)."""
    if not body.text.strip():
        raise HTTPException(400, "Пустая фраза")
    return quick.parse(body.text, datetime.now(tz).replace(tzinfo=None), db.list_people())


@app.get("/api/export")
def export_settings():
    data = portable.export(db, __version__)
    name = f"homehub-settings-{datetime.now(tz):%Y-%m-%d}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/import")
def import_settings(body: dict):
    try:
        counts = portable.import_(db, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("Импорт настроек")
        raise HTTPException(400, f"Не удалось загрузить настройки: {e}")
    events.invalidate()
    return {"ok": True, "counts": counts}


@app.get("/api/changes")
def get_changes():
    """Журнал правок (последние первыми) и число ещё не отправленных в Яндекс."""
    items = [{k: v for k, v in e.items() if k not in ("before", "after")} for e in reversed(ws.journal())]
    return {"items": items, "pending": ws.pending_count(), "error": ws.last_error()}


@app.post("/api/changes/{entry_id}/undo")
def undo_change(entry_id: str):
    title = _run_write(lambda: ws.undo(entry_id))
    _after_write()
    return {"ok": True, "title": title}


@app.post("/api/changes/flush")
def flush_changes():
    return ws.flush()


class EscortIn(BaseModel):
    uid: str
    occurrence: str | None = None  # время начала вхождения; None — вся серия
    role: str                      # dropoff | pickup | mode
    person: str | None = None      # id взрослого, '-' — не нужно, None — снять назначение;
                                   # для role=mode: escort | together | home | None (автоматически)


@app.post("/api/escort")
def set_escort(body: EscortIn):
    if body.role not in ("dropoff", "pickup", "mode", "travel"):
        raise HTTPException(400, "role: dropoff, pickup, mode или travel")
    if body.role == "travel":
        if body.person is not None and not (body.person.isdigit() and int(body.person) <= 240):
            raise HTTPException(400, "travel: число минут от 0 до 240")
    elif body.role == "mode":
        if body.person not in (None, "escort", "together", "home"):
            raise HTTPException(400, "mode: escort, together или home")
    elif body.person not in (None, "-") and body.person not in {p["id"] for p in db.list_people()}:
        raise HTTPException(400, "Неизвестный человек")
    # Разовые замены важнее назначения на серию и при его смене сохраняются.
    db.set_escort(body.uid, body.occurrence or "*", body.role, body.person)
    events.invalidate()
    return {"ok": True}


class Place(BaseModel):
    words: str      # слова в названии или месте через запятую
    minutes: int    # сколько ехать


class EscortSettings(BaseModel):
    before_minutes: int = 30
    after_minutes: int = 30
    travel_buffer: int = 5     # запас к времени в пути
    places: list[Place] = []   # «секция, бассейн» → 25 минут
    home_words: str = "дома"   # через запятую; событие с таким словом — «дома»
    home_address: str = ""     # часть адреса: событие в этом месте — «дома»


@app.put("/api/settings/escort")
def put_escort_settings(body: EscortSettings):
    if not (0 <= body.before_minutes <= 240 and 0 <= body.after_minutes <= 240
            and 0 <= body.travel_buffer <= 60 and all(0 <= p.minutes <= 240 for p in body.places)):
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
    evs = events.events(start, start + timedelta(days=days))
    soon = bd.upcoming(db.birthdays(), events.events(start, start + timedelta(days=15)), start.date(), 14)[:2]
    return widget.build(evs, plist, tz, now, days, only, soon)


# ---------- шаблоны поездок по дням недели ----------
class TemplateIn(BaseModel):
    id: int | None = None
    child_id: str
    weekday: int            # 0 — понедельник
    match: str = ""         # слова в названии; пусто — любое событие ребёнка в этот день
    dropoff: str = ""       # id взрослого, '-' — не нужно, '' — не задано
    pickup: str = ""


@app.get("/api/templates")
def list_templates():
    return db.templates()


@app.put("/api/templates")
def put_template(body: TemplateIn):
    ids = {p["id"] for p in db.list_people()}
    if body.child_id not in ids or not 0 <= body.weekday <= 6:
        raise HTTPException(400, "Некорректный ребёнок или день недели")
    for v in (body.dropoff, body.pickup):
        if v not in ("", "-") and v not in ids:
            raise HTTPException(400, "Неизвестный человек")
    tid = db.save_template(body.model_dump())
    events.invalidate()
    return {"ok": True, "id": tid}


@app.delete("/api/templates/{tid}")
def delete_template(tid: int):
    db.delete_template(tid)
    events.invalidate()
    return {"ok": True}


# ---------- дни рождения ----------
class BirthdayIn(BaseModel):
    id: int | None = None
    name: str
    month: int
    day: int
    year: int | None = None


def _today_start() -> datetime:
    return datetime.combine(datetime.now(tz).date(), time(0), tz)


@app.get("/api/birthdays")
def get_birthdays(days: int = 60):
    start = _today_start()
    evs = events.events(start, start + timedelta(days=min(max(days, 1), 120) + 1))
    return {"upcoming": bd.upcoming(db.birthdays(), evs, start.date(), min(max(days, 1), 120)),
            "all": db.birthdays()}


@app.put("/api/birthdays")
def put_birthday(body: BirthdayIn):
    try:
        date(body.year or 2000, body.month, body.day)
    except ValueError:
        raise HTTPException(400, "Некорректная дата")
    if not body.name.strip():
        raise HTTPException(400, "Укажите имя")
    return {"ok": True, "id": db.save_birthday(body.model_dump())}


@app.delete("/api/birthdays/{bid}")
def delete_birthday(bid: int):
    db.delete_birthday(bid)
    return {"ok": True}


# ---------- поиск ----------
@app.get("/api/search")
def search(q: str):
    q = q.strip().lower()
    if len(q) < 2:
        return []
    today = _today_start()
    found = [e for e in events.events(today - timedelta(days=60), today + timedelta(days=330))
             if not e.get("duty") and (q in e["title"].lower() or q in (e.get("location") or "").lower()
                                       or q in (e.get("description") or "").lower())]
    found.sort(key=lambda e: e["start"])
    return found[:300]


# ---------- списки дел и покупок ----------
class ListIn(BaseModel):
    name: str


class ItemIn(BaseModel):
    text: str
    person_id: str | None = None


class ItemPatch(BaseModel):
    text: str | None = None
    done: bool | None = None
    person_id: str | None = None


@app.get("/api/lists")
def get_lists():
    return db.lists()


@app.post("/api/lists")
def create_list(body: ListIn):
    if not body.name.strip():
        raise HTTPException(400, "Укажите название")
    return {"ok": True, "id": db.add_list(body.name)}


@app.put("/api/lists/{lid}")
def rename_list(lid: int, body: ListIn):
    db.rename_list(lid, body.name)
    return {"ok": True}


@app.delete("/api/lists/{lid}")
def delete_list(lid: int):
    db.delete_list(lid)
    return {"ok": True}


@app.post("/api/lists/{lid}/items")
def add_item(lid: int, body: ItemIn):
    if not body.text.strip():
        raise HTTPException(400, "Пустая запись")
    return {"ok": True, "id": db.add_item(lid, body.text, body.person_id)}


@app.post("/api/lists/{lid}/clear-done")
def clear_done(lid: int):
    db.clear_done(lid)
    return {"ok": True}


@app.patch("/api/items/{iid}")
def patch_item(iid: int, body: ItemPatch):
    db.update_item(iid, body.model_dump(exclude_unset=True))
    return {"ok": True}


@app.delete("/api/items/{iid}")
def delete_item(iid: int):
    db.delete_item(iid)
    return {"ok": True}


# ---------- напоминания для приложения ----------
@app.get("/api/reminders")
def get_reminders(hours: int = 36, lead: int = 30, people: str | None = None):
    """Что и когда напомнить. people — чьи поездки (id через запятую); пусто — всех."""
    now = datetime.now(tz)
    start = _today_start()
    evs = events.events(start, start + timedelta(days=4))
    wanted = {p for p in (people or "").split(",") if p} or None
    items = reminders.build(evs, db.birthdays(), now, tz, wanted, max(0, min(lead, 240)), 2,
                            reminders.load_rules(db), reminders.load_allday(db))
    lo, hi = now - timedelta(hours=3), now + timedelta(hours=max(1, min(hours, 72)))
    return {"now": now.isoformat(timespec="seconds"),
            "items": [r for r in items if lo <= datetime.fromisoformat(r["at"]) <= hi]}


# ---------- снимок для телефона и Яндекс.Диск ----------
@app.get("/api/snapshot")
def get_snapshot():
    """То же, что лежит в облаке (но без шифрования): виджет и напоминания на 7 дней."""
    return snapshot.build(events, db, tz)


class CloudIn(BaseModel):
    token: str | None = None  # пусто — отключить


@app.get("/api/cloud")
def get_cloud():
    return cloud.status()


@app.put("/api/cloud")
def put_cloud(body: CloudIn):
    try:
        cloud.set_token(body.token)
    except CloudError as e:
        raise HTTPException(400, str(e))
    return cloud.tick(force=True)


@app.post("/api/cloud/push")
def push_cloud():
    return cloud.tick(force=True)


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


@app.get("/api/app-mac")
def get_app_mac():
    """Сборка приложения для macOS (кладёт в репозиторий GitHub Actions)."""
    meta = MAC_DIR / "version.json"
    zip_ = MAC_DIR / "HomeHub-Calendar.zip"
    if not (meta.exists() and zip_.exists()):
        return {"available": False}
    import json
    return {"available": True, "url": "/app-mac.zip", "size": zip_.stat().st_size,
            **json.loads(meta.read_text(encoding="utf-8"))}


@app.get("/app-mac.zip", include_in_schema=False)
def download_app_mac():
    f = MAC_DIR / "HomeHub-Calendar.zip"
    if not f.exists():
        raise HTTPException(404, "Приложение для Mac ещё не собрано")
    return FileResponse(f, media_type="application/zip", filename="HomeHub-Calendar.zip")


def _ios_release() -> dict | None:
    meta, ipa = IOS_DIR / "version.json", IOS_DIR / "HomeHub-Calendar.ipa"
    if not (meta.exists() and ipa.exists()):
        return None
    import json
    return {**json.loads(meta.read_text(encoding="utf-8")), "size": ipa.stat().st_size}


@app.get("/api/app-ios")
def get_app_ios():
    rel = _ios_release()
    return {"available": False} if not rel else {"available": True, "url": "/app-ios.ipa", **rel}


@app.get("/app-ios.ipa", include_in_schema=False)
def download_app_ios():
    f = IOS_DIR / "HomeHub-Calendar.ipa"
    if not f.exists():
        raise HTTPException(404, "Приложение для iPhone ещё не собрано")
    return FileResponse(f, media_type="application/octet-stream", filename="HomeHub-Calendar.ipa")


@app.get("/altstore-icon.png", include_in_schema=False)
def altstore_icon():
    f = IOS_DIR / "icon.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/png")


@app.get("/altstore.json", include_in_schema=False)
def altstore_source(request: Request):
    """Источник для AltStore: добавьте этот адрес в AltStore → Sources, и приложение будет ставиться и обновляться оттуда."""
    rel = _ios_release() or {}
    base = str(request.base_url).rstrip("/")
    version = {"version": rel.get("version", "1.0"), "buildVersion": str(rel.get("build", 1)), "date": rel.get("date", "2026-01-01"),
               "size": rel.get("size", 0), "downloadURL": f"{base}/app-ios.ipa", "minOSVersion": "16.0",
               "localizedDescription": "Окно календаря, ближайшие события и напоминания."}
    app_ = {"name": "Домашний календарь", "bundleIdentifier": "ru.homehub.calendar.ios", "developerName": "HomeHub",
            "subtitle": "Семейный календарь", "tintColor": "FF3B30", "iconURL": f"{base}/altstore-icon.png",
            "localizedDescription": "Семейный календарь: общий вид дня, поездки детей, ближайшие события и напоминания. Вне дома читает снимок из облака.",
            "screenshotURLs": [], "versions": [version],
            # поля прежнего формата источников — для старых версий AltStore
            "version": version["version"], "versionDate": version["date"], "size": version["size"],
            "downloadURL": version["downloadURL"]}
    return {"name": "Домашний календарь", "identifier": "ru.homehub.calendar.source", "sourceURL": f"{base}/altstore.json",
            "apps": [app_] if rel else [], "news": []}


# ---------- веб-интерфейс ----------
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
