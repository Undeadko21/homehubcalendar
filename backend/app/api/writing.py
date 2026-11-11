"""Запись событий в Яндекс: создать, изменить, удалить, быстрое создание, мастер секций, конфликты, журнал, самопроверка."""
from __future__ import annotations

from time import perf_counter
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from pydantic import BaseModel

from .. import writer, quick
from .. import conflicts
from fastapi import APIRouter

from .. import core

router = APIRouter()


def _journal_ids() -> set[str]:
    return {e["id"] for e in core.ws.journal()}


def _new_changes(before: set[str]) -> list[str]:
    """Записи журнала, появившиеся за этот запрос (в порядке создания) — по ним экран предлагает «Отменить»."""
    return [e["id"] for e in core.ws.journal() if e["id"] not in before]


@router.get("/api/events")
def get_events(start: str, end: str, people: str | None = None):
    s, e = core._parse_dt(start), core._parse_dt(end)
    if e <= s or (e - s) > timedelta(days=400):
        raise HTTPException(400, "Некорректный диапазон")
    items = core.events.visible(core.events.events(s, e))
    if people:
        wanted = set(people.split(","))
        items = [i for i in items if wanted & set(i["people"])]
    return [_trim(i) for i in items]


_MAX_DESC = 4000


def _trim(e: dict) -> dict:
    """Описания из писем-приглашений бывают огромными; в ленте хватает начала."""
    d = e.get("description") or ""
    return {**e, "description": d[:_MAX_DESC] + "…"} if len(d) > _MAX_DESC else e


class EventPeople(BaseModel):
    uid: str
    people: list[str] | None = None  # None — вернуть участников по умолчанию


@router.post("/api/event-people")
def set_event_people(body: EventPeople):
    if body.people is not None:
        known = {p["id"] for p in core.db.list_people()}
        unknown = [p for p in body.people if p not in known]
        if unknown:
            raise HTTPException(400, f"Неизвестные люди: {', '.join(unknown)}")
    core.db.set_event_people(body.uid, body.people)
    core.events.invalidate()
    return {"ok": True}


_HEX = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")


class EventColor(BaseModel):
    uid: str
    color: str | None = None   # None — убрать свой цвет


@router.post("/api/event-color")
def set_event_color(body: EventColor):
    if body.color is not None and not _HEX.match(body.color):
        raise HTTPException(400, "Цвет вида #rrggbb")
    colors, _ = core.db.kv_get("event_colors")
    colors = dict(colors or {})
    if body.color is None:
        colors.pop(body.uid, None)
    else:
        colors[body.uid] = body.color.lower()
    core.db.kv_set("event_colors", colors)
    core.events.invalidate()
    return {"ok": True}


class SharedColor(BaseModel):
    color: str | None = None


@router.put("/api/settings/shared-color")
def put_shared_color(body: SharedColor):
    if body.color is not None and not _HEX.match(body.color):
        raise HTTPException(400, "Цвет вида #rrggbb")
    core.db.kv_set("settings:shared_color", body.color.lower() if body.color else None)
    core.events.invalidate()
    return {"ok": True, "color": body.color}


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


class ConflictIn(BaseModel):
    calendar: str
    title: str = ""
    start: str
    end: str | None = None
    all_day: bool = False
    location: str = ""
    people: list[str] | None = None
    uid: str | None = None


@router.post("/api/conflicts")
def check_conflicts(body: ConflictIn):
    """Что не сходится, если поставить событие сюда (для предупреждения в форме и при переносе)."""
    try:
        items = conflicts.check(core.events, calendar=body.calendar, title=body.title, start=core._parse_dt(body.start),
                                end=core._parse_dt(body.end) if body.end else None, all_day=body.all_day,
                                people=body.people, uid=body.uid, location=body.location)
    except ValueError:
        raise HTTPException(400, "Неверная дата")
    return {"items": items}


class SelfTestIn(BaseModel):
    calendar: str


@router.post("/api/selftest/write")
def selftest_write(body: SelfTestIn):
    """Проверка записи в живой календарь (шаги — в core.run_selftest); результат запоминается для «Состояния»."""
    return core.run_selftest(body.calendar)


@router.post("/api/event")
def create_event(body: EventIn):
    seen = _journal_ids()
    uid, sent = core._create_event(body.calendar, body.title, core._parse_dt(body.start), core._parse_dt(body.end) if body.end else None,
                              body.all_day, body.location, body.description,
                              body.repeat.model_dump() if body.repeat else None, body.people)
    return {"ok": True, "uid": uid, "pending": not sent, "changes": _new_changes(seen)}


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


@router.post("/api/section")
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
    known = {p["id"] for p in core.db.list_people()}
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
            s_ = datetime.combine(first, time.fromisoformat(st), core.tz)
            e_ = datetime.combine(first, time.fromisoformat(en), core.tz)
        except ValueError:
            raise HTTPException(400, "Неверное время")
        if e_ <= s_:
            raise HTTPException(400, "Конец занятия должен быть позже начала")
        rep = {"freq": "weekly", "byday": [writer._DAYS[d] for d in days],
               "until": until.isoformat() if until else None, "count": None if until else body.count}
        uid, sent = core._create_event(body.calendar, body.title.strip(), s_, e_, False, body.location, "", rep, body.people)
        pending = pending or not sent
        for role, who in (("dropoff", drop), ("pickup", pick)):
            if who:
                core.db.set_escort(uid, "*", role, who)
        if travel:
            core.db.set_escort(uid, "*", "travel", str(travel))
        created.append({"uid": uid, "days": days, "start": st, "end": en})
    core._after_write()
    return {"ok": True, "created": created, "pending": pending}


@router.put("/api/event/{uid}")
def update_event(uid: str, body: EventEdit):
    found = core.db.find_object(uid, body.calendar)
    if not found:
        raise HTTPException(404, "Событие не найдено (возможно, оно удалено)")
    cal_key, href, ics = found
    core.make_target(cal_key)
    core._check_people(body.people)
    seen = _journal_ids()
    fields: dict = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.start is not None:
        fields.update(start=core._parse_dt(body.start), end=core._parse_dt(body.end) if body.end else None,
                      all_day=body.all_day, occurrence=core._parse_dt(body.occurrence) if body.occurrence else None)
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
                ics, core._parse_dt(body.occurrence),
                {**fields, "start": core._parse_dt(body.start), "end": core._parse_dt(body.end) if body.end else None,
                 "all_day": body.all_day}, core.tz)
            if res is None:   # первое вхождение — это вся серия
                return None
            old_ics, new_uid, new_ics = res
            ok1 = core.ws.update(cal_key, href, ics, old_ics)
            ok2 = core.ws.create(cal_key, new_ics)
            ppl = body.people if body.people_set else core.db.event_people().get(uid)
            if ppl is not None:
                core.db.set_event_people(new_uid, ppl)
            for (u, occ_, role), person in core.db.escorts().items():   # назначения «на всю серию» переходят в новую серию
                if u == uid and occ_ == "*":
                    core.db.set_escort(new_uid, "*", role, person)
            return ok1 and ok2
        sent = core._run_write(split_following)
        if sent is not None:
            core._after_write()
            return {"ok": True, "pending": not sent, "changes": _new_changes(seen)}
        body.scope = None   # первое вхождение: падаем в обычную правку серии
        fields.pop("occurrence", None)
    if body.scope == "once":
        if not (body.occurrence and body.start):
            raise HTTPException(400, "Не указано, какое вхождение переносить")

        def split():
            series, new_uid, new_ics = writer.split_occurrence(
                ics, core._parse_dt(body.occurrence), core._parse_dt(body.start), core._parse_dt(body.end) if body.end else None,
                body.all_day, core.tz)
            if "title" in fields or "location" in fields or "description" in fields:
                new_ics = writer.apply_edit(new_ics, {k: v for k, v in fields.items() if k in ("title", "location", "description")}, core.tz)
            ok1 = core.ws.update(cal_key, href, ics, series)
            ok2 = core.ws.create(cal_key, new_ics)
            ppl = core.db.event_people().get(uid)
            if ppl is not None:
                core.db.set_event_people(new_uid, ppl)
            return ok1 and ok2
        sent = core._run_write(split)
        core._after_write()
        return {"ok": True, "pending": not sent, "changes": _new_changes(seen)}
    sent = core._run_write(lambda: core.ws.update(cal_key, href, ics, writer.apply_edit(ics, fields, core.tz)))
    if body.people_set:
        core.db.set_event_people(uid, body.people)
    core._after_write()
    return {"ok": True, "pending": not sent, "changes": _new_changes(seen)}


@router.delete("/api/event/{uid}")
def delete_event(uid: str, calendar: str, occurrence: str | None = None):
    """occurrence — время начала вхождения: убрать только его (для серий); иначе удаляется всё событие."""
    found = core.db.find_object(uid, calendar)
    if not found:
        raise HTTPException(404, "Событие не найдено (возможно, оно удалено)")
    cal_key, href, ics = found
    core.make_target(cal_key)
    seen = _journal_ids()

    def go():
        new_ics = writer.add_exdate(ics, core._parse_dt(occurrence), core.tz) if occurrence else None
        if new_ics:
            return core.ws.update(cal_key, href, ics, new_ics)
        sent = core.ws.delete(cal_key, href, ics)
        core.db.set_event_people(uid, None)
        return sent
    sent = core._run_write(go)
    core._after_write()
    return {"ok": True, "pending": not sent, "changes": _new_changes(seen)}


class QuickIn(BaseModel):
    text: str


@router.post("/api/quick")
def quick_parse(body: QuickIn):
    """Разбор фразы вроде «Йога завтра в 18:30 у Оли» в поля формы (ничего не создаёт)."""
    if not body.text.strip():
        raise HTTPException(400, "Пустая фраза")
    now = datetime.now(core.tz).replace(tzinfo=None)
    kind, text = quick.classify(body.text)
    if kind == "event":
        return {"kind": "event", **quick.parse(body.text, now, core.db.list_people())}
    # Покупка или дело: список находим по названию («Покупки», «Дела»), иначе первый/второй по порядку.
    lists = core.db.lists()
    word = "покуп" if kind == "shopping" else "дел"
    target = next((l for l in lists if word in l["name"].lower()), None) or (lists[0 if kind == "shopping" else -1] if lists else None)
    out = {"kind": kind, "list_id": target["id"] if target else None, "list_name": target["name"] if target else None}
    if kind == "shopping":
        return {**out, "items": [x.strip() for x in __import__("re").split(r"\s*(?:,|;|\s+и\s+)\s*", text) if x.strip()][:20]}
    return {**out, **quick.parse_todo(text, now, core.db.list_people())}


@router.get("/api/changes")
def get_changes():
    """Журнал правок (последние первыми) и число ещё не отправленных в Яндекс."""
    items = [{k: v for k, v in e.items() if k not in ("before", "after")} for e in reversed(core.ws.journal())]
    return {"items": items, "pending": core.ws.pending_count(), "error": core.ws.last_error()}


@router.post("/api/changes/{entry_id}/undo")
def undo_change(entry_id: str):
    title = core._run_write(lambda: core.ws.undo(entry_id))
    core._after_write()
    return {"ok": True, "title": title}


@router.post("/api/changes/flush")
def flush_changes():
    return core.ws.flush()
