"""Интеграционный тест настоящего CalDAV-сервера (Radicale): ctag, sync-token, дельты и удаления через SyncEngine."""
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("radicale")
import caldav  # noqa: E402

from app.db import Database  # noqa: E402
from app.sync import SyncEngine  # noqa: E402


def _ics(uid, title):
    return (f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:20261029T000000Z\n"
            f"DTSTART:20261101T100000Z\nDTEND:20261101T110000Z\nSUMMARY:{title}\nEND:VEVENT\nEND:VCALENDAR\n")


@pytest.fixture
def server(tmp_path):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    cfg = tmp_path / "cfg"
    cfg.write_text(f"[server]\nhosts = 127.0.0.1:{port}\n[auth]\ntype = none\n[storage]\nfilesystem_folder = {tmp_path / 'data'}\n")
    proc = subprocess.Popen([sys.executable, "-m", "radicale", "--config", str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(5)


def test_sync_against_radicale(server, tmp_path):
    client = caldav.DAVClient(url=server, username="u", password="p")
    cal = client.principal().make_calendar(name="Тест", supported_calendar_component_set=["VEVENT"])
    a, b = cal.save_event(_ics("a1", "Один")), cal.save_event(_ics("b1", "Два"))
    db = Database(tmp_path / "t.db")
    changes = []
    eng = SyncEngine(db, [{"id": "r", "type": "caldav", "url": server, "username": "u", "password": "p"}],
                     on_change=lambda: changes.append(1))
    assert eng.run()["r"]["ok"]
    key = db.list_calendars()[0]["key"]
    assert len(db.objects_map(key)) == 2
    st = db.kv_get("sync:ctags")[0][key]
    assert st["ctag"] and st["token"]                       # сервер умеет и ctag, и sync-token

    eng.run()                                               # ничего не менялось
    assert len(changes) == 1

    a.data = _ics("a1", "Один (правка)"); a.save()
    b.delete()
    cal.save_event(_ics("c1", "Три"))
    eng.run()
    titles = sorted(v.split("SUMMARY:")[1].split("\r\n")[0].split("\n")[0] for v in db.objects_map(key).values())
    assert titles == ["Один (правка)", "Три"]              # правка, добавление и удаление пришли дельтой
    assert len(db.objects_map(key)) == 2 and len(changes) == 2
    eng.run(full=True)                                      # полная загрузка даёт то же самое
    assert len(db.objects_map(key)) == 2 and len(changes) == 2


def test_write_roundtrip_against_radicale(server):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import writer
    tz = ZoneInfo("Asia/Yekaterinburg")
    client = caldav.DAVClient(url=server, username="u", password="p")
    cal = client.principal().make_calendar(name="Запись", supported_calendar_component_set=["VEVENT"])
    rid = str(cal.url).rstrip("/").rsplit("/", 1)[-1]
    target = writer.CalDavTarget(server, "u", "p")
    uid, ics = writer.build_ics("Ушу", datetime(2026, 11, 3, 17, 40, tzinfo=tz), datetime(2026, 11, 3, 18, 40, tzinfo=tz), False, tz,
                                repeat={"freq": "weekly", "byday": ["TU", "TH"], "until": "2026-11-30"})
    href = target.create(rid, ics)
    assert "SUMMARY:Ушу" in cal.event_by_url(href).data
    new = writer.apply_edit(ics, {"title": "Ушу (новое)", "location": "Зал"}, tz)
    target.update(rid, href, new)
    assert "Зал" in cal.event_by_url(href).data
    series, nuid, nics = writer.split_following(new, datetime(2026, 11, 17, 17, 40, tzinfo=tz),
                                                {"start": datetime(2026, 11, 17, 18, 0, tzinfo=tz),
                                                 "end": datetime(2026, 11, 17, 19, 0, tzinfo=tz), "all_day": False}, tz)
    target.update(rid, href, series)
    h2 = target.create(rid, nics)
    assert len(list(cal.events())) == 2
    target.delete(rid, href)
    target.delete(rid, h2)
    assert list(cal.events()) == []
