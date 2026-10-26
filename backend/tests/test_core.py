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
    assert not any(o.recurring for o in occ.values())  # разовые события не «повторяются»
    trip = occ["trip@test"]
    assert trip.all_day and trip.start == "2026-10-30" and trip.end == "2026-11-02"
    assert occ["secret@test"].private
    # «плавающее» время трактуется как местное
    assert occ["secret@test"].start == "2026-10-28T10:00:00+05:00"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.sqlite3")


def _setup(db, objects_by_cal: dict[str, tuple[str | list[str], list[str]]]):
    for key, (person, objs) in objects_by_cal.items():
        owners = [person] if isinstance(person, str) else person
        for pid in owners:
            db.upsert_person({"id": pid, "name": pid})
        db.touch_calendar(key, "s", key, key, {"people": owners})
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
    # CLASS:PRIVATE у события по умолчанию не скрывает детали (Яндекс ставит его почти везде)
    items = EventService(db, TZ).events(*rng())
    assert [i for i in items if i["uid"] == "secret@test"][0]["title"] == "Сюрприз"
    # …но учитывается, если включить privacy.respect_event_class
    items = EventService(db, TZ, respect_event_class=True).events(*rng())
    assert [i for i in items if i["uid"] == "secret@test"][0]["title"] == "Занят"
    # галочка «только занят» у календаря скрывает всё
    db.update_calendar("kid", {"private": True})
    items = EventService(db, TZ).events(*rng())
    assert all(i["title"] == "Занят" and i["description"] == "" for i in items)
    db.update_calendar("kid", {"hidden": True})
    assert EventService(db, TZ).events(*rng()) == []


def test_ui_settings_survive_resync(db):
    db.touch_calendar("s/work", "s", "work", "Работа", {"person": "dad"})
    assert db.get_calendar("s/work")["people"] == ["dad"]
    db.update_calendar("s/work", {"people": ["mom", "dad"]})
    db.touch_calendar("s/work", "s", "work", "Работа", {"person": "dad"})
    assert sorted(db.get_calendar("s/work")["people"]) == ["dad", "mom"]
    db.update_calendar("s/work", {"person_id": "mom"})  # старый формат API
    assert db.get_calendar("s/work")["people"] == ["mom"]


def test_calendar_rules():
    cfg = {"person": "dad", "calendars": [{"match": "семья", "person": "family", "color": "#123456"}]}
    assert calendar_defaults(cfg, "Семья", None)["people"] == ["family"]
    assert calendar_defaults(cfg, "Работа", "#abcdef")["people"] == ["dad"]
    cfg2 = {"calendars": [{"match": "цыган", "people": ["olya", "tolya"]}]}
    assert calendar_defaults(cfg2, "Цыганская семья", None)["people"] == ["olya", "tolya"]
    assert calendar_defaults(cfg, "Работа", "#abcdef")["color"] == "#abcdef"


def test_sync_from_ics_file(db, tmp_path):
    f = tmp_path / "x.ics"
    f.write_text(WEEKLY, encoding="utf-8")
    engine = SyncEngine(db, [{"id": "file", "type": "ics", "url": str(f), "person": "kid"}])
    engine.seed_people([])
    report = engine.run()
    assert report["file"]["ok"]
    assert db.list_calendars()[0]["people"] == ["kid"]
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


def test_ui_credentials_override_empty_config(db):
    engine = SyncEngine(db, [{"id": "yandex", "type": "caldav", "url": "https://caldav.example", "username": "", "password": ""}])
    report = engine.run()
    assert not report["yandex"]["ok"] and "пароль" in report["yandex"]["error"]
    assert engine.accounts()[0]["has_password"] is False
    engine.set_credentials("yandex", " me@yandex.ru ", "secret")
    acc = engine.accounts()[0]
    assert acc == {"id": "yandex", "url": "https://caldav.example", "username": "me@yandex.ru", "has_password": True}
    # пустой пароль при повторном сохранении не стирает прежний
    engine.set_credentials("yandex", "me@yandex.ru", "")
    assert engine.effective_config(engine.sources[0])["password"] == "secret"


def test_multiple_owners_keywords_and_override(db):
    pool = ev("pool@test", "Бассейн Марк", "20261028T180000", "20261028T190000")
    dinner = ev("dinner@test", "Ужин", "20261029T180000", "20261029T190000")
    _setup(db, {"family": (["olya", "tolya"], [pool, dinner])})
    db.upsert_person({"id": "mark", "name": "Марк", "keywords": "марк, садик"})
    svc = EventService(db, TZ)
    by_uid = {i["uid"]: i for i in svc.events(*rng())}
    assert by_uid["dinner@test"]["people"] == ["olya", "tolya"]
    assert by_uid["pool@test"]["people"] == ["olya", "tolya", "mark"]  # слово «марк» в названии
    assert not by_uid["pool@test"]["people_override"]

    # Ручной выбор участников важнее календаря и слов
    db.set_event_people("dinner@test", ["mark", "olya"])
    svc.invalidate()
    by_uid = {i["uid"]: i for i in svc.events(*rng())}
    assert by_uid["dinner@test"]["people"] == ["mark", "olya"] and by_uid["dinner@test"]["people_override"]

    # Скрытый человек убирается, а событие только скрытых людей не показывается
    db.upsert_person({"id": "olya", "name": "olya", "hidden": True})
    db.set_event_people("pool@test", ["olya"])
    svc.invalidate()
    by_uid = {i["uid"]: i for i in svc.events(*rng())}
    assert by_uid["dinner@test"]["people"] == ["mark"]
    assert "pool@test" not in by_uid

    # Сброс возвращает участников по умолчанию
    db.set_event_people("pool@test", None)
    db.upsert_person({"id": "olya", "name": "olya", "hidden": False})
    svc.invalidate()
    by_uid = {i["uid"]: i for i in svc.events(*rng())}
    assert by_uid["pool@test"]["people"] == ["olya", "tolya", "mark"]


def test_migration_from_v1_keeps_owner(tmp_path):
    import sqlite3
    from app.db import MIGRATIONS
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO people (id, name) VALUES ('mark', 'Марк')")
    conn.execute("INSERT INTO calendars (key, source_id, remote_id, name, person_id, configured) "
                 "VALUES ('y/1', 'y', '1', 'Марк', 'mark', 1)")
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.get_calendar("y/1")["people"] == ["mark"]
    assert db.list_people()[0]["keywords"] == ""
