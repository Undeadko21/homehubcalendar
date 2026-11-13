"""Сторож версии: сервер обновляется сам из ветки main (deploy/update.sh раз в 15 минут). Если он больше часа работает
не на последнем коммите — значит, обновление не проходит (не собирается образ, нет сети, остановлен таймер).
Раз в полчаса спрашиваем GitHub о голове main; отставание дольше LAG — строка в «Состоянии» и одно уведомление на коммит.
Репозиторий — `HOMECAL_REPO` (по умолчанию тот, из которого собран сервер); без номера сборки (запуск не из образа) проверка выключена."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from . import access
from .db import Database

REPO = os.environ.get("HOMECAL_REPO", "Undeadko21/homehubcalendar")
BRANCH = os.environ.get("HOMECAL_BRANCH", "main")
LAG = timedelta(minutes=60)
KEY = "version:watch"


def head(client=None) -> tuple[str, datetime] | None:
    """(sha, время коммита) головы ветки или None, если GitHub недоступен."""
    try:
        get = (client or httpx).get
        r = get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", timeout=15,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "HomeHubCalendar"})
        if r.status_code != 200:
            return None
        d = r.json()
        return d["sha"], datetime.fromisoformat(d["commit"]["committer"]["date"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def check(db: Database, build: str, now: datetime | None = None, client=None) -> dict:
    """Обновляет состояние; возвращает {behind, sha, since}."""
    if not build:
        return {}
    now = now or datetime.now(timezone.utc)
    st = dict(db.kv_get(KEY)[0] or {})
    h = head(client)
    if h is None:                       # нет связи с GitHub — ничего не знаем, прежний вывод не трогаем
        return st
    sha, when = h
    behind = not sha.startswith(build) and now - when > LAG
    st.update(sha=sha, since=when.isoformat(timespec="seconds"), behind=behind, checked=now.isoformat(timespec="seconds"))
    if behind and st.get("notified") != sha:
        st["notified"] = sha
        hours = int((now - when).total_seconds() // 3600)
        text = (f"Сервер дома не обновился: работает сборка {build}, а в main уже {sha[:7]} ({hours} ч назад). "
                "Проверьте на сервере: journalctl -u homecal-update -n 50")
        access.event(db, "deploy", text)
        access.notify(db, "HomeHub: обновление не доходит", text, priority="high")
    db.kv_set(KEY, st)
    return st


def problems(db: Database, build: str) -> list[str]:
    st = db.kv_get(KEY)[0] or {}
    if not build or not st.get("behind") or str(st.get("sha", "")).startswith(build):
        return []
    return [f"Сервер не обновляется: работает сборка {build}, последняя — {st['sha'][:7]} "
            f"(с {st['since'][:16].replace('T', ' ')} UTC). На сервере: journalctl -u homecal-update -n 50"]
