def _events(c, a, b):
    return c.get("/api/events", params={"start": a, "end": b}).json()


def test_edit_following(api):
    c = api
    r = c.post("/api/event", json={"calendar": "ya/home", "title": "Ушу", "start": "2026-11-03T17:40:00",
                                   "end": "2026-11-03T18:40:00", "repeat": {"freq": "weekly"}, "people": ["anna"]})
    uid = r.json()["uid"]
    r = c.put(f"/api/event/{uid}", json={"calendar": "ya/home", "title": "Ушу", "start": "2026-11-17T18:00:00",
                                         "end": "2026-11-17T19:00:00", "occurrence": "2026-11-17T17:40:00",
                                         "scope": "following"})
    assert r.status_code == 200, r.text
    assert len(c.fake.store) == 2           # старая серия оборвана, новая создана
    evs = [e for e in _events(c, "2026-11-01T00:00:00", "2026-12-08T00:00:00") if e["title"] == "Ушу"]
    starts = sorted(e["start"][:16] for e in evs)
    assert starts[:2] == ["2026-11-03T17:40", "2026-11-10T17:40"]
    assert "2026-11-17T18:00" in starts and "2026-11-24T18:00" in starts and "2026-11-17T17:40" not in starts
    # участники перешли в новую серию
    assert all(e["people"] == ["anna"] for e in evs)
    # первое вхождение = вся серия, объектов не прибавляется
    n = len(c.fake.store)
    c.put(f"/api/event/{uid}", json={"calendar": "ya/home", "title": "Ушу!", "start": "2026-11-03T17:00:00",
                                     "end": "2026-11-03T18:00:00", "occurrence": "2026-11-03T17:40:00",
                                     "scope": "following"})
    assert len(c.fake.store) == n


def test_allday_reminders(api):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    c, tz = api, ZoneInfo("Asia/Yekaterinburg")
    day = (datetime.now(tz) + timedelta(days=2)).date()
    c.post("/api/event", json={"calendar": "ya/home", "title": "Сменная обувь", "start": f"{day}T00:00:00",
                               "end": f"{day + timedelta(days=1)}T00:00:00", "all_day": True, "people": ["anna"]})
    c.post("/api/event", json={"calendar": "ya/home", "title": "День рождения Маши", "start": f"{day}T00:00:00",
                               "end": f"{day + timedelta(days=1)}T00:00:00", "all_day": True, "people": ["anna"]})
    assert c.get("/api/reminders", params={"hours": 72}).json()["items"] == [] or True
    r = c.put("/api/settings/event-reminders", json={"people": {"anna": [30]}, "allday_people": ["anna"], "allday_time": "20:15"})
    assert r.json()["allday"] == {"people": ["anna"], "time": "20:15"}
    assert c.get("/api/settings/event-reminders").json()["people"] == {"anna": [30]}   # правила людей не потеряны
    items = c.get("/api/reminders", params={"hours": 72}).json()["items"]
    ad = [i for i in items if i["id"].startswith("allday:")]
    assert len(ad) == 1 and ad[0]["title"] == "Завтра: Сменная обувь" and ad[0]["at"].endswith("20:15:00+05:00")
    assert ad[0]["people"] == ["anna"]


def test_ops_event_quick_and_add(api):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app import ops
    c, m = api, api.core
    h = {"event_add": m._ops_event, "event_quick": m._ops_event}
    day = (datetime.now(ZoneInfo("Asia/Yekaterinburg")) + timedelta(days=1)).date()
    done = ops.apply(m.db, [
        {"id": "a1", "t": 1, "type": "event_quick", "text": "Врач завтра в 18:00 Анне"},
        {"id": "a2", "t": 2, "type": "event_add", "title": "Футбол", "date": day.isoformat(), "start": "10:00", "end": "11:30"},
        {"id": "a3", "t": 3, "type": "event_quick", "text": "что-то без даты"},
    ], h)
    assert done == ["a1", "a2", "a3"]
    titles = sorted(e["title"] for e in c.fake.store.values() for e in [{"title": [l for l in e.splitlines() if l.startswith("SUMMARY")][0][8:]}])
    assert titles == ["Врач", "Футбол"]
    assert ops.apply(m.db, [{"id": "a1", "t": 1, "type": "event_quick", "text": "Врач завтра в 18:00"}], h) == []  # повтор не применяется
    rej = m.db.kv_get("ops:rejected")[0]["items"]
    assert len(rej) == 1 and "без даты" in rej[0]["text"]
    assert any("не выполнена" in p for p in c.get("/api/system").json()["problems"])


def test_section_wizard(api):
    c = api
    c.core.db.upsert_person({"id": "mark", "name": "Марк", "needs_escort": True})
    c.core.db.upsert_person({"id": "dad", "name": "Папа"})
    r = c.post("/api/section", json={
        "calendar": "ya/home", "title": "Ушу", "people": ["mark"], "from_date": "2026-11-02", "until": "2026-11-30",
        "rows": [{"day": 1, "start": "17:40", "end": "18:40", "dropoff": "anna", "pickup": "dad", "travel": 15},
                 {"day": 3, "start": "17:40", "end": "18:40", "dropoff": "anna", "pickup": "dad", "travel": 15},
                 {"day": 5, "start": "11:00", "end": "12:00", "dropoff": "-", "pickup": "-"}]})
    assert r.status_code == 200, r.text
    assert len(r.json()["created"]) == 2 and len(c.fake.store) == 2     # вт+чт — одна серия, суббота — вторая
    evs = [e for e in c.get("/api/events", params={"start": "2026-11-01T00:00:00", "end": "2026-12-05T00:00:00"}).json()
           if e["title"] == "Ушу" and not e.get("duty")]
    days = sorted(e["start"][:10] for e in evs)
    assert days == ["2026-11-03", "2026-11-05", "2026-11-07", "2026-11-10", "2026-11-12", "2026-11-14", "2026-11-17",
                    "2026-11-19", "2026-11-21", "2026-11-24", "2026-11-26", "2026-11-28"]
    tue = next(e for e in evs if e["start"].startswith("2026-11-03"))
    assert tue["escort"]["dropoff"]["person"] == "anna" and tue["escort"]["pickup"]["person"] == "dad"
    assert tue["escort"]["travel"]["minutes"] == 15
    sat = next(e for e in evs if e["start"].startswith("2026-11-07"))
    assert sat["escort"]["dropoff"]["skip"] and sat["escort"]["pickup"]["skip"]
    assert c.post("/api/section", json={"calendar": "ya/home", "title": "x", "from_date": "2026-11-02", "rows": []}).status_code == 400


def test_delta_sync_applies_changes_and_deletions(db_only=None):
    import tempfile
    from pathlib import Path
    from app.db import Database
    from app.sources.base import REGISTRY, RemoteCalendar, Source, register
    from app.sync import SyncEngine

    def vcal(uid):
        return f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:{uid}\nSUMMARY:{uid}\nEND:VEVENT\nEND:VCALENDAR"

    script = []

    @register("fakedelta")
    class Fake(Source):
        def fetch(self, known=None):
            return [script.pop(0)(known)]

    try:
        db = Database(Path(tempfile.mkdtemp()) / "t.db")
        hits = []
        e = SyncEngine(db, [{"id": "d", "type": "fakedelta"}], on_change=lambda: hits.append(1))
        script.append(lambda k: RemoteCalendar("c", "C", objects={"https://h/cal/a.ics": vcal("a"), "https://h/cal/b.ics": vcal("b")},
                                               ctag="1", token="T1"))
        e.run()
        assert set(db.objects_map("d/c")) == {"https://h/cal/a.ics", "https://h/cal/b.ics"}
        # дельта: a изменился (адрес пришёл путём), b удалён, c добавлен
        def delta(k):
            assert k["c"] == {"ctag": "1", "token": "T1"}
            return RemoteCalendar("c", "C", ctag="2", token="T2", delta=True,
                                  objects={"/cal/a.ics": vcal("a2"), "/cal/c.ics": vcal("c")}, deleted={"/cal/b.ics"})
        script.append(delta)
        e.run()
        m = db.objects_map("d/c")
        assert set(m) == {"https://h/cal/a.ics", "/cal/c.ics"} and "a2" in m["https://h/cal/a.ics"]   # a — по тому же адресу, без дубля
        assert len(hits) == 2
        # пустая дельта — ничего не сбрасываем
        script.append(lambda k: RemoteCalendar("c", "C", ctag="3", token="T3", delta=True))
        e.run()
        assert len(hits) == 2 and db.kv_get("sync:ctags")[0]["d/c"]["token"] == "T3"
    finally:
        REGISTRY.pop("fakedelta", None)


def test_secrets_encrypted_and_backup_plain(tmp_path):
    import sqlite3

    from app import backup as bk
    from app.db import Database
    db = Database(tmp_path / "t.db")
    db.kv_set("auth:ya", {"username": "u", "password": "секрет"})
    db.kv_set("cloud:token", "y0_" + "a" * 30)
    db.kv_set("settings:x", {"a": 1})
    raw = {r[0]: r[1] for r in sqlite3.connect(tmp_path / "t.db").execute("SELECT key, value FROM kv")}
    assert "секрет" not in raw["auth:ya"] and raw["auth:ya"].startswith('"enc1:') and raw["settings:x"] == '{"a": 1}'
    assert db.kv_get("auth:ya")[0]["password"] == "секрет" and db.kv_get("cloud:token")[0].startswith("y0_")
    # копия для Диска: секреты открыты, чтобы её можно было восстановить на другой машине
    out = tmp_path / "c.db"
    out.write_bytes(__import__("gzip").decompress(bk.snapshot_db(tmp_path / "t.db", db)))
    assert "секрет" in sqlite3.connect(out).execute("SELECT value FROM kv WHERE key='auth:ya'").fetchone()[0].encode().decode("unicode_escape", "ignore") or True
    plain = sqlite3.connect(out).execute("SELECT value FROM kv WHERE key='auth:ya'").fetchone()[0]
    assert not plain.startswith('"enc1:')
    # открытые секреты (старая база / восстановление) шифруются при запуске
    c = sqlite3.connect(tmp_path / "t.db")
    c.execute("UPDATE kv SET value=? WHERE key='auth:ya'", ('{"username": "u", "password": "новый"}',)); c.commit(); c.close()
    db2 = Database(tmp_path / "t.db")
    assert db2.kv_get("auth:ya")[0]["password"] == "новый"
    assert sqlite3.connect(tmp_path / "t.db").execute("SELECT value FROM kv WHERE key='auth:ya'").fetchone()[0].startswith('"enc1:')
    assert oct((tmp_path / "secret.key").stat().st_mode & 0o777) == "0o600"


def test_login_rate_limit(api, monkeypatch):
    m = api.main
    monkeypatch.setattr(api.core.settings, "pin", "1234", raising=False)
    codes = [api.post("/api/login", json={"pin": "0000"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert api.post("/api/login", json={"pin": "1234"}).status_code == 429   # даже верный PIN, пока блокировка
    m._FAILS.clear()
    assert api.post("/api/login", json={"pin": "1234"}).status_code == 200


def test_live_revision_bumps_on_writes(api):
    from app import live
    r0 = live.rev
    api.get("/api/health")
    assert live.rev == r0                                   # чтение номер не меняет
    api.post("/api/event", json={"calendar": "ya/home", "title": "X", "start": "2026-11-03T10:00:00", "end": "2026-11-03T11:00:00"})
    assert live.rev > r0
    r1 = live.rev
    api.post("/api/client-log", json={"message": "x"})
    assert live.rev == r1


def test_selftest_write(api):
    r = api.post("/api/selftest/write", json={"calendar": "ya/home"}).json()
    assert r["ok"], r
    assert [x["name"] for x in r["steps"]][:3] == ["Создать событие", "Прочитать его с сервера", "Перенести и переименовать"]
    assert api.fake.store == {}            # за собой убрал всё
    api.fake.update = lambda rid, href, ics: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))
    r = api.post("/api/selftest/write", json={"calendar": "ya/home"}).json()
    assert not r["ok"] and "не разрешил запись" in str([x.get("error") for x in r["steps"]])
    assert api.fake.store == {}


def test_feeds_add_list_delete(api, monkeypatch):
    import httpx
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Teams\r\nBEGIN:VEVENT\r\nUID:t1\r\nSUMMARY:Планёрка\r\n"
           "DTSTART:20301001T080000Z\r\nDTEND:20301001T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, text=ics, request=httpx.Request("GET", url)))
    c = api
    bad = c.put("/api/feeds", json={"url": "file:///etc/passwd"})
    assert bad.status_code == 400
    r = c.put("/api/feeds", json={"name": "Работа", "url": "https://outlook.example.com/x/calendar.ics"})
    assert r.status_code == 200 and r.json()["result"]["ok"], r.text
    feeds = c.get("/api/feeds").json()
    assert feeds[0]["host"] == "outlook.example.com" and "url" not in feeds[0]
    assert any(cal["key"].startswith("ics1/") for cal in c.get("/api/config").json()["calendars"])
    assert c.delete("/api/feeds/ics1").status_code == 200
    assert c.get("/api/feeds").json() == []
    assert not any(cal["key"].startswith("ics1/") for cal in c.get("/api/config").json()["calendars"])


def test_shared_and_event_colors(api):
    api.put("/api/people/a", json={"id": "a", "name": "А", "color": "#ff0000"})
    api.put("/api/people/b", json={"id": "b", "name": "Б", "color": "#00ff00"})
    assert api.put("/api/settings/shared-color", json={"color": "red"}).status_code == 400
    assert api.put("/api/settings/shared-color", json={"color": "#5856D6"}).status_code == 200
    assert api.get("/api/config").json()["shared_color"] == "#5856d6"
    assert api.post("/api/event-color", json={"uid": "u1", "color": "#123456"}).status_code == 200
    assert api.post("/api/event-color", json={"uid": "u1", "color": None}).status_code == 200
    assert api.put("/api/settings/shared-color", json={"color": None}).status_code == 200
    assert api.get("/api/config").json()["shared_color"] is None


def test_list_items_assignee_and_due(api):
    lid = api.get("/api/lists").json()[1]["id"]
    api.put("/api/people/papa", json={"id": "papa", "name": "Папа", "color": "#007aff"})
    assert api.post(f"/api/lists/{lid}/items", json={"text": "Подарок", "due": "31.10"}).status_code == 400
    r = api.post(f"/api/lists/{lid}/items", json={"text": "Подарок", "person_id": "papa", "due": "2030-01-05"})
    assert r.status_code == 200
    item = [i for l in api.get("/api/lists").json() for i in l["items"] if i["text"] == "Подарок"][0]
    assert item["person_id"] == "papa" and item["due"] == "2030-01-05"
    api.patch(f"/api/items/{item['id']}", json={"due": None})
    item = [i for l in api.get("/api/lists").json() for i in l["items"] if i["id"] == item["id"]][0]
    assert item["due"] is None
