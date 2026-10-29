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


def test_travel_time_changes_windows_and_conflicts(db):
    _family(db)
    svc = EventService(db, TZ)
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["travel"]["minutes"] is None
    assert tue["escort"]["dropoff"]["window"][0].startswith("2026-10-27T16:30")  # по умолчанию 30 минут

    # Правило по месту: «бассейн» — 25 минут в пути + запас 5 → окно 30 минут (то же), 40 → 16:15
    db.kv_set("settings:escort", {"places": [{"words": "бассейн", "minutes": 40}], "travel_buffer": 5})
    svc.invalidate()
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["travel"] == {"minutes": 40, "source": "place", "buffer": 5}
    assert tue["escort"]["dropoff"]["window"][0].startswith("2026-10-27T16:15")
    assert tue["escort"]["pickup"]["window"][1].startswith("2026-10-27T18:45")

    # Дорога конкретного события важнее правила по месту; на серию и на день
    db.set_escort("pool@test", "*", "travel", "10")
    svc.invalidate()
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["travel"]["source"] == "series" and tue["escort"]["dropoff"]["window"][0].startswith("2026-10-27T16:45")
    db.set_escort("pool@test", tue["start"], "travel", "0")
    svc.invalidate()
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["travel"]["source"] == "once" and tue["escort"]["dropoff"]["window"][0].startswith("2026-10-27T16:55")


def test_weekday_templates_are_defaults(db):
    _family(db)
    db.save_template({"child_id": "mark", "weekday": 1, "match": "", "dropoff": "tolya", "pickup": "olya"})
    db.save_template({"child_id": "mark", "weekday": 1, "match": "бассейн", "dropoff": "olya"})  # конкретнее
    svc = EventService(db, TZ)
    pools = _by_start(svc.events(*rng()), "pool@test")
    tue, thu = pools["2026-10-27"], pools["2026-10-29"]
    d = tue["escort"]["dropoff"]
    assert d["person"] == "olya" and d["scope"] == "template"      # шаблон со словом победил общий
    assert tue["escort"]["pickup"]["person"] == "olya"             # из общего шаблона
    assert thu["escort"]["dropoff"]["person"] is None              # четверг — шаблона нет
    # Разовая замена важнее шаблона, серия — тоже
    db.set_escort("pool@test", tue["start"], "dropoff", "tolya")
    db.set_escort("pool@test", "*", "pickup", "-")
    svc.invalidate()
    tue = _by_start(svc.events(*rng()), "pool@test")["2026-10-27"]
    assert tue["escort"]["dropoff"]["person"] == "tolya" and tue["escort"]["dropoff"]["scope"] == "once"
    assert tue["escort"]["pickup"]["skip"]


def test_birthdays_and_reminders(db):
    from datetime import date
    from app.birthdays import days_phrase, next_date, upcoming
    from app import reminders
    assert next_date(2, 29, date(2027, 1, 1)) == date(2027, 2, 28)
    assert next_date(10, 20, date(2026, 10, 27)) == date(2027, 10, 20)
    assert [days_phrase(n) for n in (0, 1, 2, 5, 11, 21)] == [
        "сегодня", "завтра", "через 2 дня", "через 5 дней", "через 11 дней", "через 21 день"]
    today = date(2026, 10, 27)
    manual = [{"id": 1, "name": "Оля", "month": 10, "day": 28, "year": 1990}]
    allday = [{"all_day": True, "title": "День рождения Бабушки", "start": "2026-11-02", "end": "2026-11-03"},
              {"all_day": True, "title": "День рождения Оли", "start": "2026-10-28", "end": "2026-10-29"},  # дубль ручной
              {"all_day": True, "title": "Отпуск", "start": "2026-10-30", "end": "2026-10-31"}]
    up = upcoming(manual, allday, today)
    assert [(b["name"], b["days"], b["turns"], b["auto"]) for b in up] == [("Оля", 1, 36, False), ("День рождения Бабушки", 6, None, True)]

    # напоминания: поездка завтра утром + дайджест проблем + день рождения
    _family(db)
    db.set_escort("pool@test", "*", "dropoff", "tolya")
    svc = EventService(db, TZ)
    evs = svc.events(datetime(2026, 10, 27, tzinfo=TZ), datetime(2026, 10, 31, tzinfo=TZ))
    now = datetime(2026, 10, 26, 12, 0, tzinfo=TZ)
    items = reminders.build(evs, [{"id": 1, "name": "Оля", "month": 10, "day": 27, "year": None}], now, TZ, {"tolya"}, 30)
    kinds = {r["kind"] for r in items}
    assert {"duty", "digest", "bday"} <= kinds
    duty = [r for r in items if r["kind"] == "duty"][0]
    assert duty["at"].startswith("2026-10-27T16:00") and "Отвезти Марка" in duty["title"]
    assert "Нет водителя" in [r for r in items if r["kind"] == "digest"][0]["text"]  # забирать некому
    # чужие поездки не попадают
    assert not [r for r in reminders.build(evs, [], now, TZ, {"olya"}, 30) if r["kind"] == "duty"]


def test_lists(db):
    lid = db.lists()[0]["id"]
    a = db.add_item(lid, " Молоко ")
    b = db.add_item(lid, "Хлеб", "olya")
    db.update_item(a, {"done": True})
    items = db.lists()[0]["items"]
    assert [i["text"] for i in items] == ["Хлеб", "Молоко"]  # выполненные внизу
    assert items[1]["done"] and items[1]["done_at"]
    db.clear_done(lid)
    assert [i["text"] for i in db.lists()[0]["items"]] == ["Хлеб"]
    db.delete_item(b)
    assert db.lists()[0]["items"] == []


def test_cloud_snapshot_roundtrip_and_throttle(db):
    import json
    import httpx
    from app import snapshot
    from app.cloud import CloudError, CloudSync, YandexDisk, decrypt

    _family(db)
    svc = EventService(db, TZ)
    snap = snapshot.build(svc, db, TZ, datetime(2026, 10, 27, 12, 0, tzinfo=TZ))
    assert snap["v"] == 2 and snap["widget"]["days"] and any(r["kind"] == "duty" for r in snap["reminders"]) is False  # поездки не назначены
    db.set_escort("pool@test", "*", "dropoff", "tolya")
    svc.invalidate()
    snap = snapshot.build(svc, db, TZ, datetime(2026, 10, 27, 12, 0, tzinfo=TZ))
    duty = [r for r in snap["reminders"] if r["kind"] == "duty"][0]
    assert "at" not in duty and duty["people"] == ["tolya"] and duty["start"].startswith("2026-10-27T16:30")

    uploads, published = [], {"on": False}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        assert req.headers.get("authorization") in ("OAuth y0_testtoken_0123456789abcdef", None)
        if path.endswith("/resources/upload"):
            return httpx.Response(200, json={"href": "https://up.example/f"})
        if req.url.host == "up.example":
            uploads.append(req.content)
            return httpx.Response(201)
        if path.endswith("/resources/publish"):
            published["on"] = True
            return httpx.Response(200, json={"href": "x"})
        if path.endswith("/resources"):
            return httpx.Response(200, json={"public_url": "https://yadi.sk/d/abc"} if published["on"] else {})
        return httpx.Response(404)

    mk = lambda token: YandexDisk(token, httpx.Client(transport=httpx.MockTransport(handler)))
    cloud = CloudSync(db, lambda: snapshot.build(svc, db, TZ, datetime(2026, 10, 27, 12, 0, tzinfo=TZ)), mk)
    assert cloud.tick()["configured"] is False and not uploads
    cloud.set_token("y0_testtoken_0123456789abcdef")
    st = cloud.tick()
    assert st["last_error"] is None and st["code"].startswith("hhc1.") and len(uploads) == 1
    # расшифровывается ключом из кода подключения и совпадает со снимком
    import base64
    payload = json.loads(base64.urlsafe_b64decode(st["code"][5:] + "=="))
    key = base64.urlsafe_b64decode(payload["k"] + "==")
    assert payload["u"] == "https://yadi.sk/d/abc"
    assert json.loads(decrypt(key, uploads[0]))["v"] == 2
    # без изменений повторно не загружаем, при изменении — загружаем
    cloud.tick()
    assert len(uploads) == 1
    db.set_escort("pool@test", "*", "pickup", "olya")
    svc.invalidate()
    cloud.tick()
    assert len(uploads) == 2
    # истёкший токен — понятная ошибка, прежняя ссылка остаётся
    bad = CloudSync(db, cloud.build_snapshot, lambda t: YandexDisk(t, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))))
    db.set_escort("pool@test", "*", "dropoff", "olya")
    svc.invalidate()
    assert "истёк" in bad.tick()["last_error"] and bad.status()["code"]


def test_ops_from_phone_are_applied_once(db):
    import json
    import httpx
    from app import ops, snapshot
    from app.cloud import CloudSync, YandexDisk, encrypt

    _family(db)
    lid = db.lists()[0]["id"]
    item = db.add_item(lid, "Хлеб")
    batch = [
        {"id": "p1-2", "t": 2, "type": "escort", "uid": "pool@test", "occurrence": None, "role": "pickup", "person": "olya"},
        {"id": "p1-1", "t": 1, "type": "escort", "uid": "pool@test", "occurrence": None, "role": "dropoff", "person": "tolya"},
        {"id": "p1-3", "t": 3, "type": "item_add", "list_id": lid, "text": "Молоко"},
        {"id": "p1-4", "t": 4, "type": "item_done", "item_id": item, "done": True},
        {"id": "p1-5", "t": 5, "type": "escort", "uid": "pool@test", "role": "dropoff", "person": "nobody"},  # некорректная
        {"id": "p1-6", "t": 6, "type": "escort", "uid": "pool@test", "occurrence": None, "role": "travel", "person": "15"},
    ]
    assert sorted(ops.apply(db, batch)) == sorted(o["id"] for o in batch)
    assert ops.apply(db, batch) == []  # повторно ничего
    e = db.escorts()
    assert e[("pool@test", "*", "dropoff")] == "tolya" and e[("pool@test", "*", "pickup")] == "olya"
    assert e[("pool@test", "*", "travel")] == "15"
    assert ("pool@test", "*", "dropoff") in e and e[("pool@test", "*", "dropoff")] != "nobody"
    texts = {i["text"]: i["done"] for i in db.lists()[0]["items"]}
    assert texts == {"Молоко": False, "Хлеб": True}

    svc = EventService(db, TZ)
    snap = snapshot.build(svc, db, TZ, datetime(2026, 10, 27, 12, 0, tzinfo=TZ))
    assert "p1-3" in snap["applied"] and snap["people"] and snap["lists"][0]["items"]
    pool = [x for x in snap["events"] if x["uid"] == "pool@test" and not x.get("duty")][0]
    assert pool["escort"]["dropoff"]["person"] == "tolya"
    duty = [x for x in snap["events"] if x.get("duty")][0]
    assert set(duty["duty"]) == {"role", "parent"} and isinstance(duty["duty"]["parent"], str)

    # через облако: файл ops-*.bin с телефона скачивается, применяется один раз, снимок помечает как применённое
    cloud_state = {"files": {}}

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/resources/download"):
            return httpx.Response(200, json={"href": "https://dl.example/ops"})
        if req.url.host == "dl.example":
            return httpx.Response(200, content=cloud_state["files"]["ops-phone1.bin"])
        if path.endswith("/resources") and req.url.params.get("path") == "app:/":
            items = [{"name": n, "md5": str(hash(b))} for n, b in cloud_state["files"].items()]
            return httpx.Response(200, json={"_embedded": {"items": items}})
        return httpx.Response(404)

    cloud = CloudSync(db, lambda: {}, lambda t: YandexDisk(t, httpx.Client(transport=httpx.MockTransport(handler))))
    cloud.set_token("y0_testtoken_0123456789abcdef")
    db.kv_set("cloud:state", {"public_url": "https://yadi.sk/d/x"})
    cloud_state["files"]["ops-phone1.bin"] = encrypt(cloud.key(), json.dumps(
        [{"id": "ph-1", "t": 1, "type": "item_add", "list_id": lid, "text": "Сыр"}]).encode())
    calls = []
    assert cloud.poll_ops(lambda items: calls.append(items) or ops.apply(db, items)) is True
    assert cloud.poll_ops(lambda items: calls.append(items) or ops.apply(db, items)) is False  # файл не менялся
    assert len(calls) == 1 and "Сыр" in [i["text"] for i in db.lists()[0]["items"]]


def test_bad_cloud_token_is_rejected(tmp_path):
    from app.cloud import CloudError
    from app.db import Database
    db = Database(tmp_path / "t.sqlite3")
    from app.cloud import CloudSync
    c = CloudSync(db, lambda: {}, lambda t: None)
    for bad in ("Облако: связь вне дома", "короткий", "has space in token 0123456789"):
        try:
            c.set_token(bad)
            raise AssertionError("принят: " + bad)
        except CloudError:
            pass


def test_backup_roundtrip_and_rotation(tmp_path):
    import sqlite3
    from app import backup as bk
    from app.cloud import CloudSync

    db = Database(tmp_path / "t.sqlite3")
    db.kv_set("marker", {"x": 1})

    class FakeDisk:
        files: dict = {}

        def __init__(self, token):
            pass

        def mkdir(self, p):
            pass

        def upload(self, data, path):
            FakeDisk.files[path.rsplit("/", 1)[1]] = data

        def ls(self, p):
            return [{"name": n} for n in FakeDisk.files]

        def rm(self, path):
            FakeDisk.files.pop(path.rsplit("/", 1)[1], None)

    c = CloudSync(db, lambda: {}, FakeDisk)
    c.set_token("y0_testtoken_0123456789abcdef")
    svc = bk.BackupService(db, c, TZ, FakeDisk)
    assert svc.run()["last_error"] is None
    (name, blob), = FakeDisk.files.items()
    out = tmp_path / "restored.db"
    out.write_bytes(bk.unseal(c.key(), blob))
    assert sqlite3.connect(out).execute("SELECT value FROM kv WHERE key='marker'").fetchone()[0] == '{"x": 1}'
    # старые копии удаляются
    for i in range(20):
        FakeDisk.files[f"homehub-2020010{i:02d}-0330{bk.SUFFIX}"] = b"x"
    svc.run()
    assert len(FakeDisk.files) <= bk.KEEP


def test_school_breaks_merge_with_holidays(db):
    from datetime import date
    from app import school
    school.save(db, [{"name": "Осенние каникулы", "from": "2026-10-26", "to": "2026-11-03"}, {"name": "x", "from": "bad", "to": "2026-01-01"}])
    assert len(school.load(db)) == 1
    h = HolidayService(db, {"provider": "fixed"})
    out = {d["date"]: d for d in school.merge(db, h.between(date(2026, 10, 25), date(2026, 11, 6)), date(2026, 10, 25), date(2026, 11, 6))}
    assert out["2026-10-27"]["type"] == "vacation"
    assert out["2026-11-04"]["type"] == "holiday" and "vacation" not in out["2026-11-04"]
    assert out["2026-11-03"]["vacation"] == "Осенние каникулы"
    assert "2026-10-25" not in out or out["2026-10-25"].get("vacation") is None


def test_stats_counts_events_and_trips():
    from app import stats
    people = [{"id": "a", "name": "Оля", "color": "#f00"}, {"id": "b", "name": "Толя", "color": "#00f"}]
    evs = [
        {"id": "1", "title": "Йога", "start": "2026-10-26T19:00:00+05:00", "end": "2026-10-26T20:00:00+05:00", "all_day": False, "people": ["a"]},
        {"id": "2", "title": "Йога", "start": "2026-10-28T19:00:00+05:00", "end": "2026-10-28T20:30:00+05:00", "all_day": False, "people": ["a", "b"]},
        {"id": "2:dropoff", "title": "Отвезти", "start": "2026-10-28T18:00:00+05:00", "end": "2026-10-28T19:00:00+05:00",
         "all_day": False, "people": ["b"], "duty": {"role": "dropoff", "parent": {"id": "2"}}},
        {"id": "3", "title": "Праздник", "start": "2026-10-27", "end": "2026-10-28", "all_day": True, "people": ["a"]},
    ]
    r = stats.build(evs, people, datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 11, 1, tzinfo=TZ))
    assert r["events"] == 2 and r["hours"] == 2.5 and r["trips"] == 1
    a, b = r["people"][0], r["people"][1]
    assert (a["name"], a["events"], a["minutes"]) == ("Оля", 2, 150)
    assert b["events"] == 1 and b["dropoff"] == 1
    assert r["top_titles"] == [{"title": "Йога", "count": 2}]
    assert r["busiest_day"]["events"] == 1


# ---------- запись событий ----------
def _occ(ics, a="2026-11-01", b="2027-03-01"):
    return expand_ics(ics, datetime.fromisoformat(a).replace(tzinfo=TZ), datetime.fromisoformat(b).replace(tzinfo=TZ), TZ)


def test_writer_build_edit_exdate_roundtrip():
    from app import writer

    uid, ics = writer.build_ics("Йога", datetime(2026, 11, 2, 18, 0), datetime(2026, 11, 2, 19, 0), False, TZ,
                                location="Зал", repeat={"freq": "weekly", "count": 4})
    occ = _occ(ics)
    assert len(occ) == 4 and occ[0].start == "2026-11-02T18:00:00+05:00" and occ[0].title == "Йога"

    ics2 = writer.apply_edit(ics, {"title": "Йога+", "start": datetime(2026, 11, 2, 19, 0),
                                   "end": datetime(2026, 11, 2, 20, 0), "all_day": False, "location": ""}, TZ)
    occ = _occ(ics2)
    assert len(occ) == 4 and occ[0].title == "Йога+" and occ[0].start == "2026-11-02T19:00:00+05:00"
    assert "SEQUENCE:1" in ics2

    ics3 = writer.add_exdate(ics2, datetime(2026, 11, 9, 19, 0), TZ)
    assert len(_occ(ics3)) == 3
    # убрали повтор — одно событие
    ics4 = writer.apply_edit(ics3, {"repeat": None}, TZ)
    assert len(_occ(ics4)) == 1
    # не повторяющееся: exdate = удалить объект целиком
    _, single = writer.build_ics("Раз", datetime(2026, 11, 3, 10), None, False, TZ)
    assert writer.add_exdate(single, datetime(2026, 11, 3, 10), TZ) is None


def test_writer_all_day_and_validation():
    from app import writer

    _, ics = writer.build_ics("Каникулы", datetime(2026, 11, 5), datetime(2026, 11, 5), True, TZ)
    assert "DTSTART;VALUE=DATE:20261105" in ics and "DTEND;VALUE=DATE:20261106" in ics
    with pytest.raises(writer.WriteError):
        writer.build_ics(" ", datetime(2026, 11, 5), None, False, TZ)
    with pytest.raises(writer.WriteError):
        writer.build_ics("X", datetime(2026, 11, 5, 10), datetime(2026, 11, 5, 9), False, TZ)


def test_event_write_api_with_fake_target(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("timezone: Asia/Yekaterinburg\nsources:\n  - id: ya\n    type: caldav\n    url: http://x\n"
                   "    username: u\n    password: p\npeople:\n  - id: anna\n    name: Анна\n")
    monkeypatch.setenv("HOMECAL_CONFIG", str(cfg))
    monkeypatch.setenv("HOMECAL_DATA_DIR", str(tmp_path))
    import importlib

    from fastapi.testclient import TestClient

    from app import core, main
    importlib.reload(core)
    importlib.reload(main)

    class Fake:
        def __init__(self): self.store = {}
        def create(self, rid, ics): self.store["/e1.ics"] = ics; return "/e1.ics"
        def update(self, rid, href, ics): self.store[href] = ics
        def delete(self, rid, href): del self.store[href]

    fake = Fake()
    monkeypatch.setattr(core, "make_target", lambda key: fake)
    core.db.touch_calendar("ya/home", "ya", "home", "Дом", {"people": ["anna"]})
    c = TestClient(main.app)
    r = c.post("/api/event", json={"calendar": "ya/home", "title": "Врач", "start": "2026-11-03T10:00:00",
                                   "end": "2026-11-03T11:00:00", "people": ["anna"]})
    assert r.status_code == 200, r.text
    assert any(x["route"] == "POST /api/event" for x in c.get("/api/perf").json()["routes"])
    uid = r.json()["uid"]
    assert "SUMMARY:Врач" in fake.store["/e1.ics"]
    evs = c.get("/api/events", params={"start": "2026-11-01T00:00:00", "end": "2026-11-10T00:00:00"}).json()
    assert [e["title"] for e in evs] == ["Врач"]

    assert c.put(f"/api/event/{uid}", json={"calendar": "ya/home", "title": "Врач 2"}).status_code == 200
    assert "SUMMARY:Врач 2" in fake.store["/e1.ics"]
    assert c.put("/api/event/nope", json={"calendar": "ya/home"}).status_code == 404

    assert c.delete(f"/api/event/{uid}", params={"calendar": "ya/home"}).status_code == 200
    assert fake.store == {}
    assert c.get("/api/events", params={"start": "2026-11-01T00:00:00", "end": "2026-11-10T00:00:00"}).json() == []
    cal = [x for x in c.get("/api/config").json()["calendars"] if x["key"] == "ya/home"][0]
    assert cal["writable"] is True


def test_writer_edit_occurrence_shifts_series():
    from app import writer

    _, ics = writer.build_ics("Йога", datetime(2026, 11, 2, 18), datetime(2026, 11, 2, 19), False, TZ,
                              repeat={"freq": "weekly", "count": 3})
    # правим вторую неделю: перенос на 19:00–20:30 — вся серия сдвигается
    new = writer.apply_edit(ics, {"start": datetime(2026, 11, 9, 19), "end": datetime(2026, 11, 9, 20, 30),
                                  "all_day": False, "occurrence": datetime(2026, 11, 9, 18)}, TZ)
    occ = _occ(new)
    assert [o.start for o in occ][0] == "2026-11-02T19:00:00+05:00" and occ[0].end == "2026-11-02T20:30:00+05:00"
    assert len(occ) == 3


def test_event_reminders_per_person(db):
    from app import reminders

    ics = ev("yoga@test", "Йога", "20261029T180000", "20261029T190000")
    _setup(db, {"a": (["anna", "boris"], [ics])})
    svc = EventService(db, TZ)
    evs = svc.events(datetime(2026, 10, 29, 0, tzinfo=TZ), datetime(2026, 10, 30, 0, tzinfo=TZ))
    assert reminders.save_rules(db, {"anna": [30, 10], "boris": [30], "ghost": [5]}, {"anna", "boris"}) == \
        {"anna": [30, 10], "boris": [30]}
    now = datetime(2026, 10, 29, 12, tzinfo=TZ)
    items = reminders.build(evs, [], now, TZ, None, None, 2, reminders.load_rules(db))
    ev_items = [i for i in items if i["kind"] == "event"]
    by = {i["id"].rsplit(":", 1)[1]: i for i in ev_items}
    assert set(by) == {"30", "10"}
    assert sorted(by["30"]["people"]) == ["anna", "boris"] and by["10"]["people"] == ["anna"]
    assert by["30"]["at"].startswith("2026-10-29T17:30") and by["30"]["title"] == "Йога — через 30 мин"
    # фильтр по человеку (устройство Бориса)
    only_b = reminders.build(evs, [], now, TZ, {"boris"}, None, 2, reminders.load_rules(db))
    assert [i["id"].rsplit(":", 1)[1] for i in only_b if i["kind"] == "event"] == ["30"]


def test_write_queue_retry_journal_undo(tmp_path, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("timezone: Asia/Yekaterinburg\nsources:\n  - id: ya\n    type: caldav\n    url: http://x\n"
                   "    username: u\n    password: p\npeople:\n  - id: anna\n    name: Анна\n")
    monkeypatch.setenv("HOMECAL_CONFIG", str(cfg))
    monkeypatch.setenv("HOMECAL_DATA_DIR", str(tmp_path))
    import importlib

    from fastapi.testclient import TestClient

    from app import core, main
    importlib.reload(core)
    importlib.reload(main)

    class Fake:
        down = False
        def __init__(self): self.store = {}; self.n = 0
        def _chk(self):
            if self.down: raise ConnectionError("connection refused")
        def create(self, rid, ics): self._chk(); self.n += 1; h = f"/e{self.n}.ics"; self.store[h] = ics; return h
        def update(self, rid, href, ics): self._chk(); self.store[href] = ics
        def delete(self, rid, href): self._chk(); del self.store[href]

    fake = Fake()
    monkeypatch.setattr(core, "make_target", lambda key: fake)
    core.db.touch_calendar("ya/home", "ya", "home", "Дом", {"people": ["anna"]})
    c = TestClient(main.app)
    rng = {"start": "2026-11-01T00:00:00", "end": "2026-11-10T00:00:00"}

    fake.down = True
    r = c.post("/api/event", json={"calendar": "ya/home", "title": "Врач", "start": "2026-11-03T10:00:00"}).json()
    assert r["pending"] is True and fake.store == {}
    assert [e["title"] for e in c.get("/api/events", params=rng).json()] == ["Врач"]
    uid = r["uid"]
    # правка до отправки сливается с созданием
    c.put(f"/api/event/{uid}", json={"calendar": "ya/home", "title": "Врач 2"})
    assert core.ws.pending_count() == 1
    # синхронизация не должна стирать неотправленное
    core.db.replace_objects("ya/home", {})
    core.ws.reapply()
    assert [e["title"] for e in c.get("/api/events", params=rng).json()] == ["Врач 2"]
    assert c.get("/api/status").status_code == 200

    fake.down = False
    assert core.ws.flush() == {"done": 1, "failed": 0, "left": 0}
    assert list(fake.store) == ["/e1.ics"] and "SUMMARY:Врач 2" in fake.store["/e1.ics"]
    found = core.db.find_object(uid)
    assert found[1] == "/e1.ics"

    # журнал и отмена
    log = c.get("/api/changes").json()["items"]
    assert [x["action"] for x in log] == ["update", "create"]
    assert c.post(f"/api/changes/{log[0]['id']}/undo").status_code == 200   # правка отменена
    assert "SUMMARY:Врач\r" in fake.store["/e1.ics"] or "SUMMARY:Врач\n" in fake.store["/e1.ics"]
    assert c.delete(f"/api/event/{uid}", params={"calendar": "ya/home"}).status_code == 200
    assert fake.store == {}
    dl = c.get("/api/changes").json()["items"][0]
    assert dl["action"] == "delete"
    assert c.post(f"/api/changes/{dl['id']}/undo").status_code == 200       # удаление отменено
    assert len(fake.store) == 1
    assert [e["title"] for e in c.get("/api/events", params=rng).json()] == ["Врач"]


def test_quick_parse_phrases():
    from app.quick import parse

    P = [{"id": "olya", "name": "Оля", "keywords": ""}, {"id": "mark", "name": "Марк", "keywords": "футбол"}]
    now = datetime(2026, 10, 28, 16, 0)
    r = parse("Йога завтра в 18:30 у Оли", now, P)
    assert (r["title"], r["date"], r["start"], r["end"], r["people"]) == ("Йога", "2026-10-29", "18:30", "19:30", ["olya"])
    r = parse("Бассейн по вторникам в 15:00 на 45 минут", now, P)
    assert r["repeat"] == {"freq": "weekly"} and r["date"] == "2026-11-03" and r["end"] == "15:45"
    r = parse("Купить подарок 5.12", now, P)
    assert r["all_day"] and r["date"] == "2026-12-05" and r["title"] == "Купить подарок"
    r = parse("футбол в пятницу 17:00-18:30", now, P)
    assert r["title"] == "Футбол" and r["end"] == "18:30" and r["people"] == ["mark"]


def test_settings_export_import_roundtrip(tmp_path):
    from app import portable

    a = Database(tmp_path / "a.sqlite3")
    a.upsert_person({"id": "anna", "name": "Анна", "color": "#ff0000", "keywords": "йога"})
    a.touch_calendar("s/x", "s", "x", "Дом", {"people": ["anna"]})
    a.set_event_people("u1", ["anna"])
    a.add_list("Ремонт")
    a.kv_set("settings:school", {"breaks": [1]})
    a.kv_set("auth:ya", {"password": "secret"})
    blob = portable.export(a, "t")
    assert "secret" not in str(blob)

    b = Database(tmp_path / "b.sqlite3")
    b.upsert_person({"id": "zzz", "name": "Лишний"})
    counts = portable.import_(b, blob)
    assert counts["people"] == 1
    assert [p["id"] for p in b.list_people()] == ["anna"] and b.list_people()[0]["keywords"] == "йога"
    assert b.get_calendar("s/x")["people"] == ["anna"] and b.event_people() == {"u1": ["anna"]}
    assert b.kv_get("settings:school")[0] == {"breaks": [1]} and b.kv_get("auth:ya")[0] is None
    with pytest.raises(ValueError):
        portable.import_(b, {"format": "other"})


def test_split_occurrence_moves_only_one():
    from app import writer

    _, ics = writer.build_ics("Йога", datetime(2026, 11, 2, 18), datetime(2026, 11, 2, 19), False, TZ,
                              location="Зал", repeat={"freq": "weekly", "count": 3})
    series, uid2, one = writer.split_occurrence(ics, datetime(2026, 11, 9, 18), datetime(2026, 11, 10, 9),
                                                datetime(2026, 11, 10, 10), False, TZ)
    assert [o.start for o in _occ(series)] == ["2026-11-02T18:00:00+05:00", "2026-11-16T18:00:00+05:00"]
    o = _occ(one)
    assert len(o) == 1 and o[0].title == "Йога" and o[0].start == "2026-11-10T09:00:00+05:00" and o[0].location == "Зал"


def test_incremental_sync_skips_unchanged(db):
    from app.sources.base import REGISTRY, RemoteCalendar, Source, register

    calls = {"fetch": [], "tag": "t1", "ics": "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:1\nEND:VEVENT\nEND:VCALENDAR"}

    @register("fakectag")
    class Fake(Source):
        def fetch(self, known=None):
            calls["fetch"].append(dict(known or {}))
            if known and (known.get("c") or {}).get("ctag") == calls["tag"]:
                return [RemoteCalendar("c", "C", ctag=calls["tag"], unchanged=True)]
            return [RemoteCalendar("c", "C", objects={"h": calls["ics"]}, ctag=calls["tag"])]

    try:
        hits = []
        engine = SyncEngine(db, [{"id": "f", "type": "fakectag"}], on_change=lambda: hits.append(1))
        engine.run()                       # первая — полная
        assert len(hits) == 1 and db.objects_map("f/c")
        engine.run()                       # ctag тот же — объекты не трогаем, кэш не сбрасываем
        assert calls["fetch"][1] == {"c": {"ctag": "t1", "token": None}} and len(hits) == 1
        assert db.objects_map("f/c")       # данные на месте
        calls["tag"], calls["ics"] = "t2", calls["ics"].replace("UID:1", "UID:2")
        engine.run()
        assert "UID:2" in db.objects_map("f/c")["h"] and len(hits) == 2
        engine.run(full=True)              # принудительно — известные метки не передаются
        assert calls["fetch"][-1] == {}
    finally:
        REGISTRY.pop("fakectag", None)


def test_backup_verify_and_restore(tmp_path):
    from app import backup as bk
    from app.cloud import CloudSync

    db = Database(tmp_path / "t.sqlite3")
    db.kv_set("marker", {"x": 1})
    db.upsert_person({"id": "a", "name": "Аня", "color": "#000"})

    class FakeDisk:
        files: dict = {}

        def __init__(self, token):
            pass

        def mkdir(self, p):
            pass

        def upload(self, data, path):
            FakeDisk.files[path.rsplit("/", 1)[1]] = data

        def ls(self, p):
            return [{"name": n, "size": len(b)} for n, b in FakeDisk.files.items()]

        def rm(self, path):
            FakeDisk.files.pop(path.rsplit("/", 1)[1], None)

        def download_path(self, path):
            return FakeDisk.files[path.rsplit("/", 1)[1]]

    c = CloudSync(db, lambda: {}, FakeDisk)
    c.set_token("y0_testtoken_0123456789abcdef")
    svc = bk.BackupService(db, c, TZ, FakeDisk)
    svc.run()
    name = svc.files()[0]["name"]
    v = svc.verify()
    assert v["ok"] and v["name"] == name and v["people"] == 1
    assert svc.status()["verified"]["ok"]
    db.kv_set("marker", {"x": 2})
    db.delete_person("a") if hasattr(db, "delete_person") else None
    res = svc.restore(name)
    assert res["ok"] and db.kv_get("marker")[0] == {"x": 1}
    assert (tmp_path / "before-restore.db.gz").exists()
    # битая и чужая копии не принимаются
    FakeDisk.files["homehub-29990101-0000" + bk.SUFFIX] = b"junk"
    assert not svc.verify("homehub-29990101-0000" + bk.SUFFIX)["ok"]
    try:
        svc.restore("../x")
        assert False
    except Exception as e:  # noqa: BLE001
        assert "имя" in str(e)


def test_perf_log():
    from app.perf import PerfLog
    p = PerfLog()
    p.record("GET", "/api/events", 120, 200)
    p.record("GET", "/api/events", 2000, 200, "start=1")
    s = p.summary()
    assert s["routes"][0]["n"] == 2 and s["slow"][0]["ms"] == 2000


def test_conflicts_on_create(db):
    from datetime import datetime
    from app import conflicts
    _setup(db, {"mom": ("mom", [ev("yoga@t", "Йога", "20261028T180000", "20261028T190000")]),
                "dad": ("dad", [ev("work@t", "Совещание", "20261028T160000", "20261028T170000")])})
    db.upsert_person({"id": "mark", "name": "Марк", "needs_escort": True})
    svc = EventService(db, TZ)
    t = lambda h, m=0: datetime(2026, 10, 28, h, m, tzinfo=TZ)  # noqa: E731
    # Мама на йоге — предупреждение о занятости
    r = conflicts.check(svc, calendar="mom", title="Врач", start=t(18, 30), end=t(19, 30), all_day=False, people=["mom"])
    assert any(x["kind"] == "event" and "Йога" in x["text"] for x in r)
    # Свободное время — тишина
    assert conflicts.check(svc, calendar="mom", title="Врач", start=t(12), end=t(13), all_day=False, people=["mom"]) == []
    # Правка самого события не конфликтует с ним же
    assert conflicts.check(svc, calendar="mom", title="Йога", start=t(18, 15), end=t(19), all_day=False,
                           people=["mom"], uid="yoga@t") == []
    # Ребёнок: родители заняты и до, и после — нужно сказать, что некому
    r = conflicts.check(svc, calendar="mom", title="Секция", start=t(16, 30), end=t(17), all_day=False, people=["mark"])
    texts = " ".join(x["text"] for x in r)
    assert "Марка" in texts, texts
    # Весь день — не проверяем
    assert conflicts.check(svc, calendar="mom", title="x", start=t(0), end=None, all_day=True, people=["mom"]) == []


def test_split_following_weekly_and_count():
    from datetime import datetime
    from app import writer
    from app.expand import expand_ics
    start = datetime(2026, 11, 3, 17, 40, tzinfo=TZ)   # вторник
    uid, ics = writer.build_ics("Ушу", start, start.replace(hour=18, minute=40), False, TZ,
                                repeat={"freq": "weekly", "count": 6})
    occ = datetime(2026, 11, 17, 17, 40, tzinfo=TZ)     # третье вхождение
    new_start = datetime(2026, 11, 18, 18, 0, tzinfo=TZ)  # теперь среда, 18:00
    old, nuid, new = writer.split_following(ics, occ, {"start": new_start, "end": new_start.replace(hour=19),
                                                       "all_day": False, "title": "Ушу (новое время)"}, TZ)
    rng_ = (datetime(2026, 10, 1, tzinfo=TZ), datetime(2026, 12, 31, tzinfo=TZ))
    o = [x.start for x in expand_ics(old, *rng_, TZ)]
    n = [x.start for x in expand_ics(new, *rng_, TZ)]
    assert len(o) == 2 and o[-1].startswith("2026-11-10")      # старая: 3 и 10 ноября
    assert len(n) == 4 and n[0].startswith("2026-11-18T18:00") and n[1].startswith("2026-11-25T18:00")
    assert nuid != uid and "SUMMARY:Ушу (новое время)" in new
    # первое вхождение — вся серия
    assert writer.split_following(ics, start, {"start": start, "all_day": False}, TZ) is None


def test_cancelled_titles_hidden():
    from app.expand import is_cancelled_title
    assert is_cancelled_title("Отменено: планёрка")
    assert is_cancelled_title("Canceled: Weekly sync")
    assert is_cancelled_title("  Отменена - встреча")
    assert not is_cancelled_title("Планёрка отменена на завтра")
    assert not is_cancelled_title("Отмена прививки")
