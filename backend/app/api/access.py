"""Доступ из интернета: публичный адрес, токены, вход по QR, VPS-агент, уведомления ntfy."""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from .. import access, core

router = APIRouter()
_TEMPLATE = Path(__file__).resolve().parent.parent / "vps_install.sh"


class AccessIn(BaseModel):
    public_url: str | None = Field(default=None, max_length=200)
    widget: bool | None = None     # включить / выключить токен «только чтение» для виджетов
    vps: bool | None = None        # включить / выключить связь с VPS-агентом
    ntfy: bool | None = None       # уведомления «дом недоступен»
    login_alerts: bool | None = None   # сообщать о новых входах и подборе пароля


def _state() -> dict:
    db = core.db
    topic = access.ntfy_topic(db)
    vps_on = access.enabled(db, "vps")
    return {
        "public_url": access.public_url(db),
        "widget": access.enabled(db, "widget"),
        "vps": {"enabled": vps_on, "report": access.last_report(db), "backup": access.backup_info(db),
                "problems": access.problems(db),
                "install": f'curl -fsS -H "Authorization: Bearer {access.token(db, "vps")}" '
                           f'http://127.0.0.1:18080/api/vps/install.sh | bash' if vps_on else None},
        "ntfy": {"enabled": bool(topic), "topic": topic or None, "login": access.login_alerts(db)},
        "checks": access.checks(db, core.cloud.status(), len(core.sessions._data())),
    }


@router.get("/api/access")
def get_access():
    return _state()


@router.put("/api/access")
def put_access(body: AccessIn):
    db = core.db
    if body.public_url is not None:
        try:
            access.set_public_url(db, body.public_url)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if body.widget is True:
        access.token(db, "widget")
    elif body.widget is False:
        access.disable(db, "widget")
    if body.vps is True:
        access.token(db, "vps")
    elif body.vps is False:
        access.disable(db, "vps")
    if body.ntfy is True:
        access.enable_ntfy(db)
    elif body.ntfy is False:
        access.disable_ntfy(db)
    if body.login_alerts is not None:
        access.set_login_alerts(db, body.login_alerts)
    core.cloud.tick(force=True)   # код подключения мог измениться — обновим снимок
    return _state()


@router.post("/api/access/rotate/{which}")
def rotate(which: str):
    if which not in access.KEYS:
        raise HTTPException(404, "Нет такого токена")
    access.rotate(core.db, which)
    core.cloud.tick(force=True)
    return _state()


@router.post("/api/access/probe")
def probe():
    """Проверка «снаружи» по кнопке: ответ виден сразу, результат попадает и в сводку."""
    res = access.probe_public(core.db)
    access.WATCH["last"] = res
    return {"probe": res, "checks": _state()["checks"]}


def _current(request: Request):
    from ..main import current_session
    return current_session(request)


@router.get("/api/sessions")
def sessions(request: Request):
    return {"sessions": core.sessions.listing(_current(request)), "legacy": core.sessions.legacy_ok(),
            "pin": bool(core.settings.pin), "log": access.security_log(core.db)}


@router.delete("/api/sessions/{sid}")
def revoke_session(sid: str, request: Request):
    cur = _current(request)
    if not core.sessions.revoke(sid):
        raise HTTPException(404, "Такого устройства нет в списке")
    access.event(core.db, "revoke", "Устройство отключено вручную", ip="")
    return sessions(request) | {"was_current": bool(cur and cur[:12] == sid)}


class RevokeAll(BaseModel):
    keep_current: bool = True


@router.post("/api/sessions/revoke-all")
def revoke_all(body: RevokeAll, request: Request):
    n = core.sessions.revoke_all(_current(request) if body.keep_current else None)
    access.event(core.db, "revoke", f"Отключено устройств: {n}" + (" (кроме текущего)" if body.keep_current else ""))
    return sessions(request)


class DomainIn(BaseModel):
    domain: str = Field(max_length=260)


@router.post("/api/access/domain-check")
def domain_check(body: DomainIn):
    return access.check_domain(core.db, body.domain)


@router.post("/api/access/ntfy-test")
def ntfy_test():
    topic = access.ntfy_topic(core.db)
    if not topic:
        raise HTTPException(400, "Уведомления не включены")
    try:
        r = httpx.post(f"https://ntfy.sh/{topic}", content="Проверка: уведомления из домашнего календаря работают".encode(),
                       headers={"Title": "HomeHub"}, timeout=15)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(502, "ntfy.sh не ответил: " + type(e).__name__) from e
    return {"ok": True}


@router.get("/api/access/vps-backup")
def vps_backup():
    data = access.backup_bytes(core.db)
    if not data:
        raise HTTPException(404, "Копии настроек VPS ещё нет")
    return Response(data, media_type="application/gzip",
                    headers={"Content-Disposition": 'attachment; filename="vps-config.tar.gz"'})


# ----- вызовы с VPS (по токену VPS, приходят через обратный туннель) -----

@router.get("/api/vps/install.sh")
def vps_install(request: Request):
    if not access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
        raise HTTPException(401, "auth_required")
    topic = access.ntfy_topic(core.db)
    text = (_TEMPLATE.read_text(encoding="utf-8")
            .replace("@TOKEN@", access.token(core.db, "vps"))
            .replace("@NTFY@", f"https://ntfy.sh/{topic}" if topic else ""))
    return PlainTextResponse(text)


@router.get("/api/vps/db-backup")
def vps_db_backup(request: Request):
    """Свежая копия базы, зашифрованная ключом облака (тот же формат, что на Диске): агент VPS забирает её раз в сутки."""
    from .. import backup as backup_mod
    if not access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
        raise HTTPException(401, "auth_required")
    raw = backup_mod.snapshot_db(Path(core.db.path), core.db)
    blob = backup_mod.seal(core.cloud.key(), raw)
    access.mark_dbcopy_served(core.db)
    return Response(blob, media_type="application/octet-stream")


@router.get("/api/vps/files")
def vps_files(request: Request):
    """Список вложений (id по строке) — агент VPS докачивает новые и убирает удалённые."""
    if not access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
        raise HTTPException(401, "auth_required")
    ids = [r["id"] for r in core.db.query("SELECT id FROM event_files WHERE url IS NULL ORDER BY id")]
    return Response("\n".join(ids) + ("\n" if ids else ""), media_type="text/plain")


@router.get("/api/vps/files/{fid}")
def vps_file(fid: str, request: Request):
    import gzip
    import re
    from .. import backup as backup_mod
    if not access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
        raise HTTPException(401, "auth_required")
    path = core.settings.data_dir / "files" / fid
    if not re.fullmatch(r"[0-9a-f]{32}", fid) or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return Response(backup_mod.seal(core.cloud.key(), gzip.compress(path.read_bytes(), 6)), media_type="application/octet-stream")


class Report(BaseModel):
    report: dict
    backup: str | None = None


@router.post("/api/vps/ingest")
def vps_ingest(body: Report, request: Request):
    import base64
    if not access.check(core.db, "vps", access.bearer(request.headers.get("authorization", ""))):
        raise HTTPException(401, "auth_required")
    try:
        raw = base64.b64decode(body.backup, validate=True) if body.backup else None
        access.save_report(core.db, body.report, raw)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}
