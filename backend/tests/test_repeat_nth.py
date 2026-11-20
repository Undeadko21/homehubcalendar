"""Повтор «N-й день недели месяца» и «каждые 2 недели» (v0.21)."""
from datetime import date, datetime, timedelta

import pytest

from app import quick, writer


def _all(api, days=150):
    t = api.core._today_start()
    r = api.get("/api/events", params={"start": t.isoformat(), "end": (t + timedelta(days=days)).isoformat()}).json()
    return r["events"] if isinstance(r, dict) else r


def _starts(api, title):
    return sorted(datetime.fromisoformat(e["start"]).date() for e in _all(api) if e["title"] == title)


def _first(api, wd, nth):
    """Ближайший N-й (или последний) день недели wd с завтрашнего дня."""
    return quick._next_nth(api.core._today_start().date() + timedelta(days=1), wd, nth)


@pytest.mark.parametrize("nth,code,wd", [(2, "TU", 1), (-1, "FR", 4), (1, "MO", 0)])
def test_monthly_nth_weekday(api, nth, code, wd):
    s = _first(api, wd, nth)
    title = f"Собрание {nth}{code}"
    r = api.post("/api/event", json={"calendar": "ya/home", "title": title, "start": f"{s}T18:00:00", "end": f"{s}T19:00:00",
                                     "repeat": {"freq": "monthly", "nth": nth, "byday": [code]}})
    assert r.status_code == 200, r.text
    got = _starts(api, title)
    assert len(got) >= 3
    for d in got:
        assert d.weekday() == wd
        if nth == -1:
            assert (d + timedelta(days=7)).month != d.month          # последний в месяце
        else:
            assert (d.day - 1) // 7 + 1 == nth
    assert len({(d.year, d.month) for d in got}) == len(got)         # по одному в месяц


def test_biweekly(api):
    s = api.core._today_start().date() + timedelta(days=2)
    api.post("/api/event", json={"calendar": "ya/home", "title": "Через неделю", "start": f"{s}T10:00:00", "end": f"{s}T11:00:00",
                                 "repeat": {"freq": "weekly", "interval": 2}})
    got = _starts(api, "Через неделю")[:4]
    assert [(b - a).days for a, b in zip(got, got[1:])] == [14, 14, 14]


def test_rrule_validation():
    assert writer._rrule({"freq": "monthly", "nth": 2, "byday": ["TU"]})["BYDAY"] == ["2TU"]
    assert writer._rrule({"freq": "monthly", "nth": -1, "byday": ["FR"]})["BYDAY"] == ["-1FR"]
    with pytest.raises(writer.WriteError):
        writer._rrule({"freq": "monthly", "nth": 7, "byday": ["TU"]})
    with pytest.raises(writer.WriteError):
        writer._rrule({"freq": "monthly", "nth": 2, "byday": ["TU", "WE"]})
    assert writer.nth_of(date(2026, 11, 17)) == "3TU" and writer.nth_of(date(2026, 11, 27), last=True) == "-1FR"
    assert writer._nth_byday(datetime(2026, 12, 3, 18), "2TU") == "1TH"     # перенос «это и следующие» на 3 декабря
    assert writer._nth_byday(datetime(2026, 12, 31, 18), "-1FR") == "-1TH"


def test_quick_phrases():
    now = datetime(2026, 11, 20, 10)
    r = quick.parse("Родительское собрание каждый второй вторник в 18:00", now, [])
    assert r["repeat"] == {"freq": "monthly", "nth": 2, "byday": ["TU"]} and r["date"] == "2026-12-08" and r["start"] == "18:00"
    r = quick.parse("ЖКХ каждую последнюю пятницу месяца", now, [])
    assert r["repeat"]["nth"] == -1 and r["date"] == "2026-11-27"
    r = quick.parse("Клуб каждый 1-й понедельник", now, [])
    assert r["repeat"]["nth"] == 1 and r["date"] == "2026-12-07"
    assert quick.parse("Бассейн по вторникам", now, [])["repeat"] == {"freq": "weekly"}   # старое не сломано


def _ics(rrule, start="20261208T180000"):
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:s1", f"DTSTART;TZID=Asia/Yekaterinburg:{start}",
                        "DTEND;TZID=Asia/Yekaterinburg:" + start[:9] + "190000", "SUMMARY:x", f"RRULE:{rrule}", "END:VEVENT",
                        "END:VCALENDAR"]) + "\r\n"


def _rr(ics):
    from icalendar import Calendar
    ev = next(c for c in Calendar.from_ical(ics).walk("VEVENT"))
    return {k: [str(x) for x in v] for k, v in dict(ev["RRULE"]).items()}


def test_move_whole_series_recomputes_byday():
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Yekaterinburg")
    # 2-й вторник (8 дек) → вся серия на среду 9 дек: «2-я среда»
    out = writer.apply_edit(_ics("FREQ=MONTHLY;BYDAY=2TU"), {"start": datetime(2026, 12, 9, 18, tzinfo=tz),
                                                            "end": datetime(2026, 12, 9, 19, tzinfo=tz)}, tz)
    assert _rr(out)["BYDAY"] == ["2WE"]
    # еженедельно по вторникам → на среду
    out = writer.apply_edit(_ics("FREQ=WEEKLY;BYDAY=TU"), {"start": datetime(2026, 12, 9, 18, tzinfo=tz),
                                                          "end": datetime(2026, 12, 9, 19, tzinfo=tz)}, tz)
    assert _rr(out)["BYDAY"] == ["WE"]
    # несколько дней / BYSETPOS — не трогаем
    out = writer.apply_edit(_ics("FREQ=MONTHLY;BYDAY=2TU,4TU"), {"start": datetime(2026, 12, 9, 18, tzinfo=tz),
                                                                "end": datetime(2026, 12, 9, 19, tzinfo=tz)}, tz)
    assert _rr(out)["BYDAY"] == ["2TU", "4TU"]
    # только время сдвинули — правило то же
    out = writer.apply_edit(_ics("FREQ=MONTHLY;BYDAY=2TU"), {"start": datetime(2026, 12, 8, 19, tzinfo=tz),
                                                            "end": datetime(2026, 12, 8, 20, tzinfo=tz)}, tz)
    assert _rr(out)["BYDAY"] == ["2TU"]
