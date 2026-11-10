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
        "ntfy": {"enabled": bool(topic), "topic": topic or None},
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
    core.cloud.tick(force=True)   # код подключения мог измениться — обновим снимок
    return _state()


@router.post("/api/access/rotate/{which}")
def rotate(which: str):
    if which not in access.KEYS:
        raise HTTPException(404, "Нет такого токена")
    access.rotate(core.db, which)
    core.cloud.tick(force=True)
    return _state()


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
