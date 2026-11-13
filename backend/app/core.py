"""Общие объекты приложения: настройки, база, сервисы (события, синхронизация, облако, копии, запись) и помощники.

Маршруты лежат в app/api/*.py и обращаются сюда как `core.db`, `core.events` и т. д. (тесты подменяют `core.make_target`)."""
from __future__ import annotations

import logging
import re
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
from .sessions import Sessions
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
sessions = Sessions(db)
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
        events.warm()   # собирает и кладёт в кэш всю ленту окна
    except Exception:  # noqa: BLE001
        log.exception("Прогрев")


def routes_refresh() -> int:
    """Время в дороге по карте: досчитать новые места событий детей на две недели вперёд (если включено в настройках)."""
    from . import routing
    cfg = events.escort_settings()
    home = str(cfg.get("map_home") or "").strip()
    if not cfg.get("map_travel") or not home:
        return 0
    try:
        start = _today_start()
        found = routing.refresh(db, events.events(start, start + timedelta(days=14)), home)
        if found:
            events.refresh()
        return found
    except Exception:  # noqa: BLE001
        log.exception("Время в дороге по карте")
        return 0


def run_checks() -> list[dict]:
    """Ежедневная проверка данных (checks.py); результат — в kv, видно в «Состоянии»."""
    from . import checks
    try:
        items = checks.run(db, events, tz)
    except Exception:  # noqa: BLE001
        log.exception("Проверка данных")
        return []
    db.kv_set("checks:last", {"at": datetime.now(tz).isoformat(timespec="seconds"), "items": items})
    return items


def _synced() -> None:
    ws.reapply()
    events.refresh()     # экраны берут прежнюю ленту, пока новая собирается в фоне


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


def _stem(w: str) -> str:
    """Основа слова без окончания: «йогу» → «йог», «бассейна» → «бассей» — чтобы «перенеси йогу» нашло «Йога»."""
    w = w.lower().strip(".,!?«»\"'")
    return w[:max(3, len(w) - 2)] if len(w) > 4 else w[:3] if len(w) >= 3 else w


def _ops_move(op: dict) -> None:
    """Команда Алисы «перенеси йогу на завтра [в 19:00]»: ищем ближайшее подходящее событие на 3 недели вперёд
    и переносим только его (у серии — только это вхождение), сохраняя время и длительность, если новое не сказано."""
    from .api.writing import EventEdit, update_event
    now = datetime.now(tz)
    text = str(op.get("text", ""))[:300]
    q = quick.parse(text, now.replace(tzinfo=None), db.list_people())
    if not q["date"]:
        raise ValueError("не сказано, на какой день перенести: «%s»" % text)
    stems = [_stem(w) for w in re.findall(r"[а-яёa-z]{3,}", (q["title"] or "").lower()) if w not in ("на", "мою", "мой", "моё", "наш", "нашу")]
    if not stems:
        raise ValueError("не сказано, что перенести: «%s»" % text)
    who = set(q["people"] or [p for p in (op.get("people") or []) if isinstance(p, str)])
    found = []
    for e in events.events(now - timedelta(hours=1), now + timedelta(days=21)):
        if e.get("private") or e.get("duty") or e.get("birthday") or not any(_writable(c) for c in e.get("calendars", [])):
            continue
        words = [_stem(w) for w in re.findall(r"[а-яёa-z]{3,}", e["title"].lower())]
        if not all(any(w.startswith(s) or s.startswith(w) for w in words) for s in stems):
            continue
        if who and not who & set(e.get("owners") or []):
            continue
        found.append(e)
    if not found:
        raise ValueError("не нашла событие «%s» на ближайшие три недели" % q["title"])
    e = min(found, key=lambda x: x["start"])
    old_s, old_e = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
    d = date.fromisoformat(q["date"])
    if e.get("all_day"):
        ns = datetime.combine(d, time(0))
        ne = ns + (old_e - old_s)
    else:
        t = time.fromisoformat(q["start"]) if q["start"] else old_s.timetz().replace(tzinfo=None)
        ns = datetime.combine(d, t, old_s.tzinfo or tz)
        ne = ns + (old_e - old_s)
    cal = next(c for c in e["calendars"] if _writable(c))
    update_event(e["uid"], EventEdit(calendar=cal, start=ns.isoformat(), end=ne.isoformat(), all_day=bool(e.get("all_day")),
                                     occurrence=e["start"] if e.get("recurring") else None, scope="once" if e.get("recurring") else None))


def run_selftest(calendar: str, scheduled: bool = False) -> dict:
    """Проверка записи в живой календарь: создать → перенести → прочитать с сервера → серия с исключением → удалить.
    Идёт мимо локальной базы и журнала (семья ничего не увидит), тестовые события живут секунды."""
    from time import perf_counter
    from . import access, writer
    target = make_target(calendar)
    rid = _remote_id(calendar)
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
    log.info("Самопроверка записи %s: %s", calendar, "успешно" if ok else steps)
    res = {"ok": ok, "steps": steps, "calendar": calendar, "at": datetime.now(tz).isoformat(timespec="seconds"), "scheduled": scheduled}
    prev = (db.kv_get("selftest:last")[0] or {})
    db.kv_set("selftest:last", {k: res[k] for k in ("ok", "at", "calendar", "scheduled")} |
              {"failed": next((x for x in steps if not x["ok"]), None)})
    if scheduled and not ok:
        bad = next((x for x in steps if not x["ok"]), {})
        access.notify(db, "HomeHub: запись в Яндекс не работает",
                      f"Еженедельная проверка не прошла на шаге «{bad.get('name', '')}»: {bad.get('error', '')}. Правки из приложения могут не доходить.", priority="high")
    elif scheduled and ok and prev.get("ok") is False:
        access.notify(db, "HomeHub: запись в Яндекс снова работает", "Еженедельная проверка прошла.", priority="default")
    return res


def selftest_weekly() -> dict | None:
    """Раз в неделю: самопроверка записи в первый пишущий календарь (или выбранный в settings:selftest.calendar)."""
    cfg = db.kv_get("settings:selftest")[0] or {}
    if cfg.get("enabled") is False:
        return None
    cal = cfg.get("calendar")
    if not cal or not _writable(cal):
        cals = [c for c in db.list_calendars() if _writable(c["key"])]
        if not cals:
            return None
        cal = cals[0]["key"]
    return run_selftest(cal, scheduled=True)


def backup_drill() -> dict:
    """Раз в месяц: учебное восстановление свежей копии; результат — на телефон (если включён ntfy) и в журнал."""
    from . import access
    if not cloud._token():
        return {"ok": False, "error": "облако не подключено"}
    res = backup.drill()
    if res.get("ok"):
        text = (f"Копия {res.get('name', '')} разворачивается и читается: людей {res.get('people', 0)}, "
                f"календарей {res.get('calendars', 0)}, записей {res.get('objects', 0)}.")
        access.event(db, "backup", "Учебное восстановление: " + text)
        access.notify(db, "HomeHub: копия в порядке", text, priority="low")
    else:
        text = f"Свежую копию не удалось развернуть: {res.get('error', 'неизвестная ошибка')}. Откройте «Состояние и копии»."
        access.event(db, "backup", "Учебное восстановление: " + text)
        access.notify(db, "HomeHub: копия не читается", text, priority="high")
    return res
