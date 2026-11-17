"""v0.15: частые события для «+», единая страница «Устройства», файлы офлайн-версии."""
import json
from datetime import datetime, timedelta

from app import devices, recent, sessions


def _e(title, start, minutes=60, uid=None, **kw):
    s = datetime.fromisoformat(start)
    return {"id": uid or title + start, "uid": uid or title + start, "title": title, "start": start,
            "end": (s + timedelta(minutes=minutes)).isoformat(), "all_day": False, "calendars": ["ya/home"], **kw}


def test_recent_prefers_repeated_titles_and_skips_series_and_foreign():
    now = datetime(2026, 11, 16, 12)
    evs = [
        _e("Врач", "2026-11-02T09:00:00", 30, people=["mark"], people_override=True, location="Поликлиника"),
        _e("Врач", "2026-11-10T09:00:00", 30, people=["mark"], people_override=True, location="Поликлиника"),
        _e("врач", "2026-11-14T15:00:00", 45),
        _e("Стрижка", "2026-11-12T18:00:00", 60),
        _e("Бассейн", "2026-11-11T17:00:00", 60, uid="pool", recurring=True),
        _e("Бассейн", "2026-11-13T17:00:00", 60, uid="pool", recurring=True),
        _e("Планёрка", "2026-11-13T10:00:00", calendars=["ics/work"]),
        _e("Секрет", "2026-11-13T10:00:00", private=True),
        _e("Отвезти", "2026-11-13T08:00:00", duty={"role": "dropoff"}),
    ]
    out = recent.build(evs, {"ya/home"}, now)
    assert [r["title"] for r in out] == ["врач", "Стрижка"]
    doc = out[0]
    assert (doc["count"], doc["minutes"], doc["time"], doc["people"], doc["location"]) == (3, 30, "09:00", ["mark"], "Поликлиника")
    assert out[1]["people"] == [] and out[1]["calendar"] == "ya/home"


def test_recent_events_api(api):
    for back in (3, 5):
        day = (api.core._today_start() - timedelta(days=back)).date().isoformat()
        r = api.post("/api/event", json={"calendar": "ya/home", "title": "Логопед",
                                         "start": f"{day}T16:00:00", "end": f"{day}T16:45:00"})
        assert r.status_code == 200, r.text
    items = api.get("/api/recent-events").json()["items"]
    assert items[0]["title"] == "Логопед" and items[0]["count"] == 2 and items[0]["minutes"] == 45
    assert all({"title", "minutes", "people", "calendar"} <= set(i) for i in items)


def test_user_agent_app_version_and_platform():
    ua = "Mozilla/5.0 (Linux; Android 14; SM-X700) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 HomeHubApp/2.10.0"
    assert sessions.app_version(ua) == "2.10.0" and sessions.platform(ua) == "android"
    ios = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) HomeHubApp/1.7.0 (iPhone)"
    assert sessions.app_version(ios) == "1.7.0" and sessions.platform(ios) == "ios"
    assert sessions.app_version("Mozilla/5.0 (Macintosh) Safari/605") is None


def test_devices_overview_joins_session_with_cloud_file():
    now = datetime(2026, 11, 16, 12)
    sess = [
        {"id": "a", "label": "Android · приложение", "via": "пароль", "ip": "1.1.1.1", "last": "2026-11-16T11:00:00",
         "current": True, "app": "2.10.0", "os": "android", "dev": {"code": "2d03107c", "model": "Samsung SM-X700"}},
        {"id": "b", "label": "Mac · Safari", "via": "QR", "ip": "2.2.2.2", "last": "2026-10-01T11:00:00", "current": False,
         "app": None, "os": "mac", "dev": None},
    ]
    cloud = {"ops_devices": [{"name": "ops-2d03107c~Samsung-SM-X700.bin", "device": "2d03107c", "model": "Samsung SM X700",
                              "modified": "2026-11-16T06:00:00+00:00"},
                             {"name": "ops-ffff.bin", "device": "ffff", "model": None, "modified": "2026-11-01T06:00:00+00:00"}],
             "ops_bad": [{"name": "ops-ffff.bin", "device": "ffff", "model": None, "why": "другой ключ", "modified": None}]}
    r = devices.overview(sess, cloud, {"android": "2.11.0", "mac": "1.6.1"}, now)
    a, b = r["devices"]
    assert a["model"] == "Samsung SM-X700" and a["update"] == "2.11.0" and a["cloud"]["ok"]
    assert any("обновите" in n["text"] for n in a["notes"])
    assert [n["text"] for n in b["notes"]] == ["Давно не заходило"] and "update" not in b
    assert [(c["code"], c["ok"]) for c in r["cloud_only"]] == [("ffff", False)]
    assert r["problems"] == 2


def test_devices_api_and_hello(api, monkeypatch):
    monkeypatch.setattr(api.core.settings, "pin", "1234", raising=False)
    ua = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/120 HomeHubApp/2.11.0"}
    assert api.post("/api/login", json={"pin": "1234"}, headers=ua).status_code == 200
    assert api.post("/api/devices/hello", json={"code": "abcd1234", "model": "Pixel 8"}, headers=ua).json()["ok"]
    d = api.get("/api/devices", headers=ua).json()
    assert d["pin"] and len(d["devices"]) == 1
    row = d["devices"][0]
    assert row["current"] and row["app"] == "2.11.0" and row["model"] == "Pixel 8" and row["os"] == "android"


def test_cloud_poll_remembers_devices(api):
    from app.cloud import CloudSync  # noqa: F401 — состояние читаем через status()
    st = api.core.cloud.status()
    assert "ops_devices" in st


def test_watch_token_only_summary(api, monkeypatch):
    monkeypatch.setattr(api.core.settings, "pin", "1234", raising=False)
    assert api.get("/api/watch").status_code == 401
    assert api.post("/api/login", json={"pin": "1234"}).status_code == 200
    assert api.get("/api/watch").status_code == 401                      # вход паролем — не токен дозора
    tok = api.put("/api/access", json={"watch": True}).json()["watch"]["token"]
    api.cookies.clear()
    h = {"X-Watch-Token": tok}
    r = api.get("/api/watch", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert {"version", "problems", "sources", "perf", "client_errors", "apps"} <= set(d)
    assert "people" not in d and "calendars" not in d
    assert api.get("/api/events?start=2026-11-01&end=2026-11-02", headers=h).status_code == 401   # больше ничего
    assert api.get("/api/system", headers=h).status_code == 401
    assert api.get("/api/watch", headers={"X-Watch-Token": "x" * 32}).status_code == 401
    # токены не взаимозаменяемы
    assert api.get("/api/widget", headers=h).status_code == 401 and api.get("/api/snapshot", headers=h).status_code == 401
    api.post("/api/login", json={"pin": "1234"})
    from app import access
    wtok = access.token(api.core.db, "widget")
    api.cookies.clear()
    assert api.get("/api/watch", headers={"X-Watch-Token": wtok}).status_code == 401
    assert api.get("/api/watch", headers={"X-Widget-Token": wtok}).status_code == 401


def test_watch_scrubs_urls_and_query(api):
    from app.api import system
    assert system._scrub("Синхронизация: 404 https://caldav.yandex.ru/calendars/ivan@yandex.ru/x/ — нет") == "Синхронизация: 404 … — нет"
    assert system._scrub("пишите ivan.petrov@yandex.ru") == "пишите …"
    api.core.perf.record("GET", "/api/search", 900, 200, "q=Врач Марк&people=mark")
    tok = api.put("/api/access", json={"watch": True}).json()["watch"]["token"]
    d = api.get("/api/watch", headers={"X-Watch-Token": tok}).json()
    body = json.dumps(d, ensure_ascii=False)
    assert "Врач Марк" not in body and '"query"' not in body and '"ip"' not in body
    assert any(x.get("params") == ["people", "q"] for x in d["perf"]["slow"])


def test_selftest_skips_calendar_without_write_permission(api, monkeypatch):
    """Яндекс отвечает 403 на создание в чужом календаре «только просмотр»: проверка помечает его и берёт следующий."""
    from app import access
    sent = []
    monkeypatch.setattr(access, "notify", lambda db, title, text, priority="default": sent.append(title) or True)
    core = api.core
    core.db.touch_calendar("ya/shared", "ya", "shared", "Аа общий от мамы", {"people": ["anna"]})   # первый по имени
    real_create = api.fake.create

    def create(rid, ics):
        if rid == "shared":
            from caldav.lib.error import AuthorizationError
            raise AuthorizationError(url="/calendars/x/shared/", reason="Forbidden")
        return real_create(rid, ics)

    api.fake.create = create
    monkeypatch.setattr(core, "_remote_id", lambda key: key.split("/", 1)[1])
    r = core.selftest_weekly()
    assert r["ok"] and r["calendar"] == "ya/home" and r["skipped"] == ["Аа общий от мамы"]
    assert sent == ["HomeHub: календарь только для чтения"]   # о пометке сообщаем, тревоги «запись не работает» нет
    assert "ya/shared" in core.write_denied()
    cfg = api.get("/api/config").json()
    shared = next(c for c in cfg["calendars"] if c["key"] == "ya/shared")
    assert shared["write_denied"] and not shared["writable"]
    assert not any("Проверка записи" in p for p in api.get("/api/system").json()["problems"])
    # ручная проверка снова: доступ дали — календарь возвращается в пишущие
    api.fake.create = real_create
    r = api.post("/api/selftest/write", json={"calendar": "ya/shared"}).json()
    assert r["ok"] and "ya/shared" not in core.write_denied()


def test_selftest_real_write_failure_still_alerts(api, monkeypatch):
    from app import access
    sent = []
    monkeypatch.setattr(access, "notify", lambda db, title, text, priority="default": sent.append(title) or True)
    api.fake.update = lambda rid, href, ics: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))   # 403 не на создании
    r = api.core.selftest_weekly()
    assert not r["ok"] and not r["denied"] and sent and "ya/home" not in api.core.write_denied()
    assert any("Проверка записи в «Дом»" in p for p in api.get("/api/system").json()["problems"])



def test_selftest_does_not_hide_family_calendar(api, monkeypatch):
    """403 в календаре, куда семья уже записывала, — настоящий сбой: не прячем, а тревожим."""
    from app import access
    from caldav.lib.error import AuthorizationError, PutError
    sent = []
    monkeypatch.setattr(access, "notify", lambda db, title, text, priority="default": sent.append(title) or True)
    core = api.core
    r = api.post("/api/event", json={"calendar": "ya/home", "title": "Йога", "start": "2026-12-01T10:00:00", "end": "2026-12-01T11:00:00"})
    assert r.status_code == 200
    api.fake.create = lambda rid, ics: (_ for _ in ()).throw(AuthorizationError(url="/c/home/", reason="Forbidden"))
    r = core.selftest_weekly()
    assert not r["ok"] and not r["denied"] and "ya/home" not in core.write_denied()
    assert sent and "не работает" in sent[-1]
    # «403» только в адресе (логин, UID) — не отказ в праве
    assert not core._forbidden(PutError(url="/calendars/ivan1403%40yandex.ru/x.ics", reason="Service Unavailable"))
    assert not core._forbidden(RuntimeError("403 Forbidden"))   # не ответ CalDAV-сервера
    assert core._forbidden(PutError(url="/x", reason="Forbidden"))


def test_write_queue_ignores_denied_mark(api):
    core = api.core
    core.db.kv_set(core.DENY_KEY, {"ya/home": "2026-11-17T10:00:00"})
    assert not core._writable("ya/home") and core._writable("ya/home", allow_denied=True)
    # очередь записи берёт цель и для помеченного календаря (настоящая make_target, без подмены из фикстуры)
    seen = []
    import importlib
    real = importlib.import_module("app.core").__dict__["_writable"]
    api.core.make_target = lambda key, allow_denied=False: seen.append(allow_denied) or api.fake
    core.ws.get_target("ya/home")
    assert seen == [True] and real("ya/home", allow_denied=True)
