"""Приложение FastAPI: жизненный цикл и планировщик, PIN-защита, замер времени запросов, подключение маршрутов (app/api/*.py)
и раздача веб-интерфейса."""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time as time_module
from time import perf_counter
from contextlib import asynccontextmanager
from datetime import datetime, time

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from . import ops
from . import live
from .perf import SLOW_MS
from . import core
from .api import apps, cloud_api, lists, planning, system, writing


def poll_cloud() -> None:
    """Команды, которые телефоны оставили в облаке, применяем и сразу обновляем снимок."""
    if core.cloud.poll_ops(lambda items: ops.apply(core.db, items, {"event_add": core._ops_event, "event_quick": core._ops_event})):
        core.events.invalidate()
        core.cloud.tick(force=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=core._warm, daemon=True).start()
    if os.environ.get("HOMECAL_NO_SCHEDULER") != "1":
        core.scheduler.add_job(core.engine.run, "interval", minutes=core.settings.sync.interval_minutes,
                          next_run_time=datetime.now(core.tz), id="sync", max_instances=1, coalesce=True)
        # Снимок для телефона вне дома: проверяем раз в 2 минуты, на Диск пишем при изменениях и раз в час.
        core.scheduler.add_job(core.ws.flush, "interval", minutes=2, id="writeq", max_instances=1, coalesce=True)
        core.scheduler.add_job(core.cloud.tick, "interval", minutes=2, id="cloud", max_instances=1, coalesce=True)
        core.scheduler.add_job(poll_cloud, "interval", minutes=1, id="cloud-ops", max_instances=1, coalesce=True)
        core.scheduler.add_job(core.backup.run, "cron", hour=3, minute=30, id="backup", max_instances=1, coalesce=True,
                          misfire_grace_time=6 * 3600)
        core.scheduler.start()
    yield
    if core.scheduler.running:
        core.scheduler.shutdown(wait=False)


app = FastAPI(title="HomeHub Calendar", version=__version__, lifespan=lifespan)


# ---------- простая защита PIN-кодом (включается переменной HOMECAL_PIN) ----------
def _token() -> str:
    return hmac.new(core.settings.pin.encode(), b"homecal", hashlib.sha256).hexdigest()


@app.middleware("http")
async def timing(request: Request, call_next):
    """Замер времени каждого запроса к API (GET /api/perf)."""
    if not request.url.path.startswith("/api/") or request.url.path == "/api/stream":
        return await call_next(request)
    t0 = perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        # Любая успешная запись через API — повод обновить остальные открытые экраны.
        if request.method != "GET" and status < 400 and request.url.path not in ("/api/client-log", "/api/login"):
            live.bump()
        return resp
    finally:
        ms = (perf_counter() - t0) * 1000
        route = getattr(request.scope.get("route"), "path", None) or request.url.path
        core.perf.record(request.method, route, ms, status, request.url.query)
        if ms >= SLOW_MS:
            core.log.warning("Медленный запрос %s %s: %d мс", request.method, request.url.path, ms)


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    path = request.url.path
    if core.settings.pin and path.startswith("/api/") and path not in ("/api/login", "/api/health"):
        if not hmac.compare_digest(request.cookies.get("homecal_auth", ""), _token()):
            return JSONResponse({"detail": "auth_required"}, status_code=401)
    return await call_next(request)


class Login(BaseModel):
    pin: str


_FAILS: dict[str, list] = {}   # ip -> [число неудач, до какого момента заблокирован]


def _login_wait(ip: str) -> int:
    f = _FAILS.get(ip)
    return max(0, int(f[1] - time_module.time())) if f else 0


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    if not core.settings.pin:
        return {"ok": True}
    ip = request.client.host if request.client else "?"
    wait = _login_wait(ip)
    if wait:
        raise HTTPException(429, f"Слишком много попыток. Подождите {wait // 60 + 1} мин.")
    if not hmac.compare_digest(body.pin, core.settings.pin):
        n = (_FAILS.get(ip) or [0, 0])[0] + 1
        # 5 ошибок подряд — блокировка на 1 минуту, дальше вдвое дольше (до часа)
        _FAILS[ip] = [n, time_module.time() + (min(3600, 60 * 2 ** (n - 5)) if n >= 5 else 0)]
        if len(_FAILS) > 500:
            _FAILS.clear()
        raise HTTPException(401, "Неверный PIN")
    _FAILS.pop(ip, None)
    response.set_cookie("homecal_auth", _token(), max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


# ---------- веб-интерфейс ----------

# Маршруты по темам (app/api/*.py). Страница-заглушка SPA ниже должна идти последней.
for _r in (system, apps, cloud_api, lists, planning, writing):
    app.include_router(_r.router)


if core.STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=core.STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = core.STATIC_DIR / path
        if path and f.is_file() and core.STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(core.STATIC_DIR / "index.html")
