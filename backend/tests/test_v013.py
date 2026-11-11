"""v0.13: роли по названию, вложения и ссылки, время по карте, поиск с фильтрами, единое «Быстро», отмена."""
from datetime import datetime

from app import escorts, quick, routing


def test_only_role_by_title():
    assert escorts.only_role("Отвезти Марка в школу") == "dropoff"
    assert escorts.only_role("отвезу в сад") == "dropoff"
    assert escorts.only_role("Забрать из сада") == "pickup"
    assert escorts.only_role("Привезти Олю с тренировки") == "pickup"
    assert escorts.only_role("Отвезти и забрать") is None
    assert escorts.only_role("Бассейн") is None
    assert escorts.only_role("Приветствие") is None


def _kid_event(c, title, day="2026-11-03"):
    c.put("/api/people/mark", json={"id": "mark", "name": "Марк", "needs_escort": True})
    r = c.post("/api/event", json={"calendar": "ya/home", "title": title, "start": f"{day}T17:00:00",
                                   "end": f"{day}T18:00:00", "people": ["mark"], "location": "Бассейн Юность"})
    assert r.status_code == 200, r.text
    return r.json()


def _one(c, title, day="2026-11-03"):
    evs = c.get("/api/events", params={"start": f"{day}T00:00:00", "end": f"{day}T23:59:00"}).json()
    return next(e for e in evs if e["title"] == title)


def test_only_role_in_feed(api):
    c = api
    _kid_event(c, "Отвезти Марка в школу")
    e = _one(c, "Отвезти Марка в школу")
    assert e["escort"]["only"] == "dropoff"
    assert e["escort"]["pickup"]["skip"] and not e["escort"]["dropoff"]["skip"]
    assert e["escort_issue"] == "unassigned"
    c.post("/api/escort", json={"uid": e["uid"], "role": "dropoff", "person": "anna"})
    c.post("/api/escort", json={"uid": e["uid"], "role": "pickup", "person": "anna"})   # вторая роль игнорируется
    e = _one(c, "Отвезти Марка в школу")
    assert e["escort_issue"] is None and e["escort"]["pickup"]["person"] is None


def test_event_files_and_links(api):
    c = api
    uid = _kid_event(c, "Врач")["uid"]
    r = c.post("/api/event-files/upload", params={"uid": uid, "name": "справка.pdf"}, content=b"%PDF-1.4 test")
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["mime"] == "application/pdf" and f["inline"] and f["size"] == 13
    r = c.post("/api/event-files/upload", params={"uid": uid, "name": "../x.html"}, content=b"<script>1</script>")
    h = r.json()
    raw = c.get(f"/api/event-files/{h['id']}/raw")
    assert raw.headers["content-disposition"].startswith("attachment") and raw.headers["content-type"] == "application/octet-stream"
    assert c.get(f"/api/event-files/{f['id']}/raw").content == b"%PDF-1.4 test"
    assert c.post("/api/event-files/link", json={"uid": uid, "url": "javascript:alert(1)"}).status_code == 400
    assert c.post("/api/event-files/link", json={"uid": uid, "url": "https://example.com/t", "name": "Билет"}).status_code == 200
    assert [x["name"] for x in c.get("/api/event-files", params={"uid": uid}).json()] == ["справка.pdf", "x.html", "Билет"]
    assert _one(c, "Врач")["files"] == 3
    assert c.post("/api/event-files/upload", params={"uid": uid, "name": "a"}, content=b"").status_code == 400
    assert c.delete(f"/api/event-files/{f['id']}").json()["ok"]
    assert c.get(f"/api/event-files/{f['id']}/raw").status_code == 404
    assert c.get("/api/event-files/not-an-id/raw").status_code == 404
    assert _one(c, "Врач")["files"] == 2


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _Maps:
    """Подставная карта: геокодер знает два адреса, маршрут — 20 минут по пустой дороге."""
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None):
        self.calls += 1
        if "nominatim" in url:
            known = {"екатеринбург, малышева 1": ("60.6", "56.83"), "бассейн юность": ("60.65", "56.84")}
            hit = known.get(params["q"].lower())
            return _Resp([{"lon": hit[0], "lat": hit[1]}] if hit else [])
        return _Resp({"routes": [{"duration": 1200}]})


def test_routing_estimate_cache_and_feed(api):
    c = api
    maps = _Maps()
    assert routing.estimate("Екатеринбург, Малышева 1", "Бассейн Юность", client=maps, pause=0) == 30   # 20 мин × 1,3 → вверх до 5
    assert routing.estimate("Екатеринбург, Малышева 1", "Неизвестно где", client=maps, pause=0) is None
    db = c.core.db
    home = "Екатеринбург, Малышева 1"
    assert routing.resolve(db, home, "Бассейн Юность", client=maps, pause=0) == 30
    n = maps.calls
    assert routing.resolve(db, home, "бассейн  юность", client=maps, pause=0) == 30 and maps.calls == n   # из кэша
    assert routing.resolve(db, home, "Неизвестно где", client=maps, pause=0) is None
    assert routing.cached(db, home) == {"бассейн юность": 30}
    assert routing.cached(db, "Другой дом") == {}

    _kid_event(c, "Плавание")
    e = _one(c, "Плавание")
    assert e["escort"]["travel"]["minutes"] is None            # режим выключен
    r = c.put("/api/settings/escort", json={"map_travel": True, "map_home": home})
    assert r.status_code == 200, r.text
    e = _one(c, "Плавание")
    assert e["escort"]["travel"] == {"minutes": 30, "source": "map", "buffer": 5}
    assert e["escort"]["dropoff"]["window"][0].startswith("2026-11-03T16:25")
    # ручное время важнее карты
    c.post("/api/escort", json={"uid": e["uid"], "role": "travel", "person": "10"})
    assert _one(c, "Плавание")["escort"]["travel"]["source"] == "series"


def test_routing_refresh_only_kids_places(api):
    c = api
    maps = _Maps()
    _kid_event(c, "Плавание")
    c.post("/api/event", json={"calendar": "ya/home", "title": "Работа", "start": "2026-11-03T09:00:00",
                               "end": "2026-11-03T10:00:00", "people": ["anna"], "location": "Офис"})
    evs = c.core.events.events(c.core._parse_dt("2026-11-03T00:00:00"), c.core._parse_dt("2026-11-04T00:00:00"))
    assert routing.refresh(c.core.db, evs, "Екатеринбург, Малышева 1", client=maps, pause=0) == 1
    assert list(c.core.db.kv_get(routing.KEY)[0]) == ["бассейн юность"]
    assert routing.refresh(c.core.db, evs, "Екатеринбург, Малышева 1", client=maps, pause=0) == 0


def test_route_endpoint_needs_home(api):
    assert api.post("/api/route", json={"location": "Бассейн"}).status_code == 400


def test_search_filters(api):
    c = api
    c.put("/api/people/oleg", json={"id": "oleg", "name": "Олег"})
    for title, day, who in (("Йога", "2026-11-03", ["anna"]), ("Йога", "2026-11-20", ["oleg"]), ("Врач", "2026-11-21", ["oleg"])):
        c.post("/api/event", json={"calendar": "ya/home", "title": title, "start": f"{day}T10:00:00", "end": f"{day}T11:00:00",
                                   "people": who})
    s = lambda **p: [(e["title"], e["start"][:10]) for e in c.get("/api/search", params={"start": "2026-11-01", "end": "2026-11-30", **p}).json()]
    assert s(q="йога") == [("Йога", "2026-11-03"), ("Йога", "2026-11-20")]
    assert s(q="йога", people="oleg") == [("Йога", "2026-11-20")]
    assert s(people="oleg") == [("Йога", "2026-11-20"), ("Врач", "2026-11-21")]
    assert s(q="йога", end="2026-11-10") == [("Йога", "2026-11-03")]
    assert s(calendar="ya/other", q="йога") == []
    assert c.get("/api/search", params={"q": "й"}).json() == []
    assert c.get("/api/search", params={"q": "йога", "start": "мусор"}).status_code == 400


def test_quick_classify():
    now = datetime(2026, 11, 2, 12, 0)   # понедельник
    ppl = [{"id": "olya", "name": "Оля", "keywords": ""}]
    assert quick.classify("Купить молоко и хлеб") == ("shopping", "молоко и хлеб")
    assert quick.classify("молоко в покупки") == ("shopping", "молоко")
    assert quick.classify("Йога завтра в 18:30") == ("event", "Йога завтра в 18:30")
    assert quick.classify("Покупка машины завтра в 10")[0] == "event"
    kind, text = quick.classify("дело: оплатить кружок до пятницы")
    assert kind == "todo"
    t = quick.parse_todo(text, now, ppl)
    assert t == {"text": "Оплатить кружок", "due": "2026-11-06", "person_id": None}
    t = quick.parse_todo("позвонить врачу Оля", now, ppl)
    assert t["due"] is None and t["person_id"] == "olya"


def test_quick_endpoint_kinds(api):
    c = api
    r = c.post("/api/quick", json={"text": "купить молоко, хлеб и сыр"}).json()
    assert r["kind"] == "shopping" and r["items"] == ["молоко", "хлеб", "сыр"] and r["list_name"] == "Покупки"
    r = c.post("/api/quick", json={"text": "сделать уроки завтра"}).json()
    assert r["kind"] == "todo" and r["list_name"] == "Дела" and r["due"] and r["text"] == "Уроки"
    r = c.post("/api/quick", json={"text": "Йога завтра в 18:30"}).json()
    assert r["kind"] == "event" and r["start"] == "18:30"


def test_changes_returned_for_undo(api):
    c = api
    r = c.post("/api/event", json={"calendar": "ya/home", "title": "Йога", "start": "2026-11-03T10:00:00", "end": "2026-11-03T11:00:00"}).json()
    uid = r["uid"]
    assert len(r["changes"]) == 1
    r = c.put(f"/api/event/{uid}", json={"calendar": "ya/home", "start": "2026-11-04T10:00:00", "end": "2026-11-04T11:00:00"}).json()
    assert len(r["changes"]) == 1
    assert c.post(f"/api/changes/{r['changes'][0]}/undo").json()["ok"]
    assert _one(c, "Йога")["start"].startswith("2026-11-03T10:00")
    r = c.delete(f"/api/event/{uid}", params={"calendar": "ya/home"}).json()
    c.post(f"/api/changes/{r['changes'][0]}/undo")
    assert _one(c, "Йога")["uid"] == uid


def test_trip_alert_has_action_details(api):
    from app import reminders
    c = api
    _kid_event(c, "Плавание")
    core = c.core
    evs = core.events.events(core._parse_dt("2026-11-03T00:00:00"), core._parse_dt("2026-11-04T00:00:00"))
    now = core._parse_dt("2026-11-03T09:00:00")
    out = [r for r in reminders.build(evs, [], now, core.tz, None, names={'anna': 'Анна'}) if r["id"].startswith("alert:trip")]
    assert len(out) == 1
    trip = out[0]["trip"]
    assert trip["occurrence"] is None and [n["role"] for n in trip["need"]] == ["dropoff", "pickup"]
    assert trip["need"][0]["free"] == ["anna"]
    assert trip["names"] == {"anna": "Анна"}


def test_item_files_follow_item(api):
    c = api
    lid = c.get("/api/lists").json()[0]["id"]
    iid = c.post(f"/api/lists/{lid}/items", json={"text": "Справка в бассейн"}).json()["id"]
    f = c.post("/api/event-files/upload", params={"uid": f"item:{iid}", "name": "справка.jpg"}, content=b"\xff\xd8jpeg").json()
    c.post("/api/event-files/link", json={"uid": f"item:{iid}", "url": "https://example.com/bilet"})
    item = next(i for i in c.get("/api/lists").json()[0]["items"] if i["id"] == iid)
    assert item["files"] == 2
    path = c.core.settings.data_dir / "files" / f["id"]
    assert path.exists()
    c.delete(f"/api/items/{iid}")
    assert not path.exists() and c.get("/api/event-files", params={"uid": f"item:{iid}"}).json() == []
    # «Убрать выполненные» и удаление списка тоже чистят файлы
    iid2 = c.post(f"/api/lists/{lid}/items", json={"text": "x"}).json()["id"]
    f2 = c.post("/api/event-files/upload", params={"uid": f"item:{iid2}", "name": "a.pdf"}, content=b"%PDF").json()
    c.patch(f"/api/items/{iid2}", json={"done": True})
    c.post(f"/api/lists/{lid}/clear-done")
    assert not (c.core.settings.data_dir / "files" / f2["id"]).exists()
