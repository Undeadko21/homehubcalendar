from .base import REGISTRY, RemoteCalendar, Source, build_source, register  # noqa: F401

# Импорт модулей регистрирует типы источников.
from . import caldav_source, ics_source  # noqa: F401,E402
