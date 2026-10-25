"""Разбор iCalendar и разворачивание повторяющихся событий в конкретные вхождения.

Повторы (RRULE/RDATE), исключения (EXDATE), перенесённые вхождения
(RECURRENCE-ID) и часовые пояса обрабатывает библиотека
recurring-ical-events — это самая коварная часть календарей, поэтому
своими силами её не пишем.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
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


def expand_ics(ics_text: str, range_start: datetime, range_end: datetime, tz: ZoneInfo) -> list[Occurrence]:
    try:
        cal = icalendar.Calendar.from_ical(ics_text)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось разобрать iCalendar: %s", e)
        return []

    try:
        components = recurring_ical_events.of(cal, components=["VEVENT"]).between(range_start, range_end)
    except Exception as e:  # noqa: BLE001
        log.warning("Ошибка разворачивания повторов: %s", e)
        return []

    out: list[Occurrence] = []
    for comp in components:
        if _text(comp, "STATUS").upper() == "CANCELLED":
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
                recurring=comp.get("RRULE") is not None or comp.get("RECURRENCE-ID") is not None,
                attendees=[str(a).lower().removeprefix("mailto:") for a in attendees],
            )
        )
    return out
