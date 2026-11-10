"""Сообщение о неудачном автообновлении. deploy/update.sh при неудаче откатывается на прошлую версию и пишет
плохой коммит в data/.bad_commit (при успешном обновлении файл удаляется). Сервер, поднявшийся после отката,
видит этот файл и один раз на каждый плохой коммит шлёт уведомление; пока файл есть — строка в «Состоянии»."""
from __future__ import annotations

from pathlib import Path

from . import access
from .db import Database


def bad_commit(data_dir: Path) -> str | None:
    try:
        sha = (data_dir / ".bad_commit").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return sha or None


def check(db: Database, data_dir: Path, version: str) -> str | None:
    sha = bad_commit(data_dir)
    if not sha:
        return None
    seen, _ = db.kv_get("deploy:notified")
    if (seen or {}).get("sha") != sha:
        db.kv_set("deploy:notified", {"sha": sha})
        text = (f"Обновление {sha[:7]} не запустилось — сервер вернулся на прежнюю версию {version} и работает. "
                "Следующее исправление в main подтянется само.")
        access.event(db, "deploy", text)
        access.notify(db, "HomeHub: обновление откатилось", text, priority="high")
    return sha


def problems(data_dir: Path) -> list[str]:
    sha = bad_commit(data_dir)
    return [f"Обновление {sha[:7]} не запустилось, работает прежняя версия (подробности: journalctl -u homecal-update на сервере)"] if sha else []
