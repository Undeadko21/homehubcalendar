"""Запись событий в CalDAV (Яндекс): создать, изменить, удалить.

Храним и пишем сырые VCALENDAR. Правка повторяющегося события меняет всю серию;
«удалить только это вхождение» делается через EXDATE.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import caldav
from icalendar import Calendar, Event, vDatetime

log = logging.getLogger(__name__)

REPEATS = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}


class WriteError(Exception):
    """Понятная пользователю ошибка записи."""


def _rrule(repeat: dict | None) -> dict | None:
    if not repeat or not repeat.get("freq"):
        return None
    freq = REPEATS.get(repeat["freq"])
    if not freq:
        raise WriteError("Неизвестный повтор")
    r: dict = {"FREQ": [freq]}
    if int(repeat.get("interval") or 1) > 1:
        r["INTERVAL"] = [int(repeat["interval"])]
    byday = [d for d in (repeat.get("byday") or []) if d in _DAYS]
    if byday and freq == "WEEKLY":
        r["BYDAY"] = byday
    if repeat.get("count"):
        r["COUNT"] = [int(repeat["count"])]
    elif repeat.get("until"):
        r["UNTIL"] = [date.fromisoformat(str(repeat["until"])[:10])]
    return r


def _until_utc(rr: dict | None, all_day: bool, tz: ZoneInfo) -> None:
    """RFC 5545: у события со временем UNTIL — дата-время в UTC (конец выбранного дня по местному времени)."""
    if rr and not all_day and rr.get("UNTIL") and isinstance(rr["UNTIL"][0], date) and not isinstance(rr["UNTIL"][0], datetime):
        d = rr["UNTIL"][0]
        rr["UNTIL"] = [datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz).astimezone(ZoneInfo("UTC"))]


def _apply_times(ev: Event, start: datetime, end: datetime | None, all_day: bool, tz: ZoneInfo) -> None:
    for k in ("DTSTART", "DTEND", "DURATION"):
        if k in ev:
            del ev[k]
    if all_day:
        s = start.date()
        e = (end.date() if end else s)
        if e <= s:
            e = s + timedelta(days=1)
        ev.add("DTSTART", s)
        ev.add("DTEND", e)
    else:
        s = start if start.tzinfo else start.replace(tzinfo=tz)
        e = end if end else s + timedelta(hours=1)
        e = e if e.tzinfo else e.replace(tzinfo=tz)
        if e <= s:
            raise WriteError("Конец раньше начала")
        ev.add("DTSTART", s.astimezone(tz))
        ev.add("DTEND", e.astimezone(tz))


def _finish(cal: Calendar) -> str:
    try:
        cal.add_missing_timezones()
    except Exception:  # noqa: BLE001 — без VTIMEZONE Яндекс принимает TZID из Olson
        log.debug("add_missing_timezones failed", exc_info=True)
    return cal.to_ical().decode()


def build_ics(title: str, start: datetime, end: datetime | None, all_day: bool, tz: ZoneInfo,
              location: str = "", description: str = "", repeat: dict | None = None,
              uid: str | None = None) -> tuple[str, str]:
    if not title.strip():
        raise WriteError("Нужно название")
    uid = uid or f"{uuid.uuid4()}@homehub"
    cal = Calendar()
    cal.add("PRODID", "-//HomeHub Calendar//RU")
    cal.add("VERSION", "2.0")
    ev = Event()
    ev.add("UID", uid)
    ev.add("DTSTAMP", datetime.now(ZoneInfo("UTC")))
    ev.add("SUMMARY", title.strip())
    _apply_times(ev, start, end, all_day, tz)
    if location.strip():
        ev.add("LOCATION", location.strip())
    if description.strip():
        ev.add("DESCRIPTION", description.strip())
    rr = _rrule(repeat)
    _until_utc(rr, all_day, tz)
    if rr:
        ev.add("RRULE", rr)
    ev.add("SEQUENCE", 0)
    cal.add_component(ev)
    return uid, _finish(cal)


def _master(cal: Calendar) -> Event:
    for c in cal.walk("VEVENT"):
        if "RECURRENCE-ID" not in c:
            return c
    raise WriteError("В объекте нет основного события")


def apply_edit(ics: str, fields: dict, tz: ZoneInfo) -> str:
    """fields: title, start, end, all_day, location, description, repeat (ключ есть — значит менять)."""
    cal = Calendar.from_ical(ics)
    ev = _master(cal)
    if "title" in fields:
        if not str(fields["title"]).strip():
            raise WriteError("Нужно название")
        ev["SUMMARY"] = str(fields["title"]).strip()
    if "start" in fields:
        start, end = fields["start"], fields.get("end")
        occ = fields.get("occurrence")
        if occ is not None and ("RRULE" in ev or "RDATE" in ev) and "DTSTART" in ev:
            # правим вхождение, а сдвигать надо начало всей серии на ту же разницу
            m0 = ev.decoded("DTSTART")
            if isinstance(m0, datetime):
                m0 = m0.astimezone(tz)
                o = occ if occ.tzinfo else occ.replace(tzinfo=tz)
                s_ = start if start.tzinfo else start.replace(tzinfo=tz)
                e_ = (end if end.tzinfo else end.replace(tzinfo=tz)) if end else s_ + timedelta(hours=1)
                start, end = m0 + (s_ - o), m0 + (s_ - o) + (e_ - s_)
            else:
                d = (start.date() - occ.date())
                dur = (end.date() - start.date()) if end else timedelta(days=1)
                ns = datetime.combine(m0 + d, datetime.min.time())
                start, end = ns, ns + dur
        _apply_times(ev, start, end, bool(fields.get("all_day")), tz)
    for key, prop in (("location", "LOCATION"), ("description", "DESCRIPTION")):
        if key in fields:
            if prop in ev:
                del ev[prop]
            if str(fields[key] or "").strip():
                ev.add(prop, str(fields[key]).strip())
    if "repeat" in fields:
        if "RRULE" in ev:
            del ev["RRULE"]
        rr = _rrule(fields["repeat"])
        _until_utc(rr, not isinstance(ev.decoded("DTSTART"), datetime), tz)
        if rr:
            ev.add("RRULE", rr)
        # переопределения отдельных вхождений теряют смысл при смене правила
        cal.subcomponents = [c for c in cal.subcomponents
                             if not (c.name == "VEVENT" and "RECURRENCE-ID" in c)]
    seq = int(ev.get("SEQUENCE", 0) or 0) + 1
    for k in ("SEQUENCE", "DTSTAMP", "LAST-MODIFIED"):
        if k in ev:
            del ev[k]
    ev.add("SEQUENCE", seq)
    ev.add("DTSTAMP", datetime.now(ZoneInfo("UTC")))
    ev.add("LAST-MODIFIED", datetime.now(ZoneInfo("UTC")))
    return _finish(cal)


def add_exdate(ics: str, occurrence: datetime, tz: ZoneInfo) -> str | None:
    """Убрать одно вхождение серии. None — если вхождений не осталось (нужно удалить объект)."""
    cal = Calendar.from_ical(ics)
    ev = _master(cal)
    if "RRULE" not in ev and "RDATE" not in ev:
        return None
    dtstart = ev.decoded("DTSTART")
    if isinstance(dtstart, datetime):
        occ = occurrence if occurrence.tzinfo else occurrence.replace(tzinfo=tz)
        ev.add("EXDATE", occ.astimezone(dtstart.tzinfo or tz))
    else:
        ev.add("EXDATE", occurrence.date() if isinstance(occurrence, datetime) else occurrence)
    cal.subcomponents = [c for c in cal.subcomponents
                         if not (c.name == "VEVENT" and "RECURRENCE-ID" in c
                                 and _same(c.decoded("RECURRENCE-ID"), occurrence, tz))]
    seq = int(ev.get("SEQUENCE", 0) or 0) + 1
    for k in ("SEQUENCE", "DTSTAMP"):
        if k in ev:
            del ev[k]
    ev.add("SEQUENCE", seq)
    ev.add("DTSTAMP", datetime.now(ZoneInfo("UTC")))
    return _finish(cal)


def _same(rid, occ: datetime, tz: ZoneInfo) -> bool:
    if isinstance(rid, datetime):
        o = occ if occ.tzinfo else occ.replace(tzinfo=tz)
        return rid.astimezone(tz) == o.astimezone(tz)
    return rid == (occ.date() if isinstance(occ, datetime) else occ)


def split_occurrence(ics: str, occurrence: datetime, start: datetime, end: datetime | None, all_day: bool,
                     tz: ZoneInfo) -> tuple[str, str, str]:
    """«Только это»: вхождение убирается из серии (EXDATE) и становится отдельным событием с новым временем.
    Возвращает (ics серии без вхождения, uid нового, ics нового)."""
    series = add_exdate(ics, occurrence, tz)
    if series is None:
        raise WriteError("Событие не повторяется")
    m = _master(Calendar.from_ical(ics))
    uid, new = build_ics(str(m.get("SUMMARY") or "Без названия"), start, end, all_day, tz,
                         str(m.get("LOCATION") or ""), str(m.get("DESCRIPTION") or ""))
    return series, uid, new


_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def split_following(ics: str, occurrence: datetime, fields: dict, tz: ZoneInfo) -> tuple[str, str, str] | None:
    """«Это и следующие»: старая серия обрывается перед вхождением, с него начинается новая серия (новый UID)
    с новым временем/названием. fields — как в apply_edit (start/end/all_day обязательны; title, location,
    description, repeat — по желанию). None — если это первое вхождение (тогда правится вся серия).
    Возвращает (ics старой серии, uid новой, ics новой)."""
    import recurring_ical_events

    cal = Calendar.from_ical(ics)
    ev = _master(cal)
    if "RRULE" not in ev or "DTSTART" not in ev:
        raise WriteError("Событие не повторяется")
    dtstart = ev.decoded("DTSTART")
    timed = isinstance(dtstart, datetime)
    occ = occurrence if (occurrence.tzinfo or not timed) else occurrence.replace(tzinfo=tz)
    first = dtstart.astimezone(tz) if timed else dtstart
    occ_cmp = occ.astimezone(tz) if timed else (occ.date() if isinstance(occ, datetime) else occ)
    if occ_cmp <= first:
        return None
    # Сколько вхождений было до выбранного (нужно, если у серии задан COUNT).
    lo = first if timed else datetime.combine(first, datetime.min.time())
    hi = occ_cmp if timed else datetime.combine(occ_cmp, datetime.min.time())
    before = [c for c in recurring_ical_events.of(cal).between(lo - timedelta(days=1), hi)
              if (c.decoded("DTSTART").astimezone(tz) if isinstance(c.decoded("DTSTART"), datetime)
                  else c.decoded("DTSTART")) < occ_cmp]
    n_before = len(before)

    # --- новая серия: копия исходной с новым UID и временем ---
    new_cal = Calendar.from_ical(ics)
    new_cal.subcomponents = [c for c in new_cal.subcomponents if not (c.name == "VEVENT" and "RECURRENCE-ID" in c)]
    nev = _master(new_cal)
    uid = f"{uuid.uuid4()}@homehub"
    nev["UID"] = uid
    for k in ("EXDATE", "RDATE", "SEQUENCE", "LAST-MODIFIED"):
        if k in nev:
            del nev[k]
    start, end = fields["start"], fields.get("end")
    _apply_times(nev, start, end, bool(fields.get("all_day")), tz)
    rr = dict(nev["RRULE"])
    if rr.get("COUNT"):
        left = int(rr["COUNT"][0]) - n_before
        if left < 1:
            return None
        rr["COUNT"] = [left]
    delta = (start.date() - occ_cmp.date()).days if hasattr(occ_cmp, "date") else (start.date() - occ_cmp).days
    if rr.get("FREQ") == ["WEEKLY"] and rr.get("BYDAY") and delta:
        try:
            rr["BYDAY"] = [_DAYS[(_DAYS.index(d) + delta) % 7] for d in rr["BYDAY"]]
        except ValueError:
            pass
    del nev["RRULE"]
    nev.add("RRULE", rr)
    nev.add("SEQUENCE", 0)
    nev.add("DTSTAMP", datetime.now(ZoneInfo("UTC")))
    new_ics = _finish(new_cal)
    extra = {k: v for k, v in fields.items() if k in ("title", "location", "description", "repeat")}
    if extra:
        new_ics = apply_edit(new_ics, extra, tz)

    # --- старая серия: обрываем перед вхождением ---
    old = _master(cal)
    r_old = dict(old["RRULE"])
    r_old.pop("COUNT", None)
    r_old.pop("UNTIL", None)
    if timed:
        r_old["UNTIL"] = [(occ_cmp - timedelta(seconds=1)).astimezone(ZoneInfo("UTC"))]
    else:
        r_old["UNTIL"] = [occ_cmp - timedelta(days=1)]
    del old["RRULE"]
    old.add("RRULE", r_old)
    cal.subcomponents = [c for c in cal.subcomponents
                         if not (c.name == "VEVENT" and "RECURRENCE-ID" in c
                                 and _rid_cmp(c.decoded("RECURRENCE-ID"), tz) >= occ_cmp)]
    seq = int(old.get("SEQUENCE", 0) or 0) + 1
    for k in ("SEQUENCE", "DTSTAMP"):
        if k in old:
            del old[k]
    old.add("SEQUENCE", seq)
    old.add("DTSTAMP", datetime.now(ZoneInfo("UTC")))
    return _finish(cal), uid, new_ics


def _rid_cmp(rid, tz: ZoneInfo):
    return rid.astimezone(tz) if isinstance(rid, datetime) else rid


def title_of(ics: str) -> str:
    return str(_master(Calendar.from_ical(ics)).get("SUMMARY") or "Без названия")


def uid_of(ics: str) -> str:
    return str(_master(Calendar.from_ical(ics)).get("UID"))


# ---------- ввод-вывод ----------
class CalDavTarget:
    """Тонкая обёртка над caldav: тесты подменяют её своей."""

    def __init__(self, url: str, username: str, password: str):
        self.url, self.username, self.password = url, username, password

    def _calendar(self, client, remote_id: str):
        for cal in client.principal().calendars():
            if str(cal.url).rstrip("/").rsplit("/", 1)[-1] == remote_id:
                return cal
        raise WriteError("Календарь не найден на сервере")

    def _client(self):
        return caldav.DAVClient(url=self.url, username=self.username, password=self.password, timeout=30)

    def create(self, remote_id: str, ics: str) -> str:
        with self._client() as client:
            ev = self._calendar(client, remote_id).save_event(ics)
            return str(ev.url)

    def update(self, remote_id: str, href: str, ics: str) -> None:
        with self._client() as client:
            cal = self._calendar(client, remote_id)
            ev = cal.event_by_url(href)
            ev.data = ics
            ev.save()

    def delete(self, remote_id: str, href: str) -> None:
        with self._client() as client:
            self._calendar(client, remote_id).event_by_url(href).delete()


def friendly(e: Exception) -> str:
    if isinstance(e, WriteError):
        return str(e)
    s = str(e)
    if "403" in s or "Forbidden" in s:
        return "Яндекс не разрешил запись в этот календарь (возможно, он только для чтения)"
    if "401" in s or "Unauthorized" in s:
        return "Неверный логин или пароль приложения"
    return f"Не удалось записать в Яндекс: {s[:200]}"
