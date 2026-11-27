from zoneinfo import ZoneInfo

import pytest

from app import backup, sync
from app.cloud import CloudError
from app.db import Database
from app.sources.base import RemoteCalendar


def test_deleted_attachment_survives_while_snapshot_references_it(tmp_path):
    db = Database(tmp_path / "calendar.sqlite3")
    contents = b"receipt"
    fid = "a" * 32
    files = tmp_path / "files"
    files.mkdir()
    (files / fid).write_bytes(contents)
    db.add_event_file(fid, "test", "receipt", size=len(contents))

    class Cloud:
        def _token(self):
            return "test"

        def key(self):
            return b"k" * 32

    class Disk:
        items: dict[str, bytes] = {}

        def __init__(self, token):
            pass

        def mkdir(self, path):
            pass

        def upload(self, data, path):
            self.items[path] = data

        def download_path(self, path):
            return self.items[path]

        def ls(self, path):
            return [{"name": key.rsplit("/", 1)[1]} for key in self.items if key.startswith(path + "/")]

        def rm(self, path):
            del self.items[path]

    service = backup.BackupService(db, Cloud(), ZoneInfo("UTC"), Disk)
    old = service.run()["name"]
    historical = "homehub-20000101-0000" + backup.SUFFIX
    Disk.items[f"{backup.DIR}/{historical}"] = Disk.items.pop(f"{backup.DIR}/{old}")
    db.delete_event_file(fid)
    (files / fid).unlink()
    assert service.run()["last_error"] is None
    path = f"{backup.FILES_DIR}/{fid}"
    assert path in Disk.items
    assert service.verify(historical)["attachments"] == 1
    saved = Disk.items.pop(path)
    assert not service.verify(historical)["ok"]
    with pytest.raises(CloudError):
        service.restore(historical)
    assert not db.event_files("test")
    Disk.items[path] = saved
    assert service.restore(historical)["attachments"] == 1
    assert (files / fid).read_bytes() == contents
    db.delete_event_file(fid)
    del Disk.items[f"{backup.DIR}/{historical}"]
    service.run()
    assert path not in Disk.items


@pytest.mark.parametrize("delta", [False, True])
def test_sync_discards_response_after_local_change(tmp_path, monkeypatch, delta):
    db = Database(tmp_path / "calendar.sqlite3")
    remote = RemoteCalendar("home", "Семья", objects={"event": "старый"}, ctag="r1", delta=delta)

    class Source:
        def fetch(self, known):
            db.put_object("remote/home", "event", "новый локальный")
            return [remote]

    monkeypatch.setattr(sync, "build_source", lambda cfg: Source())
    engine = sync.SyncEngine(db, [{"id": "remote", "type": "ics"}])
    assert engine.run()["remote"]["deferred"]
    assert db.objects_map("remote/home") == {"event": "новый локальный"}
    assert db.kv_get("sync:ctags")[0] is None


def test_sync_unlocks_after_sqlite_read_failure(tmp_path, monkeypatch):
    db = Database(tmp_path / "calendar.sqlite3")
    engine = sync.SyncEngine(db, [])
    get = db.kv_get
    def fail(*args):
        raise RuntimeError("SQLite read failure")
    monkeypatch.setattr(db, "kv_get", fail)
    with pytest.raises(RuntimeError):
        engine.run()
    assert not engine.running
    monkeypatch.setattr(db, "kv_get", get)
    assert engine.run() == {}


@pytest.mark.parametrize("kind", ["update", "delete"])
def test_sync_discards_snapshot_from_before_queue_ack(tmp_path, monkeypatch, kind):
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    from app import writer
    from app.writeq import WriteService

    db = Database(tmp_path / "calendar.sqlite3")
    key, href = "source/home", "/event.ics"
    tz = ZoneInfo("UTC")
    start = datetime(2026, 12, 1, 18, tzinfo=tz)
    _, before = writer.build_ics("До отправки", start, start + timedelta(hours=1), False, tz)
    after = writer.apply_edit(before, {"title": "После отправки"}, tz)
    db.touch_calendar(key, "source", "home", "Семья", {})
    db.put_object(key, href, before)
    writes = WriteService(db, lambda _: SimpleNamespace(update=lambda *_: None, delete=lambda *_: None), lambda: None)
    with writes.defer():
        if kind == "update":
            writes.update(key, href, before, after)
        else:
            writes.delete(key, href, before)

    def fetch(known):
        assert writes.flush()["done"] == 1
        return [RemoteCalendar("home", "Семья", objects={href: before})]

    monkeypatch.setattr(sync, "build_source", lambda cfg: SimpleNamespace(fetch=fetch))
    engine = sync.SyncEngine(db, [{"id": "source", "type": "ics"}], writes.reapply)
    assert engine.run()["source"]["deferred"]
    assert db.objects_map(key) == ({href: after} if kind == "update" else {})


def test_second_source_reads_restored_sync_tokens(tmp_path, monkeypatch):
    from types import SimpleNamespace

    db = Database(tmp_path / "calendar.sqlite3")
    previous = {"a/home": {"token": "ta0"}, "b/home": {"token": "tb0"}}
    db.kv_set("sync:ctags", previous)
    data = backup.snapshot_db(tmp_path / "calendar.sqlite3")
    db.kv_set("sync:ctags", {"a/home": {"token": "ta2"}, "b/home": {"token": "tb2"}})
    restore = backup.BackupService(db, None, ZoneInfo("UTC"))
    monkeypatch.setattr(restore, "_load", lambda _: data)

    def fetch_a(known):
        restore.restore("old")
        return []

    def fetch_b(known):
        assert known["home"]["token"] == "tb0"
        return [RemoteCalendar("home", "Семья", unchanged=True)]

    def source(cfg):
        return SimpleNamespace(fetch=fetch_a if cfg["id"] == "a" else fetch_b)

    monkeypatch.setattr(sync, "build_source", source)
    engine = sync.SyncEngine(db, [{"id": "a"}, {"id": "b"}])
    engine._runs = 1
    result = engine.run()
    assert result["a"]["deferred"] and result["b"]["ok"]
    assert db.kv_get("sync:ctags")[0] == previous
