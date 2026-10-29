"""Состояние сервера: статус, синхронизация, учётные записи, «Состояние», скорость, живое обновление (SSE), ошибки клиентов."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import __version__
from .. import live
from fastapi import APIRouter

from .. import core

router = APIRouter()


@router.get("/api/stream")
async def stream(request: Request):
    """Живое обновление: отдаёт номер изменений, когда он меняется (EventSource в браузере сам переподключается)."""
    async def gen():
        last = live.rev
        yield f"retry: 5000\ndata: {last}\n\n"
        idle = 0
        while not await request.is_disconnected():
            await asyncio.sleep(1)
            if live.rev != last:
                last, idle = live.rev, 0
                yield f"data: {last}\n\n"
            else:
                idle += 1
                if idle >= 20:
                    idle = 0
                    yield ": ka\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/perf")
def get_perf():
    return core.perf.summary()


@router.get("/api/system")
def get_system():
    """Всё, что нужно для страницы «Состояние»: версии, синхронизация, облако, копии, ошибки клиентов."""
    now = datetime.now(core.tz)
    sources = core.db.sync_status()
    cl, bk = core.cloud.status(), core.backup.status()
    problems: list[str] = []
    if core.ws.pending_count():
        problems.append(f"Не отправлено в Яндекс: {core.ws.pending_count()} (повторю сам, когда сервер ответит)")
    if core.ws.last_error():
        problems.append("Запись в Яндекс отклонена: " + core.ws.last_error())
    for s in sources:
        if s.get("last_error"):
            problems.append(f"Синхронизация {s['source_id']}: {s['last_error']}")
        elif s.get("last_ok"):
            age = now - datetime.fromisoformat(s["last_ok"]).astimezone(core.tz)
            if age > timedelta(minutes=max(30, core.settings.sync.interval_minutes * 4)):
                problems.append(f"Календарь {s['source_id']} давно не обновлялся ({int(age.total_seconds() // 60)} мин)")
    rej = (core.db.kv_get("ops:rejected")[0] or {}).get("items", [])
    for r in rej[-3:]:
        if datetime.fromisoformat(r["at"]) > datetime.now() - timedelta(days=2):
            problems.append(f"Команда с телефона не выполнена: «{r['text']}» — {r['why']}")
    if cl["configured"]:
        if cl.get("last_error"):
            problems.append("Облако: " + cl["last_error"])
        if cl.get("ops_error"):
            problems.append("Команды с телефона: " + cl["ops_error"])
        if bk.get("last_error"):
            problems.append("Резервная копия: " + bk["last_error"])
        elif bk.get("last_ok") and now - datetime.fromisoformat(bk["last_ok"]).astimezone(core.tz) > timedelta(days=3):
            problems.append("Резервной копии не было больше 3 суток")
    jobs = {j.id: j.next_run_time.isoformat(timespec="seconds") for j in core.scheduler.get_jobs() if j.next_run_time}
    count = lambda sql: (core.db.query(sql) or [{"n": 0}])[0]["n"]  # noqa: E731
    try:
        db_size = os.path.getsize(core.db.path)
    except OSError:
        db_size = None
    return {
        "version": __version__, "started": core.STARTED.isoformat(timespec="seconds"), "now": now.isoformat(timespec="seconds"),
        "db_size": db_size,
        "counts": {"people": count("SELECT COUNT(*) n FROM people"), "calendars": count("SELECT COUNT(*) n FROM calendars"),
                   "objects": count("SELECT COUNT(*) n FROM objects"), "birthdays": count("SELECT COUNT(*) n FROM birthdays")},
        "sources": sources, "sync_interval": core.settings.sync.interval_minutes, "syncing": core.engine.running,
        "cloud": {k: cl[k] for k in ("configured", "last_ok", "last_error", "ops_error")},
        "backup": bk, "jobs": jobs, "client_errors": len(core.CLIENT_LOG), "slow_requests": core.perf.slow_count(),
        "last_client_error": core.CLIENT_LOG[-1] if core.CLIENT_LOG else None, "problems": problems,
    }


@router.get("/api/status")
def get_status():
    return {"running": core.engine.running, "sources": core.db.sync_status(),
            "configured_sources": [s.get("id") for s in core.settings.sources]}


@router.post("/api/sync")
def trigger_sync():
    return core.engine.run(full=True)


class AccountIn(BaseModel):
    username: str
    password: str | None = None  # пусто — оставить прежний


@router.put("/api/accounts/{source_id}")
def put_account(source_id: str, body: AccountIn):
    try:
        core.engine.set_credentials(source_id, body.username, body.password)
    except KeyError:
        raise HTTPException(404, "Источник не найден")
    return core.engine.run(full=True).get(source_id, {"ok": False, "error": "источник выключен"})


class ClientLog(BaseModel):
    message: str
    stack: str = ""
    url: str = ""
    ua: str = ""
    kind: str = "error"


@router.post("/api/client-log")
def post_client_log(body: ClientLog, request: Request):
    entry = {**body.model_dump(), "at": datetime.now(core.tz).isoformat(timespec="seconds"),
             "ip": request.client.host if request.client else ""}
    entry = {k: (v[:2000] if isinstance(v, str) else v) for k, v in entry.items()}
    core.CLIENT_LOG.append(entry)
    del core.CLIENT_LOG[:-100]
    core.log.warning("Ошибка в клиенте %s: %s", entry["ip"], entry["message"])
    return {"ok": True}


@router.get("/api/client-log")
def get_client_log():
    return list(reversed(core.CLIENT_LOG))
