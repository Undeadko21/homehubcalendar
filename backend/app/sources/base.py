"""Базовый интерфейс источника календарей.

Чтобы добавить новый тип источника (Google, Outlook, что угодно):
1. создайте модуль в app/sources/,
2. унаследуйтесь от Source и реализуйте fetch(),
3. пометьте класс декоратором @register("тип"),
4. импортируйте модуль в app/sources/__init__.py.
После этого тип можно указывать в config.yaml: `type: тип`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

REGISTRY: dict[str, type["Source"]] = {}


def register(type_name: str):
    def deco(cls):
        REGISTRY[type_name] = cls
        cls.type_name = type_name
        return cls

    return deco


@dataclass
class RemoteCalendar:
    remote_id: str          # стабильный идентификатор календаря внутри источника
    name: str               # отображаемое имя
    color: str | None = None
    # href -> текст iCalendar (VCALENDAR). Каждый объект разворачивается отдельно.
    objects: dict[str, str] = field(default_factory=dict)
    ctag: str | None = None      # метка версии календаря на сервере (если сервер отдаёт)
    unchanged: bool = False      # ctag совпал с известным — объекты не загружались
    token: str | None = None     # sync-token (RFC 6578) на момент загрузки
    delta: bool = False          # объекты — только изменённые с прошлого токена, удалённые — в `deleted`
    deleted: set = field(default_factory=set)


class Source:
    type_name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id: str = cfg["id"]

    def fetch(self, known: dict[str, dict] | None = None) -> list[RemoteCalendar]:  # pragma: no cover - интерфейс
        """known: remote_id -> {"ctag", "token"} того, что уже загружено (можно не качать повторно / качать только изменения)."""
        raise NotImplementedError


def build_source(cfg: dict) -> Source:
    t = cfg.get("type")
    if t not in REGISTRY:
        raise ValueError(f"Неизвестный тип источника '{t}' (доступно: {', '.join(sorted(REGISTRY))})")
    return REGISTRY[t](cfg)
