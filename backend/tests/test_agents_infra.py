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
