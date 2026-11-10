"""Сторож сборок приложений: версия в исходниках (android/version.properties, macos/version.txt, ios/version.txt)
против той, что реально раздаёт сервер (…/release/version.json). Если CI молча не собрал приложение (так было с macOS,
когда GitHub убрал образ macos-14), в «Состоянии» появляется строка — иначе об этом никто не узнает."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _expected_files() -> dict[str, Path]:
    d = os.environ.get("HOMECAL_VERSIONS_DIR")
    if d:   # в образе Docker файлы лежат рядом, под короткими именами
        return {"android": Path(d) / "android.properties", "mac": Path(d) / "macos.txt", "ios": Path(d) / "ios.txt"}
    return {"android": ROOT / "android" / "version.properties", "mac": ROOT / "macos" / "version.txt", "ios": ROOT / "ios" / "version.txt"}


def _read(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"versionName\s*=\s*(\S+)", text)
    return (m.group(1) if m else text.strip().splitlines()[0].strip()) or None if text.strip() else None


def _served(release_dir: Path) -> str | None:
    try:
        j = json.loads((release_dir / "version.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(j.get("versionName") or j.get("version") or "") or None


NAMES = {"android": "Android", "mac": "Mac", "ios": "iPhone"}


def status(dirs: dict[str, Path]) -> list[dict]:
    """По каждому приложению: что в исходниках, что раздаётся, отстаёт ли."""
    out = []
    for key, path in _expected_files().items():
        want, have = _read(path), _served(dirs[key])
        out.append({"app": key, "name": NAMES[key], "source": want, "served": have, "behind": bool(want and want != have)})
    return out


GRACE = timedelta(hours=1)   # CI собирает Mac и iPhone несколько минут после пуша — это не сбой


def problems(dirs: dict[str, Path], db=None, now: datetime | None = None) -> list[str]:
    """Отставание показываем, только если оно держится дольше часа (время первого наблюдения — в kv `builds:lag`)."""
    now = now or datetime.now()
    seen = dict((db.kv_get("builds:lag")[0] or {}) if db else {})
    out, fresh = [], {}
    for b in status(dirs):
        if not b["behind"]:
            continue
        key = f"{b['app']}:{b['source']}"
        first = seen.get(key) or now.isoformat(timespec="seconds")
        fresh[key] = first
        if not db or now - datetime.fromisoformat(first) >= GRACE:
            out.append(f"Приложение для {b['name']} не собралось: в исходниках {b['source']}, раздаётся {b['served'] or 'ничего'} "
                       "(проверьте сборку на GitHub)")
    if db and fresh != seen:
        db.kv_set("builds:lag", fresh)
    return out
