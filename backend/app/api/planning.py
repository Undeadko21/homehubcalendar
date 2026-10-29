"""Чтение календаря и семейные данные: конфиг, события, праздники, люди, поездки, шаблоны, дни рождения, поиск, свободное время."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from pydantic import BaseModel

from .. import __version__
from ..events import UNASSIGNED
from ..freetime import find_free
from .. import birthdays as bd, school, stats, widget
from fastapi import APIRouter

from .. import core

router = APIRouter()


@router.get("/api/config")
def get_config():
    people = core.db.list_people()
    cals = core.db.list_calendars()
    known = {p["id"] for p in people}
    if any(not (set(c["people"]) & known) for c in cals if not c["hidden"]):
        people = people + [{"id": UNASSIGNED, "name": "Без владельца", "color": "#8a94a6",
                            "emoji": "", "sort": 999, "hidden": 0, "keywords": ""}]
    return {
        "title": core.settings.title,
        "timezone": core.settings.timezone,
        "version": __version__,
        "people": people,
        "calendars": [{**c, "writable": core._writable(c["key"])} for c in cals],
        "weather": core.settings.weather,
        "pin_enabled": bool(core.settings.pin),
        "accounts": core.engine.accounts(),
        "escort": core.events.escort_settings(),
        "shared_color": core.events.shared_color(),
    }


@router.get("/api/holidays")
def get_holidays(start: str, end: str):
    a, z = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    return school.merge(core.db, core.holidays.between(a, z), a, z)


class SchoolIn(BaseModel):
    breaks: list[dict]


@router.get("/api/school")
def get_school():
    return {"breaks": school.load(core.db)}


@router.put("/api/school")
def put_school(body: SchoolIn):
    out = school.save(core.db, body.breaks)
    return {"breaks": out}


@router.get("/api/stats")
def get_stats(start: str, end: str):
    s, e = core._parse_dt(start), core._parse_dt(end)
    if e <= s or (e - s) > timedelta(days=400):
        raise HTTPException(400, "Некорректный диапазон")
    people = [p for p in core.db.list_people()]
    return stats.build(core.events.events(s, e), people, s, e)


class PersonIn(BaseModel):
    id: str
    name: str
    color: str = "#6b7280"
    emoji: str = ""
    sort: int = 0
    hidden: bool = False
    keywords: str = ""  # слова автопривязки через запятую
    needs_escort: bool = False  # ребёнок: его отвозят и забирают


@router.get("/api/people")
def list_people():
    return core.db.list_people()


@router.put("/api/people/{person_id}")
def put_person(person_id: str, body: PersonIn):
    if person_id != body.id or person_id == UNASSIGNED:
        raise HTTPException(400, "Некорректный id")
    core.db.upsert_person(body.model_dump())
    core.events.invalidate()
    return {"ok": True}


@router.delete("/api/people/{person_id}")
def delete_person(person_id: str):
    core.db.delete_person(person_id)
    core.events.invalidate()
    return {"ok": True}


class CalendarPatch(BaseModel):
    people: list[str] | None = None
    person_id: str | None = None  # устаревшее: один владелец
    color: str | None = None
    hidden: bool | None = None
    private: bool | None = None


@router.patch("/api/calendars/{key:path}")
def patch_calendar(key: str, body: CalendarPatch):
    if not core.db.get_calendar(key):
        raise HTTPException(404, "Календарь не найден")
    core.db.update_calendar(key, body.model_dump(exclude_unset=True))
    core.events.invalidate()
    return {"ok": True}


class EscortIn(BaseModel):
    uid: str
    occurrence: str | None = None  # время начала вхождения; None — вся серия
    role: str                      # dropoff | pickup | mode
    person: str | None = None      # id взрослого, '-' — не нужно, None — снять назначение;
                                   # для role=mode: escort | together | home | None (автоматически)


@router.post("/api/escort")
def set_escort(body: EscortIn):
    if body.role not in ("dropoff", "pickup", "mode", "travel"):
        raise HTTPException(400, "role: dropoff, pickup, mode или travel")
    if body.role == "travel":
        if body.person is not None and not (body.person.isdigit() and int(body.person) <= 240):
            raise HTTPException(400, "travel: число минут от 0 до 240")
    elif body.role == "mode":
        if body.person not in (None, "escort", "together", "home"):
            raise HTTPException(400, "mode: escort, together или home")
    elif body.person not in (None, "-") and body.person not in {p["id"] for p in core.db.list_people()}:
        raise HTTPException(400, "Неизвестный человек")
    # Разовые замены важнее назначения на серию и при его смене сохраняются.
    core.db.set_escort(body.uid, body.occurrence or "*", body.role, body.person)
    core.events.invalidate()
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


@router.put("/api/settings/escort")
def put_escort_settings(body: EscortSettings):
    if not (0 <= body.before_minutes <= 240 and 0 <= body.after_minutes <= 240
            and 0 <= body.travel_buffer <= 60 and all(0 <= p.minutes <= 240 for p in body.places)):
        raise HTTPException(400, "От 0 до 240 минут")
    core.db.kv_set("settings:escort", {**core.events.escort_settings(), **body.model_dump(exclude_unset=True)})
    core.events.invalidate()
    return {"ok": True}


@router.get("/api/free")
def get_free(people: str, start: str, end: str, day_from: str = "08:00", day_to: str = "22:00",
             min_minutes: int = 60, all_day: bool = False):
    ids = [p for p in people.split(",") if p]
    if not ids:
        raise HTTPException(400, "Выберите хотя бы одного человека")
    d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if d1 <= d0 or (d1 - d0).days > 62:
        raise HTTPException(400, "Период от 1 до 62 дней")
    s = datetime.combine(d0, time(0), core.tz)
    e = datetime.combine(d1, time(0), core.tz)
    return find_free(core.events.events(s, e), ids, d0, d1, core.tz,
                     time.fromisoformat(day_from), time.fromisoformat(day_to), max(15, min_minutes), all_day)


@router.get("/api/widget")
def get_widget(days: int = 2, people: str | None = None):
    """Готовые к показу события для виджета: сегодня (оставшиеся) и следующие дни."""
    days = max(1, min(days, 7))
    now = datetime.now(core.tz)
    start = datetime.combine(now.date(), time(0), core.tz)
    plist = {p["id"]: p for p in core.db.list_people() if not p["hidden"]}
    only = set(people.split(",")) if people else None
    evs = core.events.events(start, start + timedelta(days=days))
    soon = bd.upcoming(core.db.birthdays(), core.events.events(start, start + timedelta(days=15)), start.date(), 14)[:2]
    return widget.build(evs, plist, core.tz, now, days, only, soon)


# ---------- шаблоны поездок по дням недели ----------
class TemplateIn(BaseModel):
    id: int | None = None
    child_id: str
    weekday: int            # 0 — понедельник
    match: str = ""         # слова в названии; пусто — любое событие ребёнка в этот день
    dropoff: str = ""       # id взрослого, '-' — не нужно, '' — не задано
    pickup: str = ""


@router.get("/api/templates")
def list_templates():
    return core.db.templates()


@router.put("/api/templates")
def put_template(body: TemplateIn):
    ids = {p["id"] for p in core.db.list_people()}
    if body.child_id not in ids or not 0 <= body.weekday <= 6:
        raise HTTPException(400, "Некорректный ребёнок или день недели")
    for v in (body.dropoff, body.pickup):
        if v not in ("", "-") and v not in ids:
            raise HTTPException(400, "Неизвестный человек")
    tid = core.db.save_template(body.model_dump())
    core.events.invalidate()
    return {"ok": True, "id": tid}


@router.delete("/api/templates/{tid}")
def delete_template(tid: int):
    core.db.delete_template(tid)
    core.events.invalidate()
    return {"ok": True}


# ---------- дни рождения ----------
class BirthdayIn(BaseModel):
    id: int | None = None
    name: str
    month: int
    day: int
    year: int | None = None


@router.get("/api/birthdays")
def get_birthdays(days: int = 60):
    start = core._today_start()
    evs = core.events.events(start, start + timedelta(days=min(max(days, 1), 120) + 1))
    return {"upcoming": bd.upcoming(core.db.birthdays(), evs, start.date(), min(max(days, 1), 120)),
            "all": core.db.birthdays()}


@router.put("/api/birthdays")
def put_birthday(body: BirthdayIn):
    try:
        date(body.year or 2000, body.month, body.day)
    except ValueError:
        raise HTTPException(400, "Некорректная дата")
    if not body.name.strip():
        raise HTTPException(400, "Укажите имя")
    return {"ok": True, "id": core.db.save_birthday(body.model_dump())}


@router.delete("/api/birthdays/{bid}")
def delete_birthday(bid: int):
    core.db.delete_birthday(bid)
    return {"ok": True}


# ---------- поиск ----------
@router.get("/api/search")
def search(q: str):
    q = q.strip().lower()
    if len(q) < 2:
        return []
    today = core._today_start()
    found = [e for e in core.events.events(today - timedelta(days=60), today + timedelta(days=330))
             if not e.get("duty") and (q in e["title"].lower() or q in (e.get("location") or "").lower()
                                       or q in (e.get("description") or "").lower())]
    found.sort(key=lambda e: e["start"])
    return found[:300]
