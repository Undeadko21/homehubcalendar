from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest


@pytest.fixture
def event():
    return {"calendar": "ya/home", "request_id": str(uuid4()), "title": "Тренировка",
            "start": "2026-12-01T18:00:00", "end": "2026-12-01T19:00:00", "people": ["anna"]}


def test_concurrent_retries_keep_one_local_and_remote_event(api, event):
    with ThreadPoolExecutor(max_workers=2) as threads:
        futures = [threads.submit(api.post, "/api/event", json=event) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]
    assert [r.status_code for r in results] == [200, 200]
    first = results[0].json()
    assert results[1].json() == first
    assert first["pending"]
    assert api.fake.n == 0
    assert api.core.db.find_object(first["uid"], event["calendar"])
    assert api.core.db.query("SELECT people FROM event_people WHERE uid=?", (first["uid"],)) == [{"people": '["anna"]'}]
    assert len(api.core.ws.queue()) == 1
    assert len(first["changes"]) == 1

    assert api.core.ws.flush()["done"] == 1
    replay = api.post("/api/event", json=event)
    assert replay.json() == first | {"pending": False}
    assert api.fake.n == 1

    different = api.post("/api/event", json=event | {"title": "Лекция"})
    assert different.status_code == 409
    assert api.fake.n == 1


def test_local_failure_does_not_confirm_or_partially_create_event(api, event, monkeypatch):
    import sqlite3

    original = api.core.db.set_event_people

    def fail(*args):
        raise sqlite3.OperationalError("disk error")

    with monkeypatch.context() as patch:
        patch.setattr(api.core.db, "set_event_people", fail)
        with pytest.raises(sqlite3.OperationalError):
            api.post("/api/event", json=event)

    assert not api.core.ws.queue()
    assert not api.core.ws.journal()
    assert not api.core.db.query("SELECT href FROM objects")
    assert api.core.db.set_event_people == original
    replay = api.post("/api/event", json=event)
    assert replay.status_code == 200
    assert len(api.core.ws.queue()) == 1


def test_create_receipt_survives_journal_rotation_and_deletion(api, event):
    first = api.post("/api/event", json=event).json()
    api.core.db.kv_set("changelog", [])
    assert api.post("/api/event", json=event).json() == first

    api.core.ws.flush()
    confirmed = first | {"pending": False}
    assert api.post("/api/event", json=event).json() == confirmed
    calendar, href, _ = api.core.db.find_object(first["uid"], event["calendar"])
    api.core.db.delete_object(calendar, href)
    assert api.post("/api/event", json=event).json() == confirmed
    assert not api.core.ws.queue()


def test_scheduler_unavailable_does_not_undo_create_acknowledgement(api, event, monkeypatch):
    from apscheduler.jobstores.base import JobLookupError

    class StoppingScheduler:
        running = True

        def modify_job(self, job_id, **changes):
            raise JobLookupError(job_id)

    monkeypatch.setattr(api.core, "scheduler", StoppingScheduler())
    response = api.post("/api/event", json=event)
    assert response.status_code == 200
    assert response.json()["pending"]
    assert len(api.core.ws.queue()) == 1


def test_replaying_a_rejected_create_explains_status(api, event, monkeypatch):
    from app.writer import WriteError

    def fail(*args):
        raise WriteError("Отказ")

    monkeypatch.setattr(api.fake, "create", fail)
    first = api.post("/api/event", json=event)
    assert first.json()["pending"]
    assert api.core.ws.flush()["failed"] == 1
    replay = api.post("/api/event", json=event)
    assert replay.status_code == 409
    assert "отклонено" in replay.json()["detail"]
    assert not api.core.ws.queue()


def test_create_and_replay_acknowledge_while_caldav_is_waiting(api, event, monkeypatch):
    sending, release = Event(), Event()
    create = api.fake.create

    def slow_create(*args):
        sending.set()
        assert release.wait(5)
        return create(*args)

    monkeypatch.setattr(api.fake, "create", slow_create)
    scheduler = api.core.scheduler
    scheduler.add_job(api.core.ws.flush, "interval", minutes=2, id="writeq", max_instances=1)
    scheduler.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as threads:
            try:
                first = threads.submit(api.post, "/api/event", json=event).result(timeout=2)
                assert first.json()["pending"]
                assert sending.wait(2)
                replay = threads.submit(api.post, "/api/event", json=event).result(timeout=2)
                assert replay.json() == first.json()
                second_event = {**event, "title": "Второе событие", "request_id": str(uuid4())}
                second = threads.submit(api.post, "/api/event", json=second_event).result(timeout=2)
                assert second.status_code == 200 and second.json()["pending"]
                assert second.json()["uid"] != first.json()["uid"]
                assert api.fake.n == 0
            finally:
                release.set()
    finally:
        scheduler.shutdown(wait=True)
