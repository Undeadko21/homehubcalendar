"""Свой значок события: по UID и по названию, сброс, проверка ввода (v0.20.0)."""
from datetime import timedelta


def _iso(t, d, h):
    return (t + timedelta(days=d, hours=h)).isoformat()


def _all(api):
    t = api.core._today_start()
    r = api.get("/api/events", params={"start": t.isoformat(), "end": (t + timedelta(days=10)).isoformat()}).json()
    return r["events"] if isinstance(r, dict) else r


def _find(api, title):
    return [e for e in _all(api) if e["title"] == title]


def test_own_icon_by_uid_and_title(api):
    core = api.core
    t = core._today_start()
    a = api.post("/api/event", json={"calendar": "ya/home", "title": "Бассейн", "start": _iso(t, 1, 10), "end": _iso(t, 1, 11), "people": ["anna"]}).json()
    api.post("/api/event", json={"calendar": "ya/home", "title": "бассейн ", "start": _iso(t, 2, 10), "end": _iso(t, 2, 11), "people": ["anna"]})
    uid = a.get("uid") or _find(api, "Бассейн")[0]["uid"]
    assert api.post("/api/event-icon", json={"uid": uid, "title": "Бассейн", "icon": "🐬"}).status_code == 200
    evs = [e for e in _all(api) if e["title"].strip().lower() == "бассейн"]
    assert len(evs) == 2 and all(e.get("icon") == "🐬" for e in evs)       # второе — по названию
    api.post("/api/event-icon", json={"uid": uid, "title": "Бассейн", "icon": ""})          # без значка
    assert all(e.get("icon") == "" for e in _find(api, "Бассейн"))
    api.post("/api/event-icon", json={"uid": uid, "title": "Бассейн", "icon": None})        # снова по словам
    assert all("icon" not in e for e in _find(api, "Бассейн"))


def test_icon_only_this_event(api):
    core = api.core
    t = core._today_start()
    api.post("/api/event", json={"calendar": "ya/home", "title": "Врач", "start": _iso(t, 1, 9), "end": _iso(t, 1, 10), "people": ["anna"]})
    api.post("/api/event", json={"calendar": "ya/home", "title": "Врач", "start": _iso(t, 3, 9), "end": _iso(t, 3, 10), "people": ["anna"]})
    first = sorted(_find(api, "Врач"), key=lambda e: e["start"])[0]
    api.post("/api/event-icon", json={"uid": first["uid"], "title": "Врач", "icon": "🦷", "same_title": False})
    got = {e["uid"]: e.get("icon") for e in _find(api, "Врач")}
    assert got[first["uid"]] == "🦷" and list(got.values()).count(None) == 1


def test_icon_rejects_text(api):
    for bad in ("abc", "<b>", "🐬🐬🐬🐬🐬🐬🐬🐬🐬", "!!!", "\u202e🐬", "🐬 "):
        assert api.post("/api/event-icon", json={"uid": "x", "title": "x", "icon": bad}).status_code == 400


def test_auto_clears_title_icon_even_for_one_event(api):
    """«Авто» без галочки «для всех» тоже снимает значок, запомненный по названию, — иначе он возвращается."""
    t = api.core._today_start()
    api.post("/api/event", json={"calendar": "ya/home", "title": "Каток", "start": _iso(t, 1, 9), "end": _iso(t, 1, 10), "people": ["anna"]})
    uid = _find(api, "Каток")[0]["uid"]
    api.post("/api/event-icon", json={"uid": uid, "title": "Каток", "icon": "🏒"})
    api.post("/api/event-icon", json={"uid": uid, "title": "Каток", "icon": None, "same_title": False})
    assert "icon" not in _find(api, "Каток")[0]
    for ok in ("🏋️", "❤️", "♟️", "⭐", "👨‍👩‍👧"):
        assert api.post("/api/event-icon", json={"uid": uid, "title": "Каток", "icon": ok}).status_code == 200, ok
