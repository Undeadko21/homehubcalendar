from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db import Database
from app.events import EventService
from app.expand import expand_ics
from app.holidays import HolidayService
from app.sync import SyncEngine, calendar_defaults

TZ = ZoneInfo("Asia/Yekaterinburg")

WEEKLY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VTIMEZONE
TZID:Europe/Moscow
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:swim@test
DTSTART;TZID=Europe/Moscow:20261005T150000
DTEND;TZID=Europe/Moscow:20261005T160000
RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=6
EXDATE;TZID=Europe/Moscow:20261019T150000
SUMMARY:Бассейн
END:VEVENT
BEGIN:VEVENT
UID:swim@test
RECURRENCE-ID;TZID=Europe/Moscow:20261026T150000
DTSTART;TZID=Europe/Moscow:20261027T170000
DTEND;TZID=Europe/Moscow:20261027T180000
SUMMARY:Бассейн (перенос)
END:VEVENT
END:VCALENDAR
"""

ALLDAY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:trip@test
DTSTART;VALUE=DATE:20261030
DTEND;VALUE=DATE:20261102
SUMMARY:Поездка
END:VEVENT
BEGIN:VEVENT
UID:secret@test
DTSTART:20261028T100000
DTEND:20261028T110000
CLASS:PRIVATE
SUMMARY:Сюрприз
END:VEVENT
BEGIN:VEVENT
UID:cancel@test
DTSTART:20261028T120000
DTEND:20261028T130000
STATUS:CANCELLED
SUMMARY:Отменено
END:VEVENT
END:VCALENDAR
"""


def ev(uid, summary, start, end):
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:{uid}
DTSTART:{start}
DTEND:{end}
SUMMARY:{summary}
END:VEVENT
END:VCALENDAR
"""


def rng():
    return datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 11, 30, tzinfo=TZ)


def test_recurrence_exdate_and_override():
    occ = expand_ics(WEEKLY, *rng(), TZ)
    starts = sorted(o.start for o in occ)
    # 6 вхождений: 05, 12, (19 исключено), (26 перенесено на 27), 02.11, 09.11
    assert len(occ) == 5
    assert "2026-10-19" not in " ".join(starts)
    moved = [o for o in occ if o.title == "Бассейн (перенос)"]
    assert moved and moved[0].start == "2026-10-27T19:00:00+05:00"  # 17:00 МСК → 19:00 ЕКБ
    assert all(o.recurring for o in occ)


def test_allday_private_cancelled():
    occ = {o.uid: o for o in expand_ics(ALLDAY, *rng(), TZ)}
    assert "cancel@test" not in occ
    trip = occ["trip@test"]
    assert trip.all_day and trip.start == "2026-10-30" and trip.end == "2026-11-02"
    assert occ["secret@test"].private
    # «плавающее» время трактуется как местное
    assert occ["secret@test"].start == "2026-10-28T10:00:00+05:00"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.sqlite3")


def _setup(db, objects_by_cal: dict[str, tuple[str, list[str]]]):
    for key, (person, objs) in objects_by_cal.items():
        db.upsert_person({"id": person, "name": person})
        db.touch_calendar(key, "s", key, key, {"person": person})
        db.replace_objects(key, {str(i): o for i, o in enumerate(objs)})


def test_dedup_exact_and_fuzzy(db):
    shared = ev("meet@test", "Родительское собрание", "20261028T180000", "20261028T190000")
    _setup(db, {
        "mom": ("mom", [shared, ev("a@test", "Ужин у бабушки", "20261029T180000", "20261029T200000")]),
        "dad": ("dad", [shared, ev("b@test", "Ужин  у бабушки!", "20261029T180000", "20261029T200000")]),
    })
    items = EventService(db, TZ).events(*rng())
    assert len(items) == 2
    for i in items:
        assert sorted(i["people"]) == ["dad", "mom"]


def test_private_masked_and_hidden(db):
    _setup(db, {"kid": ("kid", [ALLDAY])})
    items = EventService(db, TZ).events(*rng())
    secret = [i for i in items if i["uid"] == "secret@test"][0]
    assert secret["title"] == "Занят" and secret["description"] == ""
    db.update_calendar("kid", {"hidden": True})
    assert EventService(db, TZ).events(*rng()) == []


def test_ui_settings_survive_resync(db):
    db.touch_calendar("s/work", "s", "work", "Работа", {"person": "dad"})
    db.update_calendar("s/work", {"person_id": "mom"})
    db.touch_calendar("s/work", "s", "work", "Работа", {"person": "dad"})
    assert db.get_calendar("s/work")["person_id"] == "mom"


def test_calendar_rules():
    cfg = {"person": "dad", "calendars": [{"match": "семья", "person": "family", "color": "#123456"}]}
    assert calendar_defaults(cfg, "Семья", None)["person"] == "family"
    assert calendar_defaults(cfg, "Работа", "#abcdef")["person"] == "dad"
    assert calendar_defaults(cfg, "Работа", "#abcdef")["color"] == "#abcdef"


def test_sync_from_ics_file(db, tmp_path):
    f = tmp_path / "x.ics"
    f.write_text(WEEKLY, encoding="utf-8")
    engine = SyncEngine(db, [{"id": "file", "type": "ics", "url": str(f), "person": "kid"}])
    engine.seed_people([])
    report = engine.run()
    assert report["file"]["ok"]
    assert db.list_calendars()[0]["person_id"] == "kid"
    assert len(EventService(db, TZ).events(*rng())) == 5


def test_sync_error_is_reported(db):
    engine = SyncEngine(db, [{"id": "bad", "type": "ics", "url": "/nonexistent.ics"}])
    report = engine.run()
    assert not report["bad"]["ok"]
    assert db.sync_status()[0]["last_error"]


def test_holidays_fixed(db):
    hs = HolidayService(db, {"provider": "fixed"})
    days = {d["date"]: d for d in hs.between(datetime(2026, 11, 1).date(), datetime(2026, 11, 10).date())}
    assert days["2026-11-04"]["name"] == "День народного единства"
