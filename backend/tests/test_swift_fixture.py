"""Снимок, который сервер отдаёт приложениям (`/api/snapshot`, он же шифрованный файл на Диске), и его копия для тестов Swift.

Swift здесь не запускается — его проверяет GitHub Actions. Чтобы приложения и сервер не разошлись молча:
  * `macos/Tests/HomeHubCoreTests/Fixtures/snapshot.json` — настоящий вывод `snapshot.build` на наборе данных ниже;
  * этот тест сравнивает ФОРМУ свежего снимка с файлом: ключ, который есть в файле, но пропал на сервере или сменил тип, — ошибка
    (старые приложения на нём сломаются); новые необязательные поля — можно, но файл стоит обновить;
  * `UPDATE_FIXTURES=1 python -m pytest tests/test_swift_fixture.py` — перезаписать файл. Swift-тесты (SnapshotFixtureTests) читают его же.
"""
import json
import os
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "macos/Tests/HomeHubCoreTests/Fixtures/snapshot.json"


def _shape(x):
    if isinstance(x, dict):
        return {k: _shape(v) for k, v in x.items()}
    if isinstance(x, list):
        out = None
        for it in x:
            out = _shape(it) if out is None else _merge(out, _shape(it))
        return {"[]": out if out is not None else "null"}
    if x is None:
        return "null"
    if isinstance(x, bool):
        return "bool"
    if isinstance(x, (int, float)):
        return "number"
    return "str"


def _merge(a, b):
    if a == b:
        return a
    if a == "null":
        return b
    if b == "null":
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: _merge(a[k], b[k]) if k in a and k in b else a.get(k, b.get(k)) for k in {*a, *b}}
    return f"{a}|{b}"


def _lost(old, new, path="") -> list[str]:
    """Что было в файле, но пропало или поменяло тип в свежем снимке."""
    if old == "null" or new == "null":
        return []
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [f"{path}: был объект, стало {new}"]
        out = []
        for k, v in old.items():
            if k not in new:
                out.append(f"{path}/{k}: ключ пропал")
            else:
                out += _lost(v, new[k], f"{path}/{k}")
        return out
    return [] if old == new or (isinstance(new, str) and old in new.split("|")) else [f"{path}: тип {old} → {new}"]


def _build(api) -> dict:
    from app import snapshot
    core = api.core
    api.put("/api/people/mark", json={"id": "mark", "name": "Марк", "needs_escort": True})
    api.put("/api/settings/escort", json={"show_duties": True})
    swim = api.post("/api/event", json={"calendar": "ya/home", "title": "Плавание", "start": "2026-11-03T17:00:00",
                                        "end": "2026-11-03T18:00:00", "people": ["mark"], "location": "Бассейн Юность"}).json()
    api.post("/api/event", json={"calendar": "ya/home", "title": "Йога", "start": "2026-11-03T19:30:00", "end": "2026-11-03T20:30:00"})
    api.post("/api/event", json={"calendar": "ya/home", "title": "День района", "start": "2026-11-05", "end": "2026-11-06", "all_day": True})
    api.post("/api/event-color", json={"uid": swim["uid"], "color": "#ff9500"})
    api.post("/api/escort", json={"uid": swim["uid"], "occurrence": None, "role": "pickup", "person": "anna"})   # поездка у взрослого (duty)
    api.put("/api/birthdays", json={"name": "Оля", "month": 11, "day": 4, "year": 1990})
    return snapshot.build(core.events, core.db, core.tz, now=core._parse_dt("2026-11-03T09:00:00"))


def test_snapshot_shape_matches_swift_fixture(api):
    snap = _build(api)
    # то, на что опираются Swift-тесты: если генератор перестал это давать, файл потеряет смысл
    kinds = {r["kind"] for r in snap["reminders"]}
    assert {"alert", "bday"} <= kinds, kinds
    trip = next(r for r in snap["reminders"] if r["id"].startswith("alert:trip:"))["trip"]
    assert trip["need"] and trip["names"]
    assert any(e.get("duty") for e in snap["events"]) and any(e.get("color") for e in snap["events"])
    assert any(e["all_day"] for e in snap["events"])

    fresh = json.loads(json.dumps(snap, ensure_ascii=False, default=str))
    if os.environ.get("UPDATE_FIXTURES"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(fresh, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert FIXTURE.exists(), "нет файла для тестов Swift — UPDATE_FIXTURES=1 python -m pytest tests/test_swift_fixture.py"
    saved = json.loads(FIXTURE.read_text(encoding="utf-8"))
    lost = _lost(_shape(saved), _shape(fresh))
    assert not lost, ("Снимок сервера разошёлся с тем, что ждут приложения (старые версии сломаются):\n  " + "\n  ".join(lost)
                      + "\nЕсли так и задумано — обновите версию снимка и файл: UPDATE_FIXTURES=1 python -m pytest tests/test_swift_fixture.py")
