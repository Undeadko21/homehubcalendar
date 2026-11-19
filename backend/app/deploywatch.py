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


def reason(data_dir: Path) -> tuple[str, str]:
    """Причина (data/.bad_reason) и строки отчёта проверки на копии базы (data/.canary_report) — коды и время, без данных."""
    def read(name: str) -> str:
        try:
            return (data_dir / name).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return read(".bad_reason"), " · ".join(read(".canary_report").splitlines()[:3])[:300]


def check(db: Database, data_dir: Path, version: str) -> str | None:
    sha = bad_commit(data_dir)
    if not sha:
        return None
    seen, _ = db.kv_get("deploy:notified")
    if (seen or {}).get("sha") != sha:
        db.kv_set("deploy:notified", {"sha": sha})
        why, rep = reason(data_dir)
        if why:   # не прошло проверку на копии базы — прежняя версия и не останавливалась
            text = (f"Обновление {sha[:7]} {why} и не установлено — работает прежняя версия {version}."
                    + (f" Что не так: {rep}." if rep else "") + " Следующее исправление в main подтянется само.")
        else:
            text = (f"Обновление {sha[:7]} не запустилось — сервер вернулся на прежнюю версию {version} и работает. "
                    "Следующее исправление в main подтянется само.")
        access.event(db, "deploy", text)
        access.notify(db, "HomeHub: обновление откатилось", text, priority="high")
    return sha


def problems(data_dir: Path) -> list[str]:
    sha = bad_commit(data_dir)
    if not sha:
        try:   # версия поставлена, но проверку на копии базы пришлось пропустить (deploy/update.sh, canary)
            note = (data_dir / ".canary_note").read_text(encoding="utf-8").strip()
        except OSError:
            return []
        return [f"Последнее обновление поставлено без проверки на копии базы: {note}"] if note else []
    why, rep = reason(data_dir)
    if why:
        return [f"Обновление {sha[:7]} {why}, работает прежняя версия" + (f" ({rep})" if rep else "")]
    return [f"Обновление {sha[:7]} не запустилось, работает прежняя версия (подробности: journalctl -u homecal-update на сервере)"]
