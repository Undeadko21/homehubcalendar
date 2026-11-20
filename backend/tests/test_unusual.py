"""«Необычная неделя» (v0.21): пропуск серии, сдвиг времени, «не идёт», поздно у ребёнка; обычная неделя — пусто."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import unusual

TZ = ZoneInfo("Asia/Yekaterinburg")
MON = date(2026, 11, 23)
PEOPLE = [{"id": "mark", "name": "Марк", "needs_escort": True}, {"id": "anna", "name": "Анна"}]


class Fake:
    def __init__(self, evs):
        self.evs = evs

    def events(self, a, b):
        return [e for e in self.evs if a <= datetime.fromisoformat(e["start"]) < b]


def _occ(d: date, h: int, m: int = 0, uid="S", title="Бассейн", **kw):
    s = datetime.combine(d, time(h, m), TZ)
    return {"uid": uid, "id": f"{uid}{d}", "title": title, "start": s.isoformat(), "end": (s + timedelta(hours=1)).isoformat(),
            "recurring": True, "people": ["mark"], **kw}


def _series(skip=(), moved=None, absent=None, weeks=range(-4, 3)):
    out = []
    for w in weeks:
        for wd in (1, 3):   # вт и чт
            d = MON + timedelta(weeks=w, days=wd)
            if d in skip:
                continue
            h, m = 17, 0
            if moved and moved[0] == d:
                h, m = moved[1], moved[2]
            out.append(_occ(d, h, m, **({"absent": {"note": "болеет", "people": ["mark"]}} if d == absent else {})))
    return out


def test_usual_week_is_quiet():
    assert unusual.week(Fake(_series()), MON, TZ, PEOPLE) == []


def test_missing_moved_absent():
    tue, thu = MON + timedelta(days=1), MON + timedelta(days=3)
    items = unusual.week(Fake(_series(skip=[tue])), MON, TZ, PEOPLE)
    assert [i["text"] for i in items] == ["Вт: нет «Бассейн»"]
    items = unusual.week(Fake(_series(moved=(thu, 18, 30))), MON, TZ, PEOPLE)
    assert [i["text"] for i in items] == ["Чт: «Бассейн» в 18:30, обычно в 17:00"]
    items = unusual.week(Fake(_series(absent=thu)), MON, TZ, PEOPLE)
    assert [i["text"] for i in items] == ["Чт: Марк не идёт на «Бассейн» (болеет)"]


def test_whole_week_missing_is_one_line_and_ended_series_ignored():
    tue, thu = MON + timedelta(days=1), MON + timedelta(days=3)
    assert [i["text"] for i in unusual.week(Fake(_series(skip=[tue, thu])), MON, TZ, PEOPLE)] == ["«Бассейн» на этой неделе нет"]
    assert unusual.week(Fake(_series(weeks=range(-4, 0))), MON, TZ, PEOPLE) == []      # серия закончилась — не пропуск


def test_late_child_event_and_private_skipped():
    s = datetime.combine(MON + timedelta(days=4), time(20, 0), TZ)
    late = {"uid": "C", "title": "Концерт", "start": s.isoformat(), "end": (s + timedelta(hours=2)).isoformat(), "people": ["mark"]}
    adult = {**late, "uid": "D", "people": ["anna"]}
    priv = {**_occ(MON + timedelta(days=1), 17), "private": True}
    texts = [i["text"] for i in unusual.week(Fake(_series() + [late, adult, priv]), MON, TZ, PEOPLE)]
    assert texts == ["Пт: поздно — «Концерт» до 22:00 (Марк)"]


def test_api(api):
    r = api.get("/api/unusual", params={"start": "2026-11-25"}).json()
    assert r["week"] == "2026-11-23" and isinstance(r["items"], list)
    assert api.get("/api/unusual", params={"start": "x"}).status_code == 400


def test_monday_morning_digest_line():
    from app import reminders
    tue = MON + timedelta(days=1)
    odd = unusual.mondays(Fake(_series(skip=[tue])), MON - timedelta(days=1), 3, TZ, PEOPLE)
    assert odd == {MON: ["Вт: нет «Бассейн»"]}
    morning = {"enabled": True, "time": "07:30", "people": ["anna"], "go": True, "changes": True}
    now = datetime.combine(MON - timedelta(days=1), time(20), TZ)
    items = reminders._morning([], MON - timedelta(days=1), now, TZ, None, morning, {}, 2, {"anna": "Анна"}, odd)
    mon = next(i for i in items if i["id"] == f"morning:anna:{MON}")
    assert "Необычно на неделе: Вт: нет «Бассейн»" in mon["text"]
    assert all("Необычно" not in i["text"] for i in items if i is not mon)


def test_multiday_child_event_not_late_and_single_move_is_moved():
    s = datetime.combine(MON + timedelta(days=4), time(10, 0), TZ)
    camp = {"uid": "L", "title": "Лагерь", "start": s.isoformat(), "end": (s + timedelta(days=2, hours=5)).isoformat(), "people": ["mark"]}
    thu = MON + timedelta(days=3)
    moved = {"uid": "X1", "title": "Бассейн", "start": datetime.combine(thu, time(18, 30), TZ).isoformat(),
             "end": datetime.combine(thu, time(19, 30), TZ).isoformat(), "people": ["mark"]}
    texts = [i["text"] for i in unusual.week(Fake(_series(skip=[thu]) + [camp, moved]), MON, TZ, PEOPLE)]
    assert texts == ["Чт: «Бассейн» в 18:30, обычно в 17:00"]
    fri = MON + timedelta(days=4)
    other_day = {**moved, "start": datetime.combine(fri, time(17), TZ).isoformat(), "end": datetime.combine(fri, time(18), TZ).isoformat()}
    texts = [i["text"] for i in unusual.week(Fake(_series(skip=[thu]) + [other_day]), MON, TZ, PEOPLE)]
    assert texts == ["Чт: «Бассейн» перенесено на Пт 17:00"]
