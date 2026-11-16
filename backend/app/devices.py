"""Единая страница «Устройства»: кто вошёл, какая версия приложения, когда был на связи и доходят ли команды из облака.

Собирает три источника в одну строку на устройство: вход (сессия), версия приложения из User-Agent и файл команд
`ops-<код>~<Модель>.bin` на Диске. Вход и файл сходятся по коду, который приложение сообщает само (`POST /api/devices/hello`)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SILENT = timedelta(days=14)   # дольше не заходили — помечаем «давно не было»


def latest(app_dir: Path, ios_dir: Path, mac_dir: Path) -> dict:
    """Версии приложений, которые сейчас раздаёт сервер."""
    out = {}
    for os_, d, key in (("android", app_dir, "versionName"), ("ios", ios_dir, "version"), ("mac", mac_dir, "version")):
        try:
            out[os_] = str(json.loads((d / "version.json").read_text(encoding="utf-8"))[key])
        except (OSError, ValueError, KeyError):
            pass
    return out


def _ver(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))


def _local(iso: str | None) -> str | None:
    """Время с Диска (UTC) → местное без пояса, как у остальных полей."""
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.astimezone().replace(tzinfo=None) if d.tzinfo else d).isoformat(timespec="seconds")


def overview(sessions: list[dict], cloud: dict, newest: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    files = {f["device"]: f for f in cloud.get("ops_devices") or []}
    bad = {b["device"]: b for b in cloud.get("ops_bad") or []}
    for code, b in bad.items():
        files.setdefault(code, {"name": b["name"], "device": code, "model": b.get("model"), "modified": b.get("modified")})
    used: set[str] = set()
    rows = []
    for s in sessions:
        row = {"id": s["id"], "label": s["label"], "via": s.get("via"), "ip": s.get("ip"), "last": s.get("last"),
               "current": s.get("current"), "app": s.get("app"), "os": s.get("os"), "model": None, "notes": []}
        want = newest.get(s.get("os") or "") if s.get("app") else None
        if want and _ver(s["app"]) < _ver(want):
            row["update"] = want
            row["notes"].append({"level": "warn", "text": f"Приложение {s['app']} — есть {want}, обновите"})
        dev = s.get("dev") or {}
        if dev.get("model"):
            row["model"] = dev["model"]
        code = dev.get("code")
        if code and code in files:
            used.add(code)
            row["cloud"] = _cloud(files[code], bad.get(code))
            if bad.get(code):
                row["notes"].append({"level": "warn", "text": "Команды вне дома не доходят — подключите заново кодом или QR"})
        try:
            if s.get("last") and now - datetime.fromisoformat(s["last"]) > SILENT:
                row["notes"].append({"level": "info", "text": "Давно не заходило"})
        except ValueError:
            pass
        rows.append(row)
    # Телефоны, которые шлют команды из облака, но входа с них не видно (приложение старое или вход был до обновления).
    extra = []
    for code, f in files.items():
        if code in used:
            continue
        extra.append({"code": code, "model": f.get("model"), "name": f["name"], **_cloud(f, bad.get(code))})
    extra.sort(key=lambda r: r.get("last") or "", reverse=True)
    return {"devices": rows, "cloud_only": extra, "latest": newest,
            "problems": sum(1 for r in rows if any(n["level"] == "warn" for n in r["notes"])) + sum(1 for r in extra if not r["ok"])}


def _cloud(f: dict, bad: dict | None) -> dict:
    return {"last": _local(f.get("modified")), "ok": not bad, "why": (bad or {}).get("why")}
