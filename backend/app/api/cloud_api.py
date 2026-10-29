"""Облако (Яндекс.Диск), резервные копии, снимок, напоминания, перенос настроек."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import __version__
from .. import reminders, snapshot, portable
from ..cloud import CloudError
from fastapi import APIRouter

from .. import core

router = APIRouter()


class EventRemindersIn(BaseModel):
    people: dict[str, list[int]] = {}
    allday_people: list[str] | None = None
    allday_time: str | None = None


@router.get("/api/settings/event-reminders")
def get_event_reminders():
    return {"people": reminders.load_rules(core.db), "choices": list(reminders.LEAD_CHOICES),
            "allday": reminders.load_allday(core.db)}


@router.put("/api/settings/event-reminders")
def put_event_reminders(body: EventRemindersIn):
    known = {p["id"] for p in core.db.list_people()}
    out = reminders.save_rules(core.db, body.people, known)
    if body.allday_people is not None or body.allday_time is not None:
        cur = reminders.load_allday(core.db)
        reminders.save_allday(core.db, cur["people"] if body.allday_people is None else body.allday_people,
                              body.allday_time or cur["time"], known)
    core.cloud.tick(force=True)
    return {"people": out, "choices": list(reminders.LEAD_CHOICES), "allday": reminders.load_allday(core.db)}


@router.get("/api/backup")
def get_backup():
    return core.backup.status()


@router.post("/api/backup")
def run_backup():
    return core.backup.run()


@router.get("/api/backup/files")
def backup_files():
    try:
        return {"files": core.backup.files(), "status": core.backup.status()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@router.post("/api/backup/verify")
def backup_verify(body: dict | None = None):
    return core.backup.verify((body or {}).get("name"))


@router.post("/api/backup/restore")
def backup_restore(body: dict):
    try:
        res = core.backup.restore(str(body.get("name", "")))
    except Exception as e:  # noqa: BLE001
        core.log.exception("Восстановление")
        raise HTTPException(400, str(e))
    core._synced()
    return res


@router.get("/api/export")
def export_settings():
    data = portable.export(core.db, __version__)
    name = f"homehub-settings-{datetime.now(core.tz):%Y-%m-%d}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/import")
def import_settings(body: dict):
    try:
        counts = portable.import_(core.db, body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        core.log.exception("Импорт настроек")
        raise HTTPException(400, f"Не удалось загрузить настройки: {e}")
    core.events.invalidate()
    return {"ok": True, "counts": counts}


# ---------- напоминания для приложения ----------
@router.get("/api/reminders")
def get_reminders(hours: int = 36, lead: int = 30, people: str | None = None):
    """Что и когда напомнить. people — чьи поездки (id через запятую); пусто — всех."""
    now = datetime.now(core.tz)
    start = core._today_start()
    evs = core.events.events(start, start + timedelta(days=4))
    wanted = {p for p in (people or "").split(",") if p} or None
    items = reminders.build(evs, core.db.birthdays(), now, core.tz, wanted, max(0, min(lead, 240)), 2,
                            reminders.load_rules(core.db), reminders.load_allday(core.db))
    lo, hi = now - timedelta(hours=3), now + timedelta(hours=max(1, min(hours, 72)))
    return {"now": now.isoformat(timespec="seconds"),
            "items": [r for r in items if lo <= datetime.fromisoformat(r["at"]) <= hi]}


# ---------- снимок для телефона и Яндекс.Диск ----------
@router.get("/api/snapshot")
def get_snapshot():
    """То же, что лежит в облаке (но без шифрования): виджет и напоминания на 7 дней."""
    return snapshot.build(core.events, core.db, core.tz)


class CloudIn(BaseModel):
    token: str | None = None  # пусто — отключить


@router.get("/api/cloud")
def get_cloud():
    return core.cloud.status()


@router.put("/api/cloud")
def put_cloud(body: CloudIn):
    try:
        core.cloud.set_token(body.token)
    except CloudError as e:
        raise HTTPException(400, str(e))
    return core.cloud.tick(force=True)


@router.post("/api/cloud/push")
def push_cloud():
    return core.cloud.tick(force=True)
