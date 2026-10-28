import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import handler as h  # noqa: E402

TZ = timezone(timedelta(hours=5))
NOW = datetime(2026, 10, 27, 15, 14, tzinfo=TZ)


def ev(i, title, start, end, people, **kw):
    return {"id": i, "uid": i, "title": title, "start": start, "end": end, "all_day": False, "location": "",
            "people": people, **kw}


SNAP = {
    "generated": NOW.isoformat(),
    "people": [
        {"id": "olya", "name": "Оля", "keywords": "оленька", "needs_escort": 0},
        {"id": "oleg", "name": "Олег", "keywords": "", "needs_escort": 0},
        {"id": "masha", "name": "Маша", "keywords": "", "needs_escort": 1},
        {"id": "papa", "name": "Папа", "keywords": "", "needs_escort": 0},
        {"id": "mama", "name": "Мама", "keywords": "", "needs_escort": 0},
    ],
    "events": [
        ev("1", "Йога", "2026-10-27T19:00:00+05:00", "2026-10-27T20:00:00+05:00", ["olya"]),
        ev("2", "Созвон", "2026-10-27T14:00:00+05:00", "2026-10-27T16:00:00+05:00", ["oleg"]),
        ev("3", "Танцы", "2026-10-27T16:00:00+05:00", "2026-10-27T17:30:00+05:00", ["masha"],
           escort={"mode": "escort", "dropoff": {"person": "mama", "skip": False},
                   "pickup": {"person": None, "skip": False}}),
        ev("4", "Школа", "2026-10-29T08:00:00+05:00", "2026-10-29T13:30:00+05:00", ["masha"]),
        ev("5", "Планёрка", "2026-10-28T09:30:00+05:00", "2026-10-28T10:00:00+05:00", ["papa"]),
        {**ev("6", "Праздник", "2026-10-28T00:00:00+05:00", "2026-10-29T00:00:00+05:00", ["papa"]), "all_day": True},
    ],
}


def ask(cmd, state=None):
    req = {"request": {"command": cmd, "nlu": {"tokens": cmd.lower().split()}}, "state": {"user": state or {}}}
    return h.respond(req, SNAP, NOW)


def text(cmd, state=None):
    return ask(cmd, state)["response"]["text"]


def test_genitive_and_matching():
    assert [h.genitive(n) for n in ("Оля", "Маша", "Папа", "Олег", "Игорь", "Андрей", "Бабушка Нина")] == \
        ["Оли", "Маши", "Папы", "Олега", "Игоря", "Андрея", "Бабушки Нины"]
    assert h.find_person(SNAP, ["оли"])["id"] == "olya"
    assert h.find_person(SNAP, ["олега"])["id"] == "oleg"
    assert h.find_person(SNAP, ["оленька"])["id"] == "olya"
    assert h.find_person(SNAP, ["папы"])["id"] == "papa"
    assert h.find_person(SNAP, ["погода"]) is None


def test_next_meeting():
    assert text("когда следующая встреча оли") == "Следующая встреча у Оли: Йога, сегодня в 19:00."
    assert "в 19 часов" in ask("когда следующая встреча оли")["response"]["tts"]
    assert text("когда следующая встреча у олега").startswith("У Олега сейчас идёт: Созвон, до 16:00")
    assert text("когда следующая встреча у маши") == "Следующая встреча у Маши: Танцы, сегодня в 16:00."


def test_far_and_empty():
    assert "в среду" not in text("когда следующая встреча мамы")
    assert text("когда следующая встреча мамы") == "У Мамы ближайшие дни встреч нет."
    assert text("когда следующая встреча папы") == "Следующая встреча у Папы: Планёрка, завтра в 09:30."


def test_day_and_escort():
    assert text("что завтра у папы") == "Завтра у Папы: весь день Праздник; в 09:30 Планёрка."
    assert text("что сегодня у мамы") == "У Мамы сегодня ничего нет."
    assert text("кто отвозит машу") == "Танцы у Маши, сегодня в 16:00. Отвезти: Мама. Забрать: никто не назначен."


def test_me_and_remember():
    r = ask("я оля")
    assert r["user_state_update"] == {"person": "olya"}
    assert text("когда моя следующая встреча", {"person": "olya"}) == "Следующая встреча у вас: Йога, сегодня в 19:00."
    assert "представьтесь" in text("когда моя следующая встреча")


def test_welcome_and_unknown():
    assert text("").startswith("Привет")
    assert "Не поняла" in text("какая погода")
    assert json.dumps(ask("когда следующая встреча оли"))


def test_load_snapshot_roundtrip(monkeypatch):
    """Снимок, зашифрованный сервером, читается функцией (тот же формат, что в backend/app/cloud.py)."""
    import base64
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = os.urandom(32)
    nonce = os.urandom(12)
    blob = nonce + AESGCM(key).encrypt(nonce, json.dumps(SNAP).encode(), b"homehub-v1")
    monkeypatch.setenv("HOMEHUB_URL", "https://yadi.sk/d/x")
    monkeypatch.setenv("HOMEHUB_KEY", base64.urlsafe_b64encode(key).decode().rstrip("="))

    def fake_get(url):
        return json.dumps({"href": "https://dl/x"}).encode() if "public/resources/download" in url else blob
    monkeypatch.setattr(h, "_get", fake_get)
    h._cache.update(t=0, snap=None)
    out = h.handler({"request": {"command": "когда следующая встреча оли", "nlu": {"tokens": ["когда", "следующая", "встреча", "оли"]}}})
    assert "Не получилось" not in out["response"]["text"] and "Оли" in out["response"]["text"]


def test_full_and_double_names():
    snap = {**SNAP, "people": [{"id": "olya", "name": "Ольга Иванова", "keywords": ""},
                               {"id": "masha", "name": "Мария", "keywords": ""},
                               {"id": "papa", "name": "Анатолий", "keywords": ""}]}
    assert h.find_person(snap, ["оли"])["id"] == "olya"
    assert h.find_person(snap, ["ольги"])["id"] == "olya"
    assert h.find_person(snap, ["иванову"])["id"] == "olya"
    assert h.find_person(snap, ["маши"])["id"] == "masha"
    assert h.find_person(snap, ["толи"])["id"] == "papa"
    assert h.find_person(snap, ["анатолия"])["id"] == "papa"
    assert h.genitive("Ольга Иванова") == "Ольги Ивановой"
