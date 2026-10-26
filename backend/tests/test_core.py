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


def _family(db):
    """Оля и Толя — взрослые, Марк — ребёнок. Бассейн по вт/чт 17:00–18:00."""
    pool = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:test
BEGIN:VEVENT
UID:pool@test
DTSTART:20261027T170000
DTEND:20261027T180000
RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4
SUMMARY:Бассейн
END:VEVENT
END:VCALENDAR
"""
    _setup(db, {
        "mark": ("mark", [pool]),
        "olya": ("olya", [ev("w1@test", "Работа", "20261027T090000", "20261027T164500")]),
        "tolya": ("tolya", [ev("w2@test", "Созвон", "20261029T175000", "20261029T183000")]),
    })
    db.upsert_person({"id": "mark", "name": "Марк", "needs_escort": True})


def _by_start(items, uid):
    return {i["start"][:10]: i for i in items if i["uid"] == uid and not i.get("duty")}


def test_escort_series_once_and_conflicts(db):
    _family(db)
    svc = EventService(db, TZ)
    pools = _by_start(svc.events(*rng()), "pool@test")
    tue = pools["2026-10-27"]
    assert tue["escort"]["children"] == ["mark"]
    assert tue["escort_issue"] == "unassigned"
    # Оля работает до 16:45 — в окно «отвезти» 16:30–17:00 занята, Толя свободен
    assert tue["escort"]["dropoff"]["free"] == ["tolya"]

    # Серия: отвозит Оля, забирает Толя
    db.set_escort("pool@test", "*", "dropoff", "olya")
    db.set_escort("pool@test", "*", "pickup", "tolya")
    svc.invalidate()
    pools = _by_start(svc.events(*rng()), "pool@test")
    tue, thu = pools["2026-10-27"], pools["2026-10-29"]
    assert tue["escort"]["dropoff"]["person"] == "olya" and tue["escort"]["dropoff"]["scope"] == "series"
    assert tue["escort_issue"] == "conflict"
    assert tue["escort"]["dropoff"]["conflicts"][0]["title"] == "Работа"
    # в четверг Толя на созвоне 17:50–18:30, а забирать в 18:00–18:30
    assert thu["escort"]["pickup"]["conflicts"][0]["title"] == "Созвон"

    # Разовая замена на вторник: отвозит Толя → конфликта нет
    db.set_escort("pool@test", tue["start"], "dropoff", "tolya")
    svc.invalidate()
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["dropoff"]["person"] == "tolya" and tue["escort"]["dropoff"]["scope"] == "once"
    assert tue["escort_issue"] is None

    # «Не нужно» снимает роль из проверки
    db.set_escort("pool@test", "*", "pickup", "-")
    svc.invalidate()
    thu = _by_start(svc.events(*rng()), "pool@test")["2026-10-29"]
    assert thu["escort"]["pickup"]["skip"] and thu["escort"]["pickup"]["person"] is None


def test_escort_double_booking(db):
    _family(db)
    db.upsert_person({"id": "liza", "name": "Лиза", "needs_escort": True})
    db.touch_calendar("liza", "s", "liza", "liza", {"people": ["liza"]})
    db.replace_objects("liza", {"0": ev("art@test", "Рисование", "20261027T171500", "20261027T181500")})
    db.set_escort("pool@test", "*", "dropoff", "tolya")
    db.set_escort("art@test", "*", "dropoff", "tolya")
    items = EventService(db, TZ).events(*rng())
    art = [i for i in items if i["uid"] == "art@test" and not i.get("duty")][0]
    assert any(c["kind"] == "escort" for c in art["escort"]["dropoff"]["conflicts"])


def test_free_time(db):
    from datetime import date, time
    from app.freetime import find_free
    _family(db)
    db.set_escort("pool@test", "*", "dropoff", "tolya")
    svc = EventService(db, TZ)
    items = svc.events(datetime(2026, 10, 27, tzinfo=TZ), datetime(2026, 10, 28, tzinfo=TZ))
    day = find_free(items, ["olya", "tolya"], date(2026, 10, 27), date(2026, 10, 28), TZ,
                    time(8), time(22), 60)[0]
    # Оля занята 9:00–16:45, Толя отвозит 16:30–17:00 → свободны 8–9 и 17–22
    assert [(w["start"][11:16], w["end"][11:16]) for w in day["windows"]] == [("08:00", "09:00"), ("17:00", "22:00")]
    assert any(b["title"].startswith("Отвезти") and b["kind"] == "escort" for b in day["busy"])
    work = next(b for b in day["busy"] if b["title"] == "Работа")
    assert work["people"] == ["olya"] and work["event_start"].startswith("2026-10-27T09:00")
    # Только Толя — свободен почти весь день, кроме поездки
    day = find_free(items, ["tolya"], date(2026, 10, 27), date(2026, 10, 28), TZ, time(8), time(22), 60)[0]
    assert [(w["start"][11:16], w["end"][11:16]) for w in day["windows"]] == [("08:00", "16:30"), ("17:00", "22:00")]


def test_escort_modes_auto_and_manual(db):
    _family(db)
    # «Цыганская семья»: Оля + Толя, туда же Марк по слову автопривязки
    db.touch_calendar("fam", "s", "fam", "fam", {"people": ["olya", "tolya"]})
    db.replace_objects("fam", {
        "0": ev("zoo@test", "Зоопарк с Марком", "20261031T110000", "20261031T140000"),
        "1": ev("bday@test", "ДР Марка дома", "20261101T150000", "20261101T180000"),
    })
    db.upsert_person({"id": "mark", "name": "Марк", "needs_escort": True, "keywords": "марк"})
    svc = EventService(db, TZ)
    by_uid = {i["uid"]: i for i in svc.events(*rng())}

    zoo = by_uid["zoo@test"]["escort"]
    assert zoo["mode"] == "together" and zoo["mode_auto"] and "участвует" in zoo["mode_reason"]
    assert zoo["dropoff"]["skip"] and by_uid["zoo@test"]["escort_issue"] is None

    bday = by_uid["bday@test"]["escort"]
    assert bday["mode"] == "home" and "дома" in bday["mode_reason"]

    pool = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert pool["escort"]["mode"] == "escort" and pool["escort_issue"] == "unassigned"

    # Вручную: бассейн во вторник — «все вместе», зоопарк — всё-таки отвозят
    db.set_escort("pool@test", pool["start"], "mode", "together")
    db.set_escort("zoo@test", "*", "mode", "escort")
    svc.invalidate()
    items = svc.events(*rng())
    pools = _by_start(items, "pool@test")
    assert pools["2026-10-27"]["escort"]["mode"] == "together" and not pools["2026-10-27"]["escort"]["mode_auto"]
    assert pools["2026-10-29"]["escort"]["mode"] == "escort"  # разовая замена не задела четверг
    zoo = next(i for i in items if i["uid"] == "zoo@test")
    assert zoo["escort"]["mode"] == "escort" and zoo["escort_issue"] == "unassigned"


def test_home_address_and_whole_words():
    from app.escorts import _home_match
    assert _home_match({"title": "Ужин дома"}, ["дома"], "") is not None
    assert _home_match({"title": "Дом культуры", "location": ""}, ["дома"], "") is None
    assert _home_match({"title": "Гости", "location": "ул. Ленина, 5, кв 3"}, ["дома"], "ленина, 5") is not None


def test_duties_and_together_in_adult_calendars(db):
    _family(db)
    db.set_escort("pool@test", "*", "dropoff", "olya")
    db.set_escort("pool@test", "*", "pickup", "tolya")
    items = EventService(db, TZ).events(*rng())
    duties = [i for i in items if i.get("duty") and i["uid"] == "pool@test" and i["start"].startswith("2026-10-27")]
    by_role = {d["duty"]["role"]: d for d in duties}
    assert by_role["dropoff"]["people"] == ["olya"] and by_role["dropoff"]["title"] == "Отвезти Марка: Бассейн"
    assert by_role["dropoff"]["start"].startswith("2026-10-27T16:30")
    assert by_role["dropoff"]["escort_issue"] == "conflict"  # Оля на работе до 16:45
    assert by_role["pickup"]["people"] == ["tolya"] and by_role["pickup"]["duty"]["parent"]["uid"] == "pool@test"

    # «Все вместе» без взрослых участников — показывается у всех взрослых
    tue = next(i for i in items if i["uid"] == "pool@test" and not i.get("duty") and i["start"].startswith("2026-10-27"))
    db.set_escort("pool@test", tue["start"], "mode", "together")
    items = EventService(db, TZ).events(*rng())
    tue = next(i for i in items if i["uid"] == "pool@test" and not i.get("duty") and i["start"].startswith("2026-10-27"))
    assert set(tue["people"]) == {"mark", "olya", "tolya"}
    assert not [i for i in items if i.get("duty") and i["start"].startswith("2026-10-27")]


def test_accusative():
    from app.escorts import accusative
    assert [accusative(n) for n in ["Марк", "Маша", "Оля", "Толик", "Игорь", "Тимофей", "Mark"]] == \
        ["Марка", "Машу", "Олю", "Толика", "Игоря", "Тимофея", "Mark"]


def test_widget_payload(db):
    from app import widget
    _family(db)
    db.set_escort("pool@test", "*", "dropoff", "olya")
    items = EventService(db, TZ).events(*rng())
    people = {p["id"]: p for p in db.list_people()}
    now = datetime(2026, 10, 27, 16, 50, tzinfo=TZ)
    data = widget.build(items, people, TZ, now, 2)
    today = data["days"][0]
    assert today["label"] == "Сегодня"
    titles = [e["title"] for e in today["events"]]
    assert "Работа" not in titles  # закончилась в 16:45
    pool = next(e for e in today["events"] if e["title"] == "Бассейн")
    assert pool["time"] == "17:00–18:00" and pool["note"].startswith("→ olya") and "← кто?" in pool["note"]
    duty = next(e for e in today["events"] if e["duty"])
    assert duty["now"] and duty["issue"] == "conflict" and duty["note"] == "занят(а): Работа"
    assert data["days"][1]["label"].startswith("Завтра")
    only = widget.build(items, people, TZ, now, 1, {"tolya"})
    assert all("tolya" in e["people"] for e in only["days"][0]["events"])
