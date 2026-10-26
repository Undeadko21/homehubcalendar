"""Загрузка настроек из config.yaml с подстановкой переменных окружения.

Секреты (логины, пароли приложений) хранятся в .env и подставляются
в config.yaml через синтаксис ${ИМЯ_ПЕРЕМЕННОЙ}.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_RE = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


@dataclass
class SyncSettings:
    interval_minutes: int = 10
    past_days: int = 90
    future_days: int = 400


@dataclass
class Settings:
    timezone: str = "Europe/Moscow"
    title: str = "Домашний календарь"
    data_dir: Path = Path("/data")
    sync: SyncSettings = field(default_factory=SyncSettings)
    sources: list[dict] = field(default_factory=list)
    people: list[dict] = field(default_factory=list)
    holidays: dict = field(default_factory=lambda: {"provider": "isdayoff", "country": "ru"})
    weather: dict = field(default_factory=dict)
    dedup: dict = field(default_factory=lambda: {"fuzzy": True})
    privacy: dict = field(default_factory=lambda: {"respect_event_class": False})
    pin: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "homecal.sqlite3"


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    path = Path(path or os.environ.get("HOMECAL_CONFIG", "/config/config.yaml"))
    raw: dict = {}
    if path.exists():
        raw = _expand_env(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    sync_raw = raw.get("sync") or {}
    settings = Settings(
        timezone=raw.get("timezone", "Europe/Moscow"),
        title=raw.get("title", "Домашний календарь"),
        data_dir=Path(os.environ.get("HOMECAL_DATA_DIR", raw.get("data_dir", "/data"))),
        sync=SyncSettings(**{k: v for k, v in sync_raw.items() if k in SyncSettings.__annotations__}),
        sources=raw.get("sources") or [],
        people=raw.get("people") or [],
        holidays=raw.get("holidays") or {"provider": "isdayoff", "country": "ru"},
        weather=raw.get("weather") or {},
        dedup=raw.get("dedup") or {"fuzzy": True},
        privacy=raw.get("privacy") or {"respect_event_class": False},
        pin=os.environ.get("HOMECAL_PIN", str(raw.get("pin", "") or "")),
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
