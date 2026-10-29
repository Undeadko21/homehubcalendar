"""Раздача приложений (Android, macOS, iPhone/AltStore) и сведений об их версиях."""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from fastapi import APIRouter

from .. import core

router = APIRouter()


@router.get("/api/app")
def get_app():
    """Последняя версия приложения для Android, которую раздаёт этот сервер."""
    meta = core.APP_DIR / "version.json"
    apk = core.APP_DIR / "homehub-calendar.apk"
    if not (meta.exists() and apk.exists()):
        return {"available": False}
    import json
    info = json.loads(meta.read_text(encoding="utf-8"))
    return {"available": True, "url": "/app.apk", "size": apk.stat().st_size, **info}


@router.get("/app.apk", include_in_schema=False)
def download_app():
    apk = core.APP_DIR / "homehub-calendar.apk"
    if not apk.exists():
        raise HTTPException(404, "Приложение ещё не собрано")
    return FileResponse(apk, media_type="application/vnd.android.package-archive",
                        filename="homehub-calendar.apk")


@router.get("/api/app-mac")
def get_app_mac():
    """Сборка приложения для macOS (кладёт в репозиторий GitHub Actions)."""
    meta = core.MAC_DIR / "version.json"
    zip_ = core.MAC_DIR / "HomeHub-Calendar.zip"
    if not (meta.exists() and zip_.exists()):
        return {"available": False}
    import json
    return {"available": True, "url": "/app-mac.zip", "size": zip_.stat().st_size,
            **json.loads(meta.read_text(encoding="utf-8"))}


@router.get("/app-mac.zip", include_in_schema=False)
def download_app_mac():
    f = core.MAC_DIR / "HomeHub-Calendar.zip"
    if not f.exists():
        raise HTTPException(404, "Приложение для Mac ещё не собрано")
    return FileResponse(f, media_type="application/zip", filename="HomeHub-Calendar.zip")


def _ios_release() -> dict | None:
    meta, ipa = core.IOS_DIR / "version.json", core.IOS_DIR / "HomeHub-Calendar.ipa"
    if not (meta.exists() and ipa.exists()):
        return None
    import json
    return {**json.loads(meta.read_text(encoding="utf-8")), "size": ipa.stat().st_size}


@router.get("/api/app-ios")
def get_app_ios():
    rel = _ios_release()
    return {"available": False} if not rel else {"available": True, "url": "/app-ios.ipa", **rel}


@router.get("/app-ios.ipa", include_in_schema=False)
def download_app_ios():
    f = core.IOS_DIR / "HomeHub-Calendar.ipa"
    if not f.exists():
        raise HTTPException(404, "Приложение для iPhone ещё не собрано")
    return FileResponse(f, media_type="application/octet-stream", filename="HomeHub-Calendar.ipa")


@router.get("/altstore-icon.png", include_in_schema=False)
def altstore_icon():
    f = core.IOS_DIR / "icon.png"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/png")


@router.get("/altstore.json", include_in_schema=False)
def altstore_source(request: Request):
    """Источник для AltStore: добавьте этот адрес в AltStore → Sources, и приложение будет ставиться и обновляться оттуда."""
    rel = _ios_release() or {}
    base = str(request.base_url).rstrip("/")
    version = {"version": rel.get("version", "1.0"), "buildVersion": str(rel.get("build", 1)), "date": rel.get("date", "2026-01-01"),
               "size": rel.get("size", 0), "downloadURL": f"{base}/app-ios.ipa", "minOSVersion": "16.0",
               "localizedDescription": "Окно календаря, ближайшие события и напоминания."}
    app_ = {"name": "Домашний календарь", "bundleIdentifier": "ru.homehub.calendar.ios", "developerName": "HomeHub",
            "subtitle": "Семейный календарь", "tintColor": "FF3B30", "iconURL": f"{base}/altstore-icon.png",
            "localizedDescription": "Семейный календарь: общий вид дня, поездки детей, ближайшие события и напоминания. Вне дома читает снимок из облака.",
            "screenshotURLs": [], "versions": [version],
            # поля прежнего формата источников — для старых версий AltStore
            "version": version["version"], "versionDate": version["date"], "size": version["size"],
            "downloadURL": version["downloadURL"]}
    return {"name": "Домашний календарь", "identifier": "ru.homehub.calendar.source", "sourceURL": f"{base}/altstore.json",
            "apps": [app_] if rel else [], "news": []}
