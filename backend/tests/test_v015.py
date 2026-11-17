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
