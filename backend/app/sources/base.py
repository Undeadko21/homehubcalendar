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


class Source:
    type_name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id: str = cfg["id"]

    def fetch(self) -> list[RemoteCalendar]:  # pragma: no cover - интерфейс
        raise NotImplementedError


def build_source(cfg: dict) -> Source:
    t = cfg.get("type")
    if t not in REGISTRY:
        raise ValueError(f"Неизвестный тип источника '{t}' (доступно: {', '.join(sorted(REGISTRY))})")
    return REGISTRY[t](cfg)
