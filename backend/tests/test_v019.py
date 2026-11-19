"""v0.19: журнал «что изменилось», кэш разбора iCalendar."""
from datetime import timedelta

from app import changes, expand


def _iso(t, d, h):
    return (t + timedelta(days=d)).replace(hour=h).strftime("%Y-%m-%dT%H:%M:%S")


def test_changes_journal_new_moved_deleted(api):
    core = api.core
    t = core._today_start()
    core.events.warm()                                   # первая сборка окна — база для сравнения
    ev = api.post("/api/event", json={"calendar": "ya/home", "title": "Английский", "start": _iso(t, 2, 16),
                                      "end": _iso(t, 2, 17), "people": ["anna"]}, headers={"user-agent": "HomeHubApp/2.11 (iPhone)"}).json()
    core.events.warm()
    log = changes.recent(core.db)
    assert log[0]["text"].startswith("Новое: Английский") and log[0]["origin"] == "с iPhone" and log[0]["people"] == ["anna"]
    api.put(f"/api/event/{ev['uid']}", json={"calendar": "ya/home", "start": _iso(t, 2, 17), "end": _iso(t, 2, 18)})
    core.events.warm()
    log = changes.recent(core.db)
    assert log[0]["text"].startswith("Изменено: Английский") and "→" in log[0]["text"]
    # уведомление — kind=event, тому, чьё событие
    items = changes.reminders(core.db, __import__("datetime").datetime.now(core.tz), {"anna"})
    assert items and items[0]["kind"] == "event" and items[0]["people"] == ["anna"]
    assert not changes.reminders(core.db, __import__("datetime").datetime.now(core.tz), {"papa"})
    assert api.get("/api/event-changes").json()["items"][0]["text"].startswith("Изменено")


def test_changes_mass_is_one_line():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Yekaterinburg")
    now = datetime.now(tz)
    old = [{"id": f"x{i}", "uid": f"u{i}", "start": (now + timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1, hours=1)).isoformat(),
            "title": f"E{i}", "people": []} for i in range(20)]
    found = changes.diff(old, [], now)
    assert len(found) == 20
    assert changes.diff(old, old, now) == []


def test_expand_cache_reuses_and_sees_changes():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Yekaterinburg")
    ics = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:a", "DTSTART:20261120T100000Z",
                       "DTEND:20261120T110000Z", "SUMMARY:{}", "END:VEVENT", "END:VCALENDAR", ""])
    s, e = datetime(2026, 11, 1, tzinfo=tz), datetime(2026, 12, 1, tzinfo=tz)
    a = expand.expand_ics(ics.format("Один"), s, e, tz)
    b = expand.expand_ics(ics.format("Один"), s, e, tz)
    c = expand.expand_ics(ics.format("Два"), s, e, tz)
    assert a[0].title == b[0].title == "Один" and c[0].title == "Два"


def _tz_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Yekaterinburg")
    return tz, datetime.now(tz).replace(minute=0, second=0, microsecond=0)


def _series(now, hour, n=4, title="Бассейн", **kw):
    return [{"id": f"s{d}", "uid": "S", "start": (now + timedelta(days=d)).replace(hour=hour).isoformat(),
             "end": (now + timedelta(days=d)).replace(hour=hour + 1).isoformat(), "title": title, "people": ["mark"], **kw}
            for d in range(1, 1 + 7 * n, 7)]


def test_series_moved_is_one_change():
    """Перенос серии 16:00 → 17:00 — одна запись «Изменено … (всё повторение)», а не «Отменено» + «Новое» по каждому разу."""
    tz, now = _tz_now()
    found = changes.diff(_series(now, 16), _series(now, 17), now)
    assert len(found) == 1 and found[0]["kind"] == "changed" and found[0].get("series") == 2   # 2 вхождения в 14 днях
    assert "всё повторение" in changes.describe(found[0], tz)
    one = _series(now, 16)
    two = [dict(e) for e in one]
    two[0]["start"] = two[0]["start"].replace("T16", "T18")
    found = changes.diff(one, two, now)
    assert len(found) == 1 and "→" in changes.describe(found[0], tz)


def test_private_does_not_leak_old_title():
    tz, now = _tz_now()
    old = [{"id": "p", "uid": "P", "start": (now + timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1, hours=1)).isoformat(),
            "title": "Психолог", "location": "ул. Ленина 1", "people": ["anna"]}]
    new = [dict(old[0], title="Занят", location="", private=True)]
    assert changes.diff(old, new, now) == []                       # стало личным — не изменение
    moved = [dict(new[0], start=(now + timedelta(days=2)).isoformat(), end=(now + timedelta(days=2, hours=1)).isoformat())]
    txt = changes.describe(changes.diff(new, moved, now)[0], tz)
    assert "Психолог" not in txt and "Ленина" not in txt


def test_hidden_calendar_is_not_a_change(api):
    core = api.core
    t = core._today_start()
    core.events.warm()
    api.post("/api/event", json={"calendar": "ya/home", "title": "Йога", "start": _iso(t, 3, 10), "end": _iso(t, 3, 11), "people": ["anna"]})
    core.events.warm()
    before = len(changes.recent(core.db))
    api.patch("/api/calendars/ya/home", json={"hidden": True})
    core.events.warm()
    api.patch("/api/calendars/ya/home", json={"hidden": False})
    core.events.warm()
    assert len(changes.recent(core.db)) == before


def test_take_ids_only_for_own_list(api):
    """«Всё взял» не трогает общий список («Покупки»), привязанный к событию."""
    from app import eventlists
    db = api.core.db
    shop, own = db.add_list("Покупки"), db.add_list("Бассейн: вещи")
    db.add_item(shop, "молоко", None)
    db.add_item(own, "очки", None)
    eventlists.attach(db, "U1", shop, own=False)
    eventlists.attach(db, "U2", own, own=True)
    tl = eventlists.todo_texts(db)
    assert [x["own"] for x in tl["U1"]] == [False] and [x["own"] for x in tl["U2"]] == [True]


def test_expand_cache_only_when_asked():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("UTC")
    ics = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:c1", "DTSTART:20300101T100000Z",
                        "DTEND:20300101T110000Z", "SUMMARY:x", "END:VEVENT", "END:VCALENDAR"])
    a, b = datetime(2029, 12, 1, tzinfo=tz), datetime(2030, 2, 1, tzinfo=tz)
    expand._OCC.clear()
    expand.expand_ics(ics, a, b, tz)
    assert not expand._OCC
    expand.expand_ics(ics, a, b, tz, cache=True)
    assert len(expand._OCC) == 1
    expand.expand_ics(ics, a, b + timedelta(days=1), tz, cache=True)   # другое окно (новый день) — кэш сначала очищен
    assert len(expand._OCC) == 1


def test_take_list_resets_for_next_time_without_opening(api):
    """«Всё взял» из уведомления, событие не открывали: к следующему разу отметки снимаются при сборке напоминаний."""
    from datetime import datetime
    from app import eventlists
    db, tz = api.core.db, api.core.tz
    now = datetime.now(tz)
    lid = db.add_list("Бассейн: вещи")
    item = db.add_item(lid, "шапочка", None)
    eventlists.attach(db, "SW", lid, own=True)
    m = eventlists.load(db)
    m["SW"]["occ"] = (now - timedelta(days=6)).isoformat()   # прошлый раз уже прошёл
    db.kv_set(eventlists.KEY, m)
    iid = item if isinstance(item, int) else item["id"]
    db.update_item(iid, {"done": True})
    assert eventlists.todo_texts(db) == {"SW": []}
    nxt = [{"uid": "SW", "start": (now + timedelta(days=1)).isoformat()}]
    assert [x["text"] for x in eventlists.todo_texts(db, nxt, now)["SW"]] == ["шапочка"]


def test_take_list_all_day_series_does_not_crash(api):
    """Событие на весь день: вхождение — дата без пояса, now — с поясом (раньше TypeError ронял снимок)."""
    from datetime import datetime
    from app import eventlists
    db, tz = api.core.db, api.core.tz
    now = datetime.now(tz)
    lid = db.add_list("Поход: вещи")
    db.add_item(lid, "термос", None)
    eventlists.attach(db, "AD", lid, own=True)
    eventlists.for_occurrence(db, "AD", (now - timedelta(days=7)).strftime("%Y-%m-%d"))
    out = eventlists.todo_texts(db, [{"uid": "AD", "start": now.strftime("%Y-%m-%d")}], now)
    assert [x["text"] for x in out["AD"]] == ["термос"]
    assert api.get("/api/reminders").status_code == 200
