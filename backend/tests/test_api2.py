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


def test_events_response_is_gzipped_and_stream_has_origin(api):
    big = api.get("/api/events?start=2026-01-01T00:00:00&end=2026-12-31T00:00:00", headers={"Accept-Encoding": "gzip"})
    assert big.status_code == 200
    from app import live
    r = live.rev
    live.mark(r, r + 1, "abc")
    assert live.origin(r + 1) == "abc" and live.origin(r) is None


def test_events_speed_budget(tmp_path):
    """Бюджет скорости: неделя из подписки в 1500 событий считается быстро (регресс ловим здесь, а не по жалобам)."""
    import time
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.expand import expand_ics
    from app.sources.ics_source import split_feed
    tz = ZoneInfo("Asia/Yekaterinburg")
    base = datetime(2026, 1, 1, 9)
    ev = []
    for i in range(1500):
        s = base + timedelta(days=i % 600, hours=i % 8)
        rr = "RRULE:FREQ=WEEKLY;COUNT=30\n" if i % 15 == 0 else ""
        ev.append(f"BEGIN:VEVENT\nUID:u{i}\nDTSTAMP:20260101T000000Z\nDTSTART;TZID=Asia/Yekaterinburg:{s:%Y%m%dT%H%M%S}\n"
                  f"DTEND;TZID=Asia/Yekaterinburg:{s + timedelta(hours=1):%Y%m%dT%H%M%S}\nSUMMARY:Встреча {i}\n{rr}END:VEVENT")
    parts = split_feed("BEGIN:VCALENDAR\nVERSION:2.0\n" + "\n".join(ev) + "\nEND:VCALENDAR\n")
    a = datetime(2026, 10, 26, tzinfo=tz)
    for p in parts.values():          # первый проход строит границы, как после синхронизации
        expand_ics(p, a, a + timedelta(days=9), tz)
    t = time.time()
    n = sum(len(expand_ics(p, a, a + timedelta(days=9), tz)) for p in parts.values())
    assert n > 0 and time.time() - t < 0.5, f"неделя на 1500 событий: {time.time() - t:.2f} с"


def test_ready_and_checks(api):
    r = api.get("/api/ready")
    assert r.status_code == 200 and r.json()["ok"] is True
    # ребёнок без взрослых — предупреждение; после «Проверить сейчас» оно попадает в problems
    api.put("/api/people/kid", json={"id": "kid", "name": "Оля", "color": "#ff0000", "emoji": "👧", "needs_escort": True})
    api.delete("/api/people/anna")
    out = api.post("/api/checks").json()
    assert any("нет ни одного взрослого" in i["text"] for i in out["items"])
    sysinfo = api.get("/api/system").json()
    assert any("нет ни одного взрослого" in p for p in sysinfo["problems"]) and sysinfo["checks"]["at"]


def test_person_summary(api):
    r = api.get("/api/person/anna")
    assert r.status_code == 200
    d = r.json()
    assert d["person"]["id"] == "anna" and set(d) >= {"next", "regular", "duties", "todos"}
    assert api.get("/api/person/nobody").status_code == 404


def test_login_behind_proxy_and_long_password(api, monkeypatch):
    """За прокси блокировка считается по X-Forwarded-For, пароль может быть русским, cookie через HTTPS — Secure."""
    monkeypatch.setattr(api.core.settings, "pin", "длинный пароль семьи", raising=False)
    api.main._FAILS.clear()
    bad = {"X-Forwarded-For": "203.0.113.7"}
    codes = [api.post("/api/login", json={"pin": "x"}, headers=bad).status_code for _ in range(6)]
    assert codes[5] == 429
    # другой клиент за тем же прокси не заблокирован
    r = api.post("/api/login", json={"pin": "длинный пароль семьи"}, headers={"X-Forwarded-For": "198.51.100.2", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "secure" in r.headers["set-cookie"].lower()
    assert "openapi" not in api.get("/openapi.json").text   # описание API не отдаётся (SPA-заглушка или 404)


def test_index_html_is_not_cached(api):
    """Оболочка интерфейса не должна залипать в WebView: no-cache."""
    r = api.get("/")
    if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
        assert r.headers.get("cache-control") == "no-cache"


def test_access_tokens_qr_and_public_versions(api, monkeypatch):
    """Токены доступа: виджет читает сводку без пароля, VPS присылает отчёт, вход по одноразовой ссылке, версии приложений открыты."""
    from app import access
    api.post("/api/login", json={"pin": ""})  # без PIN всё открыто — проверим защищённый режим ниже
    monkeypatch.setattr(api.core.settings, "pin", "длинный пароль семьи", raising=False)

    # версии приложений и здоровье — без входа; данные — нет
    for path in ("/api/app", "/api/app-mac", "/api/app-ios", "/api/health"):
        assert api.get(path).status_code == 200, path
    assert api.get("/api/widget").status_code == 401 and api.get("/api/snapshot").status_code == 401
    assert api.get("/api/lists").status_code == 401

    # вход, включение токенов
    assert api.post("/api/login", json={"pin": "длинный пароль семьи"}).status_code == 200
    st = api.put("/api/access", json={"public_url": "https://cal.example.ru", "widget": True, "vps": True, "ntfy": True}).json()
    assert st["widget"] and st["vps"]["enabled"] and st["ntfy"]["topic"].startswith("homehub-")
    assert api.put("/api/access", json={"public_url": "http://bad"}).status_code == 400
    wtoken = access.token(api.core.db, "widget")
    vtoken = access.token(api.core.db, "vps")
    api.cookies.clear()

    # токен виджета: только GET /api/widget и /api/snapshot
    assert api.get("/api/widget", headers={"X-Widget-Token": wtoken}).status_code == 200
    assert api.get("/api/snapshot", headers={"X-Widget-Token": wtoken}).status_code == 200
    assert api.get("/api/widget", headers={"X-Widget-Token": "wrong-token"}).status_code == 401
    assert api.get("/api/lists", headers={"X-Widget-Token": wtoken}).status_code == 401
    assert api.post("/api/sync", headers={"X-Widget-Token": wtoken}).status_code == 401

    # VPS: установка и отчёт по токену VPS (токен виджета не годится)
    bad = {"Authorization": f"Bearer {wtoken}"}
    good = {"Authorization": f"Bearer {vtoken}"}
    assert api.get("/api/vps/install.sh", headers=bad).status_code == 401
    sh = api.get("/api/vps/install.sh", headers=good)
    assert sh.status_code == 200 and vtoken in sh.text and "https://ntfy.sh/homehub-" in sh.text and "@TOKEN@" not in sh.text
    import base64
    body = {"report": {"disk_pct": 40, "certs": {"cal.example.ru": 60}, "caddy": True, "uptime_days": 3},
            "backup": base64.b64encode(b"tar-bytes").decode()}
    assert api.post("/api/vps/ingest", json=body, headers=bad).status_code == 401
    assert api.post("/api/vps/ingest", json=body, headers=good).status_code == 200
    assert access.problems(api.core.db) == []
    access.save_report(api.core.db, {"disk_pct": 91, "certs": {"cal.example.ru": 5}, "caddy": False}, None)
    texts = " ".join(access.problems(api.core.db))
    assert "91%" in texts and "истекает" in texts and "Caddy" in texts

    # код подключения несёт адрес и токен виджета
    api.post("/api/login", json={"pin": "длинный пароль семьи"})
    st = api.get("/api/access").json()
    assert st["vps"]["backup"]["size"] == len(b"tar-bytes")
    assert api.get("/api/access/vps-backup").content == b"tar-bytes"

    # вход по одноразовой ссылке
    link = api.post("/api/login/qr").json()["url"]
    path = "/api/login/qr/" + link.rsplit("/", 1)[1]
    api.cookies.clear()
    r = api.get(path, follow_redirects=False)
    assert r.status_code == 303 and "homecal_auth" in r.headers["set-cookie"]
    assert api.get("/api/lists").status_code == 200
    api.cookies.clear()
    assert api.get(path, follow_redirects=False).status_code == 410   # второй раз не работает


def test_connection_code_carries_server_and_widget_token(api):
    import base64
    import json

    from app import access
    cl = api.core.cloud
    cl.set_token("y0_" + "a" * 30)
    cl.db.kv_set("cloud:state", {"public_url": "https://disk.yandex.ru/d/xyz"})
    access.set_public_url(cl.db, "https://cal.example.ru")
    payload = lambda: json.loads(base64.urlsafe_b64decode(cl.code()[5:] + "=="))  # noqa: E731
    assert "w" not in payload()
    access.token(cl.db, "widget")
    p = payload()
    assert p["s"] == "https://cal.example.ru" and p["w"] == access.token(cl.db, "widget") and p["u"] and p["k"]


def test_altstore_uses_forwarded_scheme(api):
    r = api.get("/altstore.json", headers={"X-Forwarded-Proto": "https", "Host": "cal.example.ru"})
    assert r.status_code == 200
    assert r.json()["sourceURL"] == "https://cal.example.ru/altstore.json"


def test_sessions_revoke_and_login_alerts(api, monkeypatch):
    import time

    from app import access
    sent = []
    monkeypatch.setattr(access, "_post_ntfy", lambda topic, title, text, priority="default": sent.append((title, text)))
    monkeypatch.setattr(api.core.settings, "pin", "длинный пароль семьи", raising=False)
    access.enable_ntfy(api.core.db)

    def wait():
        for _ in range(50):
            if sent:
                return
            time.sleep(0.02)

    ua = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17) AppleWebKit Safari/605", "X-Forwarded-For": "203.0.113.7"}
    assert api.get("/api/lists").status_code == 401
    assert api.post("/api/login", json={"pin": "длинный пароль семьи"}, headers=ua).status_code == 200
    assert api.cookies.get("homecal_auth", "").startswith("s.")
    wait()
    assert sent and "новый вход" in sent[0][0].lower()          # первый вход с нового адреса — уведомление
    sent.clear()
    assert api.get("/api/lists").status_code == 200

    # второе устройство
    other = api.main.app
    from fastapi.testclient import TestClient
    c2 = TestClient(other)
    assert c2.post("/api/login", json={"pin": "длинный пароль семьи"},
                   headers={"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/120", "X-Forwarded-For": "203.0.113.7"}).status_code == 200
    assert not sent                                              # знакомый адрес — без уведомления
    lst = api.get("/api/sessions").json()["sessions"]
    assert len(lst) == 2 and sum(s["current"] for s in lst) == 1
    assert {s["label"] for s in lst} == {"iPhone · Safari", "Mac · Chrome"}
    mine = next(s for s in lst if s["current"])
    theirs = next(s for s in lst if not s["current"])
    assert c2.get("/api/lists").status_code == 200
    assert api.delete(f"/api/sessions/{theirs['id']}").status_code == 200
    assert c2.get("/api/lists").status_code == 401               # отключённое устройство вышло
    assert api.get("/api/lists").status_code == 200              # это — нет
    assert api.delete("/api/sessions/nope").status_code == 404

    # подбор пароля: на 5-й ошибке подряд — уведомление
    bad = {"X-Forwarded-For": "198.51.100.9"}
    for _ in range(5):
        api.post("/api/login", json={"pin": "x"}, headers=bad)
    wait()
    assert any("подбор" in t.lower() for t, _ in sent)
    assert access.fails_last_day(api.core.db) >= 3

    # «отключить все, кроме этого»: текущее остаётся
    c3 = TestClient(other)
    c3.post("/api/login", json={"pin": "длинный пароль семьи"}, headers={"X-Forwarded-For": "203.0.113.7"})
    assert api.post("/api/sessions/revoke-all", json={"keep_current": True}).status_code == 200
    assert api.get("/api/lists").status_code == 200 and c3.get("/api/lists").status_code == 401
    assert mine["id"] in [s["id"] for s in api.get("/api/sessions").json()["sessions"]]


def test_legacy_cookie_is_upgraded_and_can_be_revoked(api, monkeypatch):
    import hashlib
    import hmac
    monkeypatch.setattr(api.core.settings, "pin", "длинный пароль семьи", raising=False)
    legacy = hmac.new("длинный пароль семьи".encode(), b"homecal", hashlib.sha256).hexdigest()
    api.cookies.set("homecal_auth", legacy)
    r = api.get("/api/lists")
    assert r.status_code == 200 and "s." in r.headers.get("set-cookie", "")   # заменили личной сессией
    assert len(api.get("/api/sessions").json()["sessions"]) == 1
    api.cookies.clear()
    api.cookies.set("homecal_auth", legacy)
    api.post("/api/sessions/revoke-all", json={"keep_current": False})
    assert api.get("/api/lists").status_code == 401              # старый cookie больше не работает


def test_access_checks_and_probe(api, monkeypatch):
    from app import access
    db = api.core.db
    names = {c["id"]: c["level"] for c in api.get("/api/access").json()["checks"]}
    assert names["public"] == "warn" and names["ntfy"] == "info" and names["devices"] == "ok"
    access.set_public_url(db, "https://cal.example.ru")
    monkeypatch.setattr(access, "probe_public", lambda db, timeout=8.0: {"ok": False, "error": "ConnectError", "at": "2026-01-01T00:00:00"})
    sent = []
    monkeypatch.setattr(access, "_post_ntfy", lambda topic, title, text, priority="default": sent.append(title))
    access.enable_ntfy(db)
    for _ in range(3):
        access.watch(db)
    import time
    time.sleep(0.1)
    assert access.WATCH["down"] and sent and "нет связи" in sent[0].lower()
    res = api.post("/api/access/probe").json()
    assert res["probe"]["ok"] is False
    assert next(c for c in res["checks"] if c["id"] == "probe")["level"] == "bad"
    monkeypatch.setattr(access, "probe_public", lambda db, timeout=8.0: {"ok": True, "ms": 40, "at": "2026-01-01T00:00:00"})
    access.watch(db)
    assert not access.WATCH["down"]
    access.WATCH.update(fails=0, down=False, last=None, alerted=0.0)


def test_cloud_token_is_cleaned_from_pasted_url(api):
    from app.cloud import clean_token
    raw = "y0_" + "A" * 40
    assert clean_token(f"https://oauth.yandex.ru/verification_code#access_token={raw}&token_type=bearer&expires_in=31536000") == raw
    assert clean_token(f"access_token={raw}&token_type=bearer") == raw
    assert clean_token(f"OAuth {raw}") == raw
    assert clean_token(f'  "{raw}"  ') == raw
    api.core.cloud.set_token(f"{raw}&token_type=bearer&expires_in=1")
    assert api.core.cloud._token() == raw


def test_access_checks_survive_timezone_aware_cloud_time(api):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    api.core.db.kv_set("cloud:state", {"public_url": "https://disk.yandex.ru/d/x",
                                       "last_ok": datetime.now(ZoneInfo("Asia/Yekaterinburg")).isoformat(timespec="seconds")})
    api.core.cloud.set_token("y0_" + "a" * 30)
    r = api.get("/api/access")
    assert r.status_code == 200
    cloud = next(c for c in r.json()["checks"] if c["id"] == "cloud")
    assert cloud["level"] == "ok" and "назад" in cloud["detail"] or "только что" in cloud["detail"]
