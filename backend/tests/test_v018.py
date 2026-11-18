"""v0.18: «Болеет / не идёт», «Пора выезжать», утренняя сводка «мой день», погода для неё."""
from datetime import date, datetime, timedelta

import httpx

from app import absences, reminders, weather


def _setup(api, day="2026-11-24"):
    api.put("/api/people/mark", json={"id": "mark", "name": "Марк", "needs_escort": True})
    swim = api.post("/api/event", json={"calendar": "ya/home", "title": "Плавание", "start": f"{day}T17:00:00",
                                        "end": f"{day}T18:00:00", "people": ["mark"], "location": "Бассейн Юность"}).json()
    api.post("/api/escort", json={"uid": swim["uid"], "occurrence": None, "role": "dropoff", "person": "anna"})
    api.post("/api/escort", json={"uid": swim["uid"], "occurrence": None, "role": "travel", "person": "20"})
    return swim


def _events(api, day="2026-11-24"):
    return api.get("/api/events", params={"start": f"{day}T00:00:00", "end": f"{day}T23:59:00"}).json()


def test_absence_marks_child_event_and_drops_trip(api):
    swim = _setup(api)
    ev = next(e for e in _events(api) if e["uid"] == swim["uid"])
    assert ev["escort"]["mode"] == "escort" and ev["escort"]["dropoff"]["person"] == "anna"
    r = api.put("/api/absences", json={"items": [{"person": "mark", "from": "2026-11-23", "to": "2026-11-25", "note": "болеет"}]})
    assert r.status_code == 200 and r.json()["items"][0]["note"] == "болеет"
    evs = _events(api)
    ev = next(e for e in evs if e["uid"] == swim["uid"])
    assert ev["absent"] == {"note": "болеет", "people": ["mark"]}
    assert ev["escort"]["mode"] == "absent" and not ev.get("escort_issue")
    assert not any(e.get("duty") for e in evs)        # поездки у взрослого нет


def test_absence_clean_rejects_garbage():
    out = absences.clean([{"person": "x", "from": "2026-01-05", "to": "2026-01-01"}, {"person": "nobody", "from": "2026-01-01"},
                          {"person": "x", "from": "плохо"}, {"person": "x", "from": "2026-01-01", "to": "2028-01-01"}], {"x"})
    assert out == [{"id": out[0]["id"], "person": "x", "from": "2026-01-01", "to": "2026-01-05", "note": "не идёт"}]


def test_partial_absence_keeps_event():
    evs = [{"id": "e", "start": "2026-11-24T10:00:00", "people": ["a", "b"], "all_day": False}]
    absences.mark(evs, [{"person": "a", "from": "2026-11-24", "to": "2026-11-24", "note": "болеет"}])
    assert "absent" not in evs[0]


def test_go_reminder_at_departure_and_morning_digest(api):
    swim = _setup(api)
    core = api.core
    now = core._parse_dt("2026-11-24T06:00:00")
    start = core._today_start().replace(year=2026, month=11, day=24)
    evs = core.events.events(start, start + timedelta(days=2))
    items = reminders.build(evs, [], now, core.tz, None, None, 1, morning=reminders.load_morning(core.db),
                            weather={date(2026, 11, 24): "−5…−1°, снег"}, names={"anna": "Анна"})
    go = next(r for r in items if r["id"].startswith("go:"))
    # дорога 20 + запас → выезд раньше начала на 25 минут (запас 5 по умолчанию)
    at = datetime.fromisoformat(go["at"])
    assert at.strftime("%H:%M") == "16:35" and go["people"] == ["anna"] and go["kind"] == "event"
    assert go["title"] == "Пора выезжать — отвезти Марка: Плавание" and "20 мин" in go["text"]
    m = next(r for r in items if r["id"] == "morning:anna:2026-11-24")
    assert m["kind"] == "event" and m["people"] == ["anna"] and m["at"].startswith("2026-11-24T07:30")
    assert m["title"].startswith("Анна, ваш день:") and "поездка" in m["title"] and "Погода: −5…−1°, снег" in m["text"]
    # опоздавшее «пора выезжать» (больше 20 минут) не отдаём
    late = reminders.build(evs, [], core._parse_dt("2026-11-24T17:30:00"), core.tz, None, None, 1, morning=reminders.load_morning(core.db))
    assert not any(r["id"].startswith("go:") for r in late)
    # ребёнку сводку не шлём
    assert not any(r["id"].startswith("morning:mark") for r in items)


def test_morning_settings_api(api):
    r = api.put("/api/settings/morning", json={"time": "06:45", "go": False})
    assert r.status_code == 200 and r.json()["time"] == "06:45" and r.json()["go"] is False
    assert api.put("/api/settings/morning", json={"time": "25:00"}).status_code == 400


def test_weather_daily_parses_and_survives_errors():
    def ok(req):
        return httpx.Response(200, json={"daily": {"time": ["2026-11-24"], "weather_code": [73], "temperature_2m_max": [-1.2],
                                                   "temperature_2m_min": [-5.6], "precipitation_probability_max": [70]}})
    weather._cache.update(at=0, key=None, days={})
    d = weather.daily({"latitude": 1, "longitude": 2}, httpx.Client(transport=httpx.MockTransport(ok)))
    assert d[date(2026, 11, 24)] == "−6…−1°, снег, осадки 70 % — тёплая обувь"
    weather._cache.update(at=0, key=None, days={})
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert weather.daily({"latitude": 1, "longitude": 2}, bad) == {}
    assert weather.daily({}, bad) == {}


def test_event_list_attach_reset_and_reminder_text(api):
    swim = _setup(api)
    r = api.put("/api/event-list", json={"uid": swim["uid"], "new_name": "Плавание: взять"})
    lst = r.json()["list"]
    for t in ("шапочка", "очки"):
        api.post(f"/api/lists/{lst['id']}/items", json={"text": t})
    t = api.core._today_start()
    past = (t - timedelta(days=7)).replace(hour=17).isoformat()
    later = (t + timedelta(days=7)).replace(hour=17).isoformat()
    future2 = (t + timedelta(days=14)).replace(hour=17).isoformat()
    lst = api.get("/api/event-list", params={"uid": swim["uid"], "occurrence": past}).json()["list"]
    api.patch(f"/api/items/{lst['items'][0]['id']}", json={"done": True})
    # то же вхождение — отметки на месте
    same = api.get("/api/event-list", params={"uid": swim["uid"], "occurrence": past}).json()["list"]
    assert sum(i["done"] for i in same["items"]) == 1
    core = api.core
    items = reminders.build(core.events.events(core._parse_dt("2026-11-24T00:00:00"), core._parse_dt("2026-11-25T00:00:00")), [],
                            core._parse_dt("2026-11-24T06:00:00"), core.tz, None, None, 1,
                            event_lists=__import__("app.eventlists", fromlist=["x"]).todo_texts(core.db))
    go = next(x for x in items if x["id"].startswith("go:"))
    assert "Взять: " in go["text"] and ("очки" in go["text"] or "шапочка" in go["text"])
    # следующее вхождение (прошлое уже прошло) — отметки сброшены
    api.patch(f"/api/items/{lst['items'][0]['id']}", json={"done": True})
    nxt = api.get("/api/event-list", params={"uid": swim["uid"], "occurrence": later}).json()["list"]
    assert not any(i["done"] for i in nxt["items"])
    # заглянули ещё на неделю вперёд, пока текущее не прошло, — ничего не сбрасывается
    api.patch(f"/api/items/{lst['items'][0]['id']}", json={"done": True})
    ahead = api.get("/api/event-list", params={"uid": swim["uid"], "occurrence": future2}).json()["list"]
    assert sum(i["done"] for i in ahead["items"]) == 1
    # список покупок привязать нельзя
    shop = api.post("/api/lists", json={"name": "Покупки"}).json()["id"]
    assert api.put("/api/event-list", json={"uid": swim["uid"], "list_id": shop}).status_code == 400
    # отвязать
    assert api.put("/api/event-list", json={"uid": swim["uid"]}).json()["list"] is None


def test_search_last_time(api):
    t = api.core._today_start()
    d1, d2 = (t - timedelta(days=200)).date().isoformat(), (t - timedelta(days=30)).date().isoformat()
    for d in (d1, d2):
        api.post("/api/event", json={"calendar": "ya/home", "title": "Стоматолог", "start": f"{d}T10:00:00", "end": f"{d}T11:00:00", "people": ["anna"]})
    r = api.get("/api/search/last", params={"q": "стомат"}).json()["items"]
    anna = next(x for x in r if x["person"] == "anna")
    assert anna["last"]["start"].startswith(d2) and anna["count"] == 2 and anna["next"] is None
    assert api.get("/api/search/last", params={"q": "ст"}).json() == {"items": []}


def test_go_for_pickup_and_absent_adult_not_free(api):
    swim = _setup(api)
    api.post("/api/escort", json={"uid": swim["uid"], "occurrence": None, "role": "pickup", "person": "anna"})
    core = api.core
    evs = core.events.events(core._parse_dt("2026-11-24T00:00:00"), core._parse_dt("2026-11-25T00:00:00"))
    items = reminders.build(evs, [], core._parse_dt("2026-11-24T06:00:00"), core.tz, None, None, 1, morning=reminders.load_morning(core.db))
    pick = next(r for r in items if r["id"].startswith("go:") and "забрать" in r["title"])
    assert pick["at"].startswith("2026-11-24T17:35")          # конец 18:00 − дорога 20 − запас 5
    # Анна уехала — назначенная ей поездка становится конфликтом, а сама она не «свободна»
    api.put("/api/absences", json={"items": [{"person": "anna", "from": "2026-11-24", "to": "2026-11-24", "note": "уехал(а)"}]})
    ev = next(e for e in _events(api) if e["uid"] == swim["uid"])
    assert ev["escort_issue"] == "conflict" and "anna" not in ev["escort"]["pickup"]["free"]


def test_child_absent_even_with_adult(api):
    api.put("/api/people/mark", json={"id": "mark", "name": "Марк", "needs_escort": True})
    ev = api.post("/api/event", json={"calendar": "ya/home", "title": "Театр", "start": "2026-11-26T18:00:00",
                                      "end": "2026-11-26T20:00:00", "people": ["mark", "anna"]}).json()
    api.put("/api/absences", json={"items": [{"person": "mark", "from": "2026-11-26", "to": "2026-11-26", "note": "болеет"}]})
    e = next(x for x in _events(api, "2026-11-26") if x["uid"] == ev["uid"])
    assert e["absent"]["people"] == ["mark"] and e["escort"]["mode"] == "absent"
