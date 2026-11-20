"""Инфраструктура разработки: шум уведомлений в сводке дозора (А9)."""
from datetime import datetime


def _watch(api):
    tok = api.put("/api/access", json={"watch": True}).json()["watch"]["token"]
    return api.get("/api/watch", headers={"X-Watch-Token": tok}).json()


def test_watch_noise_counts_and_flags(api, monkeypatch):
    from app import changes
    from app.api import system
    w = _watch(api)
    assert "reminders_24h" in w["noise"] and w["noise"]["changes_24h"] == 0
    assert not any(p.startswith("Шум") for p in w["problems"])
    now = datetime.now(api.core.tz).isoformat(timespec="seconds")
    api.core.db.kv_set(changes.KEY, [{"id": str(i), "at": now, "text": "x", "people": []} for i in range(5)])
    monkeypatch.setattr(system, "NOISE_CHANGES_24H", 3)
    w = _watch(api)
    assert w["noise"]["changes_24h"] == 5
    assert any("кто что изменил" in p for p in w["problems"])
    assert "text" not in str(w["noise"])   # только счётчики, без текстов


def test_watch_noise_reminders_threshold_and_failure(api, monkeypatch):
    from app import snapshot
    from app.api import system
    monkeypatch.setattr(system, "NOISE_REMINDERS_24H", -1)   # любое число напоминаний «слишком много»
    assert any(p.startswith("Шум:") and "напоминаний" in p for p in _watch(api)["problems"])
    monkeypatch.setattr(snapshot, "build", lambda *a, **k: 1 / 0)
    w = _watch(api)
    assert w["noise"] == {"error": "ZeroDivisionError"} and not any(p.startswith("Шум") for p in w["problems"])


def test_feedback_flow_and_watch(api):
    assert api.post("/api/feedback", json={"text": "  "}).status_code == 400
    r = api.post("/api/feedback", json={"text": "Не открывается карточка бассейна", "screen": "Неделя", "version": "0.21.0",
                                        "device": "iPhone", "errors": ["TypeError: x is undefined"]}).json()
    assert api.get("/api/feedback").json()["items"][0]["id"] == r["id"]
    w = _watch(api)
    msg = [p for p in w["problems"] if p.startswith("Сообщение")]
    assert msg and "карточка бассейна" in msg[0] and "TypeError" in msg[0]
    api.delete(f"/api/feedback/{r['id']}")
    assert not [p for p in _watch(api)["problems"] if p.startswith("Сообщение")]


def test_trends_detect_slowdown_and_errors(api):
    from datetime import date, timedelta
    from app import trends
    db = api.core.db
    d0 = date(2026, 11, 1)
    for i in range(10):
        slow = i >= 7
        trends.record(db, [{"route": "GET /api/events", "p95": 900 if slow else 300, "n": 50},
                           {"route": "GET /api/config", "p95": 50, "n": 50}],
                      [{"at": f"{d0 + timedelta(days=i)}T12:00:00"}] * (6 if slow else 1), d0 + timedelta(days=i))
    p = trends.problems(db)
    assert any("GET /api/events медленнее" in x and "~900" in x and "~300" in x for x in p)
    assert any("ошибок экранов больше" in x for x in p)
    assert not any("/api/config" in x for x in p)
    w = _watch(api)
    assert w["trend"][-1]["slowest"]["GET /api/events"] == 900
    assert any(x.startswith("Тренд:") for x in w["problems"])


def test_trends_quiet_with_little_history(api):
    from app import trends
    trends.record(api.core.db, [{"route": "GET /api/events", "p95": 5000, "n": 9}], [])
    assert trends.problems(api.core.db) == []
