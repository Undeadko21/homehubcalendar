"""Разбор iCalendar и разворачивание повторяющихся событий в конкретные вхождения.

Повторы (RRULE/RDATE), исключения (EXDATE), перенесённые вхождения
(RECURRENCE-ID) и часовые пояса обрабатывает библиотека
recurring-ical-events — это самая коварная часть календарей, поэтому
своими силами её не пишем.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import timezone, date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

log = logging.getLogger(__name__)


@dataclass
class Occurrence:
    uid: str
    title: str
    start: str               # ISO: дата (весь день) или дата-время с поясом
    end: str                 # для событий на весь день — исключающая дата, как в iCalendar
    all_day: bool
    location: str = ""
    description: str = ""
    url: str = ""
    private: bool = False
    busy: bool = True        # TRANSP:TRANSPARENT → «свободен»
    tentative: bool = False
    recurring: bool = False
    attendees: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _to_dt(v, tz: ZoneInfo) -> datetime | date:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)  # «плавающее» время — считаем местным
        return v.astimezone(tz)
    return v


def _text(comp, key: str) -> str:
    v = comp.get(key)
    return str(v).strip() if v is not None else ""


# Границы событий по содержимому объекта: разбирать заново ради «этого в сентябре 2024 нет» не нужно.
# Значение — (самое раннее, самое позднее | None, если повторяется бесконечно / неизвестно), с запасом в сутки.
_BOUNDS: dict[tuple[int, int], tuple[datetime, datetime | None]] = {}
_MARGIN = timedelta(days=2)


def _utc(v) -> datetime:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)


def _bounds(cal) -> tuple[datetime, datetime | None]:
    lo: datetime | None = None
    hi: datetime | None = None
    open_end = False
    for c in cal.walk("VEVENT"):
        try:
            start = c.decoded("DTSTART")
        except Exception:  # noqa: BLE001
            return datetime.min.replace(tzinfo=timezone.utc), None
        s = _utc(start)
        lo = s if lo is None else min(lo, s)
        if "RDATE" in c:
            open_end = True
        end = None
        if "DTEND" in c:
            end = c.decoded("DTEND")
        elif "DURATION" in c:
            end = start + c.decoded("DURATION")
        e = _utc(end) if end is not None else s
        rr = c.get("RRULE")
        if rr is not None:
            until = rr.get("UNTIL")
            if until:
                e = max(e, _utc(until[0])) + (e - s)
            else:
                open_end = True
        hi = e if hi is None else max(hi, e)
    if lo is None:
        return datetime.min.replace(tzinfo=timezone.utc), None
    return lo - _MARGIN, (None if open_end else hi + _MARGIN)


# Отменённые встречи: Teams/Outlook пишут «Canceled: …», Битрикс24 и русские клиенты — «Отменено: …».
_CANCELLED_RE = re.compile(r"^\s*(?:canceled|cancelled|отменено|отменена|отменен|отменён)\b\s*[:\-–—]", re.I)


def is_cancelled_title(title: str) -> bool:
    return bool(_CANCELLED_RE.match(title or ""))


def expand_ics(ics_text: str, range_start: datetime, range_end: datetime, tz: ZoneInfo) -> list[Occurrence]:
    key = (len(ics_text), hash(ics_text))
    b = _BOUNDS.get(key)
    if b is not None:
        lo, hi = b
        if range_end.astimezone(timezone.utc) < lo or (hi is not None and range_start.astimezone(timezone.utc) > hi):
            return []
    try:
        cal = icalendar.Calendar.from_ical(ics_text)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось разобрать iCalendar: %s", e)
        return []
    if b is None:
        if len(_BOUNDS) > 60000:
            _BOUNDS.clear()
        try:
            _BOUNDS[key] = _bounds(cal)
        except Exception:  # noqa: BLE001
            _BOUNDS[key] = (datetime.min.replace(tzinfo=timezone.utc), None)

    try:
        components = recurring_ical_events.of(cal, components=["VEVENT"]).between(range_start, range_end)
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка разворачивания повторов: %s", e)
        return []

    # Повторяющиеся — только серии из исходного файла (RRULE/RDATE или перенесённые вхождения).
    # Смотреть на развёрнутые вхождения нельзя: библиотека ставит RECURRENCE-ID каждому.
    recurring_uids = {
        str(c.get("UID"))
        for c in cal.walk("VEVENT")
        if c.get("RRULE") is not None or c.get("RDATE") is not None or c.get("RECURRENCE-ID") is not None
    }

    out: list[Occurrence] = []
    for comp in components:
        if _text(comp, "STATUS").upper() == "CANCELLED" or is_cancelled_title(_text(comp, "SUMMARY")):
            continue
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        start = _to_dt(dtstart.dt, tz)
        dtend = comp.get("DTEND")
        if dtend is not None:
            end = _to_dt(dtend.dt, tz)
        elif comp.get("DURATION") is not None:
            end = start + comp.get("DURATION").dt
        elif isinstance(start, datetime):
            end = start
        else:
            end = start + timedelta(days=1)

        all_day = not isinstance(start, datetime)
        if all_day and isinstance(end, datetime):
            end = end.date()
        if not all_day and not isinstance(end, datetime):
            end = datetime.combine(end, datetime.min.time(), tz)

        attendees = comp.get("ATTENDEE") or []
        if not isinstance(attendees, list):
            attendees = [attendees]

        cls = _text(comp, "CLASS").upper()
        out.append(
            Occurrence(
                uid=_text(comp, "UID") or f"nouid-{hash(_text(comp, 'SUMMARY'))}",
                title=_text(comp, "SUMMARY") or "(без названия)",
                start=start.isoformat(),
                end=end.isoformat(),
                all_day=all_day,
                location=_text(comp, "LOCATION"),
                description=_text(comp, "DESCRIPTION"),
                url=_text(comp, "URL"),
                private=cls in ("PRIVATE", "CONFIDENTIAL"),
                busy=_text(comp, "TRANSP").upper() != "TRANSPARENT",
                tentative=_text(comp, "STATUS").upper() == "TENTATIVE",
                recurring=_text(comp, "UID") in recurring_uids,
                attendees=[str(a).lower().removeprefix("mailto:") for a in attendees],
            )
        )
    return out
