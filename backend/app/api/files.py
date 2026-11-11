"""Вложения и ссылки в карточке события; время в дороге по карте."""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import core, routing

router = APIRouter()

MAX_SIZE = 15 * 1024 * 1024
MAX_PER_EVENT = 12
# Что можно открыть прямо в браузере; остальное (в т.ч. html и svg — в них бывает скрипт) отдаётся только на скачивание.
INLINE = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"}


def files_dir() -> Path:
    d = core.settings.data_dir / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _public(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "mime": row["mime"], "size": row["size"],
            "url": row["url"], "created": row["created"], "inline": row["mime"] in INLINE}


def _clean_name(name: str) -> str:
    name = re.sub(r"[\\/\x00-\x1f]", " ", name or "").strip(" .")
    return name[:120] or "файл"


@router.get("/api/event-files")
def list_files(uid: str):
    return [_public(r) for r in core.db.event_files(uid)]


@router.post("/api/event-files/upload")
async def upload_file(request: Request, uid: str, name: str):
    """Файл передаётся телом запроса как есть (без multipart), имя — в адресе."""
    if not uid.strip():
        raise HTTPException(400, "Не указано событие")
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_SIZE:
        raise HTTPException(413, "Файл больше 15 МБ")
    if len(core.db.event_files(uid)) >= MAX_PER_EVENT:
        raise HTTPException(400, f"У события уже {MAX_PER_EVENT} вложений")
    data = await request.body()
    if not data:
        raise HTTPException(400, "Пустой файл")
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "Файл больше 15 МБ")
    name = _clean_name(name)
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    fid = uuid.uuid4().hex
    (files_dir() / fid).write_bytes(data)
    core.db.add_event_file(fid, uid, name, mime, len(data))
    core.events.invalidate()
    return _public(core.db.event_file(fid))


class LinkIn(BaseModel):
    uid: str
    url: str
    name: str = ""


@router.post("/api/event-files/link")
def add_link(body: LinkIn):
    url = body.url.strip()
    if not re.match(r"^https?://[^\s]+$", url, re.I) or len(url) > 2000:
        raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
    if len(core.db.event_files(body.uid)) >= MAX_PER_EVENT:
        raise HTTPException(400, f"У события уже {MAX_PER_EVENT} вложений")
    fid = uuid.uuid4().hex
    core.db.add_event_file(fid, body.uid, _clean_name(body.name) if body.name.strip() else "", "link", 0, url)
    core.events.invalidate()
    return _public(core.db.event_file(fid))


@router.get("/api/event-files/{fid}/raw")
def get_file(fid: str):
    row = core.db.event_file(fid) if re.fullmatch(r"[0-9a-f]{32}", fid) else None
    path = files_dir() / fid
    if not row or row["url"] or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    inline = row["mime"] in INLINE
    return FileResponse(path, media_type=row["mime"] if inline else "application/octet-stream", headers={
        "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(row['name'])}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"})


@router.delete("/api/event-files/{fid}")
def delete_file(fid: str):
    row = core.db.event_file(fid) if re.fullmatch(r"[0-9a-f]{32}", fid) else None
    if not row:
        raise HTTPException(404, "Файл не найден")
    core.db.delete_event_file(fid)
    try:
        (files_dir() / fid).unlink(missing_ok=True)
    except OSError:
        pass
    core.events.invalidate()
    return {"ok": True}


class RouteIn(BaseModel):
    location: str


@router.post("/api/route")
def route(body: RouteIn):
    """Сколько ехать от дома до места (по карте, без пробок + запас). Адрес дома — в настройках поездок."""
    home = str(core.events.escort_settings().get("map_home") or "").strip()
    if not home:
        raise HTTPException(400, "Укажите адрес дома для карты: Настройки → Поездки детей")
    if not body.location.strip():
        raise HTTPException(400, "У события не указано место")
    try:
        minutes = routing.resolve(core.db, home, body.location, force=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Карта сейчас недоступна, попробуйте позже")
    if minutes is None:
        raise HTTPException(404, "Не удалось найти адрес на карте — уточните место события или адрес дома")
    core.events.invalidate()
    return {"minutes": minutes}
