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
from datetime import datetime, time, timedelta

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel, Field

from . import BUILD, __version__
from . import access, deploywatch, ops, versionwatch
from . import sessions as sessions_mod
from . import live
from .perf import SLOW_MS
from . import core
from .api import access as access_api
from .api import apps, cloud_api, files, lists, planning, system, writing


def poll_cloud() -> None:
    """Команды, которые телефоны оставили в облаке, применяем и сразу обновляем снимок."""
    if core.cloud.poll_ops(lambda items: ops.apply(core.db, items, {"event_add": core._ops_event, "event_quick": core._ops_event, "event_move": core._ops_move})):
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
        core.scheduler.add_job(lambda: access.watch(core.db), "interval", minutes=5, id="access-watch", max_instances=1, coalesce=True)
        core.scheduler.add_job(lambda: versionwatch.check(core.db, BUILD), "interval", minutes=30, id="version-watch",
                               max_instances=1, coalesce=True, next_run_time=datetime.now() + timedelta(minutes=20))
        core.scheduler.add_job(core.routes_refresh, "interval", minutes=30, id="routes", max_instances=1, coalesce=True)
        core.scheduler.add_job(core.run_checks, "cron", hour=4, minute=10, id="checks", max_instances=1, coalesce=True,
                          misfire_grace_time=6 * 3600)
        core.scheduler.add_job(core.backup_drill, "cron", day=1, hour=4, minute=40, id="backup-drill", max_instances=1, coalesce=True,
                               misfire_grace_time=6 * 3600)
        core.scheduler.add_job(lambda: deploywatch.check(core.db, core.settings.data_dir, __version__), "interval", minutes=10,
                               id="deploy-watch", max_instances=1, coalesce=True, next_run_time=datetime.now() + timedelta(seconds=30))
        core.scheduler.add_job(core.selftest_weekly, "cron", day_of_week="sun", hour=5, minute=20, id="selftest", max_instances=1,
                               coalesce=True, misfire_grace_time=3600)
        core.scheduler.add_job(core.backup.run, "cron", hour=3, minute=30, id="backup", max_instances=1, coalesce=True,
                          misfire_grace_time=6 * 3600)
        core.scheduler.start()
    yield
    if core.scheduler.running:
        core.scheduler.shutdown(wait=False)


# Описание API наружу не отдаём: календарь может быть открыт в интернет.
app = FastAPI(title="HomeHub Calendar", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1200, compresslevel=4)


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
    rev_before = live.rev
    try:
        resp = await call_next(request)
        status = resp.status_code
        # Любая успешная запись через API — повод обновить остальные открытые экраны.
        if request.method != "GET" and status < 400 and request.url.path not in ("/api/client-log", "/api/login"):
            after = live.bump()
            cid = request.headers.get("x-client-id")
            if cid:
                live.mark(rev_before, after, cid[:40])
        return resp
    finally:
        ms = (perf_counter() - t0) * 1000
        route = getattr(request.scope.get("route"), "path", None) or request.url.path
        core.perf.record(request.method, route, ms, status, request.url.query)
        if ms >= SLOW_MS:
            core.log.warning("Медленный запрос %s %s: %d мс", request.method, request.url.path, ms)


# Без входа доступно только то, что нужно до входа: проверка живости, сведения о версиях приложений (номера, не файлы данных).
_PUBLIC_API = ("/api/login", "/api/health", "/api/ready", "/api/app", "/api/app-mac", "/api/app-ios")


def _pinfp() -> str:
    return sessions_mod.pin_fingerprint(core.settings.pin)


def _issue_cookie(resp, request: Request, secret: str) -> None:
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"   # через HTTPS — cookie только по HTTPS
    resp.set_cookie("homecal_auth", "s." + secret, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", secure=secure)


def _new_session(request: Request, via: str) -> str:
    return core.sessions.create(_pinfp(), sessions_mod.device_label(request.headers.get("user-agent", "")), _client_ip(request), via)


def current_session(request: Request) -> str | None:
    """Ключ сессии этого запроса (нужен списку устройств, чтобы пометить «это устройство»)."""
    c = request.cookies.get("homecal_auth", "")
    if c.startswith("s.") and core.settings.pin:
        k = sessions_mod._key(c[2:])
        return k if k in core.sessions._data() else None
    return getattr(request.state, "session_key", None)


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    path = request.url.path
    upgrade_secret = None
    if core.settings.pin and path.startswith("/api/") and path not in _PUBLIC_API and not path.startswith("/api/login/qr/"):
        cookie = request.cookies.get("homecal_auth", "")
        if cookie.startswith("s.") and core.sessions.check(cookie[2:], _pinfp(), _client_ip(request)):
            pass
        elif cookie and not cookie.startswith("s.") and core.sessions.legacy_ok() and hmac.compare_digest(cookie, _token()):
            # Старый общий cookie: молча заменяем личной сессией, чтобы устройство появилось в списке и его можно было отключить.
            upgrade_secret = _new_session(request, "прежний вход")
            request.state.session_key = sessions_mod._key(upgrade_secret)
            access.remember_ip(core.db, _client_ip(request))
        elif request.method == "GET" and path in ("/api/widget", "/api/snapshot") and \
                access.check(core.db, "widget", request.headers.get("x-widget-token", "")):
            access.touch_widget(core.db)   # токен виджета: только чтение сводки, ничего не меняет
        elif path.startswith("/api/vps/") and \
                access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
            pass   # VPS-агент приходит с токеном через обратный туннель (отчёт, установка, копия базы); каждый маршрут проверяет токен и сам
        else:
            return JSONResponse({"detail": "auth_required"}, status_code=401)
    resp = await call_next(request)
    if upgrade_secret:
        _issue_cookie(resp, request, upgrade_secret)
    return resp


class Login(BaseModel):
    pin: str = Field(max_length=200)


def _client_ip(request: Request) -> str:
    """Адрес клиента. За прокси (Caddy на VPS) настоящий адрес — первый в X-Forwarded-For: Caddy сам его выставляет и чужой не доверяет."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()[:64] or "?"
    return request.client.host if request.client else "?"


_FAILS: dict[str, list] = {}   # ip -> [число неудач, до какого момента заблокирован]


def _login_wait(ip: str) -> int:
    f = _FAILS.get(ip)
    return max(0, int(f[1] - time_module.time())) if f else 0


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    if not core.settings.pin:
        return {"ok": True}
    ip = _client_ip(request)
    wait = _login_wait(ip)
    if wait:
        raise HTTPException(429, f"Слишком много попыток. Подождите {wait // 60 + 1} мин.")
    if not hmac.compare_digest(body.pin.encode(), core.settings.pin.encode()):   # байты: пароль может быть с русскими буквами
        n = (_FAILS.get(ip) or [0, 0])[0] + 1
        # 5 ошибок подряд — блокировка на 1 минуту, дальше вдвое дольше (до часа)
        _FAILS[ip] = [n, time_module.time() + (min(3600, 60 * 2 ** (n - 5)) if n >= 5 else 0)]
        if len(_FAILS) > 500:
            _FAILS.clear()
        label = sessions_mod.device_label(request.headers.get("user-agent", ""))
        # Событие в журнал — на каждую ошибку подряд с 3-й; уведомление на телефон — когда адрес заблокирован (5, 10, 15… ошибок).
        if n >= 3:
            access.event(core.db, "fail", f"Неверный пароль ({n}-я попытка подряд), {label}", ip=ip, alert=n >= 5 and n % 5 == 0,
                         title="HomeHub: подбор пароля?", priority="high")
        raise HTTPException(401, "Неверный PIN")
    _FAILS.pop(ip, None)
    _issue_cookie(response, request, _new_session(request, "пароль"))
    label = sessions_mod.device_label(request.headers.get("user-agent", ""))
    if access.remember_ip(core.db, ip):
        access.event(core.db, "login", f"Новый вход с нового адреса: {label}", ip=ip, alert=True, title="HomeHub: новый вход")
    else:
        access.event(core.db, "login", f"Вход: {label}", ip=ip)
    return {"ok": True}


@app.post("/api/login/qr")
def login_qr_create(request: Request):
    """Одноразовая ссылка входа на 10 минут — для QR-кода: открыть на новом устройстве, пароль вводить не нужно."""
    origin = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{request.headers.get('host', request.url.netloc)}"
    return {"url": f"{origin}/api/login/qr/{access.new_login_link()}", "ttl": access.QR_TTL}


@app.get("/api/login/qr/{link}")
def login_qr_use(link: str, request: Request):
    ip = _client_ip(request)
    wait = _login_wait(ip)
    if wait:
        raise HTTPException(429, f"Слишком много попыток. Подождите {wait // 60 + 1} мин.")
    if not core.settings.pin or access.use_login_link(link):
        _FAILS.pop(ip, None)
        resp = RedirectResponse("/", status_code=303)
        if core.settings.pin:
            _issue_cookie(resp, request, _new_session(request, "QR-код"))
            access.remember_ip(core.db, ip)
            access.event(core.db, "login", f"Вход по QR-коду: {sessions_mod.device_label(request.headers.get('user-agent', ''))}", ip=ip,
                         alert=True, title="HomeHub: вход по QR")
        return resp
    n = (_FAILS.get(ip) or [0, 0])[0] + 1
    _FAILS[ip] = [n, time_module.time() + (min(3600, 60 * 2 ** (n - 5)) if n >= 5 else 0)]
    return PlainTextResponse("Ссылка недействительна или уже использована. Создайте новую в настройках.", status_code=410)


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/ready")
def ready():
    """Глубже health: база читается и лента собирается. Нужен update.sh, чтобы поймать сломанную логику, а не только «процесс жив»."""
    from . import checks
    try:
        return checks.ready(core.db, core.events, core.tz)
    except Exception as e:  # noqa: BLE001
        core.log.exception("ready")
        return JSONResponse({"ok": False, "error": type(e).__name__}, status_code=503)


# ---------- веб-интерфейс ----------

# Маршруты по темам (app/api/*.py). Страница-заглушка SPA ниже должна идти последней.
for _r in (system, apps, cloud_api, files, lists, planning, writing, access_api):
    app.include_router(_r.router)


if core.STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=core.STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = core.STATIC_DIR / path
        if path and f.is_file() and core.STATIC_DIR in f.resolve().parents:
            return FileResponse(f, headers={"Cache-Control": "no-cache"} if f.name == "index.html" else None)
        # Оболочка страницы всегда сверяется с сервером: иначе WebView в приложениях может долго держать старую версию интерфейса.
        return FileResponse(core.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
