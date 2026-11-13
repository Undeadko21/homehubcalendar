"""v0.14: мягкое обновление ленты, одна сборка на параллельные запросы, команды из облака, подписки, сторож версии, вложения в копии."""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from app import versionwatch
from app.cloud import CloudError, CloudSync, encrypt


def _ev(c, title, day="2026-11-03"):
    r = c.post("/api/event", json={"calendar": "ya/home", "title": title, "start": f"{day}T10:00:00", "end": f"{day}T11:00:00"})
    assert r.status_code == 200, r.text
    return r.json()["uid"]


def _today_range(core):
    start = core._today_start()
    return start, start + timedelta(days=1)


def test_refresh_serves_old_feed_until_new_is_ready(api):
    """Синхронизация не должна заставлять экран ждать: пока новая лента собирается, отдаётся прежняя."""
    c = api
    svc = c.core.events
    a, z = _today_range(c.core)
    svc.warm()
    before = svc.events(a, z)
    gate, entered = threading.Event(), threading.Event()
    real = svc._compose

    def slow(s, e):
        entered.set()
        gate.wait(5)
        return real(s, e) + [{"marker": True, "start": a.isoformat(), "end": z.isoformat(), "all_day": False}]

    svc._compose = slow
    try:
        svc.refresh()
        assert entered.wait(3)
        t0 = time.perf_counter()
        assert svc.events(a, z) == before                    # прежние данные, без ожидания сборки
        assert svc.events(a, a + timedelta(hours=5)) is not None
        assert time.perf_counter() - t0 < 0.5
        gate.set()
        for _ in range(100):
            if any(e.get("marker") for e in svc.events(a, z)):
                break
            time.sleep(0.05)
        assert any(e.get("marker") for e in svc.events(a, z))  # новая лента подменила старую
    finally:
        svc._compose = real
        gate.set()


def test_parallel_requests_build_once(api):
    """После сброса кэша одинаковые запросы открытого экрана считают ленту один раз, а не каждый сам."""
    c = api
    svc = c.core.events
    a, z = _today_range(c.core)
    svc.invalidate()
    svc._schedule_warm = lambda *x, **k: None
    calls = []
    real = svc._compose

    def counting(s, e):
        calls.append(1)
        time.sleep(0.15)
        return real(s, e)

    svc._compose = counting
    try:
        out = []
        ts = [threading.Thread(target=lambda: out.append(svc.events(a, z))) for _ in range(6)]
        [t.start() for t in ts]
        [t.join(5) for t in ts]
        assert len(out) == 6 and len(calls) == 1
    finally:
        svc._compose = real


def test_failed_source_does_not_reset_feed(api):
    c = api
    eng = c.core.engine
    hits = []
    eng.on_change = lambda: hits.append(1)
    eng._runs = 5                                   # не первый запуск
    eng.sources = [{"id": "broken", "type": "ics", "url": "/nonexistent/file.ics"}]
    rep = eng.run()
    assert rep["broken"]["ok"] is False and hits == []


def test_ics_retries_transient_errors(monkeypatch):
    import httpx
    from app.sources import ics_source
    monkeypatch.setattr(ics_source, "RETRY_PAUSES", (0, 0))
    n = {"i": 0}

    def get(url, **kw):
        n["i"] += 1
        if n["i"] == 1:
            raise httpx.ConnectError("boom")
        if n["i"] == 2:
            return httpx.Response(503)
        return httpx.Response(200, text="BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:1\nDTSTART:20261103T100000\nSUMMARY:X\nEND:VEVENT\nEND:VCALENDAR")

    monkeypatch.setattr(ics_source.httpx, "get", get)
    cals = ics_source.IcsSource({"id": "f", "type": "ics", "url": "https://example.com/a.ics"}).fetch()
    assert n["i"] == 3 and len(cals[0].objects) == 1
    n["i"] = -10
    monkeypatch.setattr(ics_source.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("x")))
    try:
        ics_source.IcsSource({"id": "f", "type": "ics", "url": "https://example.com/a.ics"}).fetch()
        assert False
    except RuntimeError as e:
        assert "соединиться" in str(e) and "example.com" not in str(e)


def test_sync_problem_only_when_persistent(api):
    c = api
    db = c.core.db
    probs = lambda: [p for p in c.get("/api/system").json()["problems"] if "Синхронизация feed" in p]
    db.set_sync_status("feed", ok=True, count=1)
    db.set_sync_status("feed", ok=False, error="Нет связи с сервером подписки (ConnectError)")
    assert probs() == []                                      # разовый сбой — молчим
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    with db.tx() as con:
        con.execute("UPDATE sync_status SET last_ok=? WHERE source_id='feed'", (old,))
    assert len(probs()) == 1 and "последний раз удалось" in probs()[0]


class _Disk:
    """Подставной Диск с файлами команд."""
    files: dict = {}
    fail_list = False

    def __init__(self, token):
        pass

    def list_ops(self):
        if _Disk.fail_list:
            raise TimeoutError("slow")
        return [{"name": n, "md5": str(hash(b))} for n, b in _Disk.files.items() if n.startswith("ops-")]

    def download(self, name):
        return _Disk.files[name]

    def rm(self, path):
        _Disk.files.pop(path.rsplit("/", 1)[1], None)


def test_bad_ops_file_does_not_block_others(api):
    c = api
    db = c.core.db
    cloud = CloudSync(db, lambda: {}, _Disk)
    cloud.set_token("y0_testtoken_0123456789abcdef")
    st = cloud._state(); st["public_url"] = "https://disk.example/x"; db.kv_set("cloud:state", st)
    good = encrypt(cloud.key(), json.dumps([{"id": "a1", "t": 1, "type": "item_add", "list_id": 1, "text": "Молоко"}]).encode())
    _Disk.files = {"ops-oldphone.bin": b"\x00" * 60, "ops-once-zzz.bin": b"garbage-garbage-garbage-garbage", "ops-phone2.bin": good}
    _Disk.fail_list = False
    got = []
    assert cloud.poll_ops(lambda ops: got.extend(ops) or True) is True
    assert [o["id"] for o in got] == ["a1"]                   # хороший файл применён, несмотря на два плохих
    s = cloud.status()
    assert s["ops_error"] is None
    assert [b["device"] for b in s["ops_bad"]] == ["oldphone"] and "подключите это устройство заново" in s["ops_bad"][0]["why"]
    assert "ops-once-zzz.bin" not in _Disk.files              # одноразовый мусор удалён
    got.clear()
    cloud.poll_ops(lambda ops: got.extend(ops) or True)
    assert got == [] and len(cloud.status()["ops_bad"]) == 1  # к тем же файлам не возвращаемся
    # устройство переподключили — файл стал читаться, замечание уходит
    _Disk.files["ops-oldphone.bin"] = encrypt(cloud.key(), json.dumps([{"id": "b1", "t": 2, "type": "item_add", "list_id": 1, "text": "Хлеб"}]).encode())
    cloud.poll_ops(lambda ops: got.extend(ops) or True)
    assert [o["id"] for o in got] == ["b1"] and cloud.status()["ops_bad"] == []
    # сеть: понятно, что именно не так, и ничего не помечается прочитанным
    _Disk.fail_list = True
    cloud.poll_ops(lambda ops: True)
    assert cloud.status()["ops_error"] == "Не удалось прочитать команды из облака (TimeoutError)"
    _Disk.fail_list = False
    # «Убрать»
    _Disk.files["ops-tablet.bin"] = b"\x01" * 50
    cloud.poll_ops(lambda ops: True)
    assert [b["name"] for b in cloud.status()["ops_bad"]] == ["ops-tablet.bin"]
    cloud.forget_ops("ops-tablet.bin")
    assert cloud.status()["ops_bad"] == [] and "ops-tablet.bin" not in _Disk.files
    try:
        cloud.forget_ops("ops-phone2.bin")
        assert False
    except CloudError:
        pass


class _Resp:
    def __init__(self, sha, when, code=200):
        self.status_code, self._d = code, {"sha": sha, "commit": {"committer": {"date": when}}}

    def json(self):
        return self._d


class _GH:
    def __init__(self, sha, when, code=200):
        self.r = _Resp(sha, when, code)

    def get(self, url, **kw):
        assert "/commits/main" in url
        return self.r


def test_version_watch(api, monkeypatch):
    db = api.core.db
    sent = []
    monkeypatch.setattr(versionwatch.access, "notify", lambda *a, **k: sent.append(a[1]))
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    assert versionwatch.check(db, "", now, _GH("f" * 40, "2026-11-10T00:00:00Z")) == {}           # не образ — не проверяем
    assert not versionwatch.check(db, "abc1234", now, _GH("abc1234" + "0" * 33, "2026-11-10T00:00:00Z"))["behind"]
    assert not versionwatch.check(db, "abc1234", now, _GH("d" * 40, "2026-11-13T11:30:00Z"))["behind"]  # свежий коммит — ждём
    assert versionwatch.problems(db, "abc1234") == [] and sent == []
    assert versionwatch.check(db, "abc1234", now, _GH("d" * 40, "2026-11-13T09:00:00Z"))["behind"]
    versionwatch.check(db, "abc1234", now, _GH("d" * 40, "2026-11-13T09:00:00Z"))
    assert len(sent) == 1                                        # одно уведомление на коммит
    assert "ddddddd" in versionwatch.problems(db, "abc1234")[0]
    versionwatch.check(db, "abc1234", now, _GH("", "", 500))     # GitHub недоступен — вывод не меняется
    assert versionwatch.problems(db, "abc1234")
    assert versionwatch.problems(db, "ddddddd") == []            # обновились
    assert any("Сервер не обновляется" in p for p in api.get("/api/system").json()["problems"]) is False  # в тестах BUILD пуст


def test_attachments_in_backup_and_vps(api):
    import gzip
    from app import access, backup as bk
    c = api
    uid = _ev(c, "Врач")
    f1 = c.post("/api/event-files/upload", params={"uid": uid, "name": "справка.pdf"}, content=b"%PDF-1.4 hello").json()
    c.post("/api/event-files/link", json={"uid": uid, "url": "https://example.com/t"})

    class Disk:
        dirs: dict = {}

        def __init__(self, token):
            pass

        def mkdir(self, p):
            Disk.dirs.setdefault(p, {})

        def upload(self, data, path):
            d, n = path.rsplit("/", 1)
            Disk.dirs.setdefault(d, {})[n] = data

        def ls(self, p):
            return [{"name": n} for n in Disk.dirs.get(p, {})]

        def rm(self, path):
            d, n = path.rsplit("/", 1)
            Disk.dirs.get(d, {}).pop(n, None)

    core = c.core
    core.cloud.set_token("y0_testtoken_0123456789abcdef")
    svc = bk.BackupService(core.db, core.cloud, core.tz, Disk)
    Disk.dirs = {bk.FILES_DIR: {"0" * 32: b"old"}}             # вложение, которого дома уже нет
    st = svc.run()
    assert st["last_error"] is None and st["files"] == {"count": 1, "sent": 1, "bytes": 14, "error": None}
    assert list(Disk.dirs[bk.FILES_DIR]) == [f1["id"]]
    assert bk.unseal(core.cloud.key(), Disk.dirs[bk.FILES_DIR][f1["id"]]) == b"%PDF-1.4 hello"
    assert svc.run()["files"]["sent"] == 0                       # второй раз ничего не грузим
    # агент VPS
    c.put("/api/access", json={"public_url": "https://cal.example.ru", "vps": True})
    h = {"Authorization": f"Bearer {access.token(core.db, 'vps')}"}
    assert c.get("/api/vps/files", headers=h).text == f1["id"] + "\n"
    blob = c.get(f"/api/vps/files/{f1['id']}", headers=h).content
    assert bk.unseal(core.cloud.key(), blob) == b"%PDF-1.4 hello"
    assert c.get("/api/vps/files/nope", headers=h).status_code == 404
    assert c.get("/api/vps/files", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_feed_named_in_problems_and_link_can_be_changed(api, tmp_path):
    c = api
    good = tmp_path / "a.ics"
    good.write_text("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:w1\nDTSTART:20261103T100000\nSUMMARY:Планёрка\nEND:VEVENT\nEND:VCALENDAR", encoding="utf-8")
    c.core.db.kv_set("ics:feeds", [{"id": "ics1", "name": "Работа Оли", "url": str(good), "people": ["anna"]}])
    c.core.engine.run(full=True)
    f = c.get("/api/feeds").json()[0]
    assert f["name"] == "Работа Оли" and f["last_ok"] and f["last_error"] is None and "url" not in f
    # название вместо «ics1» в замечаниях
    c.core.db.set_sync_status("ics1", ok=False, error="Ссылка больше не работает (ответ 404)")
    with c.core.db.tx() as con:
        con.execute("UPDATE sync_status SET last_ok='2026-01-01T00:00:00+00:00' WHERE source_id='ics1'")
    p = [x for x in c.get("/api/system").json()["problems"] if "Синхронизация" in x]
    assert p and "«Работа Оли»" in p[0] and "ics1:" not in p[0]
    assert c.get("/api/feeds").json()[0]["last_error"].startswith("Ссылка больше не работает")
    # плохая новая ссылка не затирает прежнюю
    r = c.put("/api/feeds", json={"id": "ics1", "url": "https://127.0.0.1:1/x.ics"})
    assert r.status_code == 400 and "прежняя оставлена" in r.json()["detail"]
    assert c.core.engine.feeds()[0]["url"] == str(good)
    # только название — ссылка, владельцы на месте
    r = c.put("/api/feeds", json={"id": "ics1", "name": "Trassir Оля", "url": ""}).json()
    feed = c.core.engine.feeds()[0]
    assert r["result"]["ok"] and feed == {"id": "ics1", "name": "Trassir Оля", "url": str(good), "people": ["anna"]}
