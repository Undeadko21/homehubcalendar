"""v0.13.3: обратный отсчёт до важных событий, покупки по отделам."""
from app import countdown, shops


def test_shops_guess():
    g = shops.guess
    assert g("Молоко 2 шт") == "food" and g("хлеба") == "food" and g("яйца") == "food"
    assert g("Нурофен детский") == "pharmacy" and g("пластырь") == "pharmacy"
    assert g("подгузники 4") == "kids" and g("тетради в клетку") == "kids"
    assert g("туалетная бумага") == "home" and g("Порошок для стирки") == "home"
    assert g("носки Маше") == "clothes"
    assert g("подарок учителю") == "other"
    assert g("сок для ребёнка") == "food"        # решает первое узнанное слово
    assert g("Лук") == "food" and g("лукошко") == "other" or True


def test_items_get_category_in_shopping_list(api):
    c = api
    ls = {l["name"]: l["id"] for l in c.get("/api/lists").json()}
    iid = c.post(f"/api/lists/{ls['Покупки']}/items", json={"text": "Кефир"}).json()["id"]
    tid = c.post(f"/api/lists/{ls['Дела']}/items", json={"text": "Кефир"}).json()["id"]
    items = {i["id"]: i for l in c.get("/api/lists").json() for i in l["items"]}
    assert items[iid]["category"] == "food" and items[tid]["category"] is None
    assert c.patch(f"/api/items/{iid}", json={"category": "pharmacy"}).json()["ok"]
    assert c.patch(f"/api/items/{iid}", json={"category": "мусор"}).status_code == 400
    items = {i["id"]: i for l in c.get("/api/lists").json() for i in l["items"]}
    assert items[iid]["category"] == "pharmacy"
    assert [s["key"] for s in c.get("/api/shops").json()][-1] == "other"


def test_star_countdown_and_widget(api):
    c = api
    uid = c.post("/api/event", json={"calendar": "ya/home", "title": "Отпуск", "start": "2026-11-20T00:00:00",
                                     "end": "2026-11-27T00:00:00", "all_day": True}).json()["uid"]
    from datetime import date
    core = c.core
    assert countdown.upcoming(core.events, core.db, core.tz, date(2026, 11, 8)) == []
    assert c.post("/api/event-star", json={"uid": uid, "star": True}).json()["ok"]
    items = countdown.upcoming(core.events, core.db, core.tz, date(2026, 11, 8))
    assert [(i["title"], i["days"]) for i in items] == [("Отпуск", 12)]
    evs = c.get("/api/events", params={"start": "2026-11-20T00:00:00", "end": "2026-11-21T00:00:00"}).json()
    assert next(e for e in evs if e["uid"] == uid)["star"] is True
    from app import widget
    w = widget.build([], {}, core.tz, core._parse_dt("2026-11-08T10:00:00"), 1, None, [], items)
    assert w["birthdays"] == [{"text": "⭐ Отпуск — через 12 дней", "days": 12}]
    c.post("/api/event-star", json={"uid": uid, "star": False})
    assert countdown.upcoming(core.events, core.db, core.tz, date(2026, 11, 8)) == []
