"""Источник: CalDAV-сервер (Яндекс, Nextcloud, iCloud, Radicale...).

Для Яндекса:
    url: https://caldav.yandex.ru
    username: логин@yandex.ru
    password: пароль приложения (Яндекс ID → Безопасность → Пароли приложений → Календарь)
"""
from __future__ import annotations

import logging

import caldav

from .base import RemoteCalendar, Source, register

log = logging.getLogger(__name__)


@register("caldav")
class CalDavSource(Source):
    def fetch(self, known: dict[str, dict] | None = None) -> list[RemoteCalendar]:
        include = [s.lower() for s in self.cfg.get("include", [])]
        exclude = [s.lower() for s in self.cfg.get("exclude", [])]

        with caldav.DAVClient(
            url=self.cfg["url"],
            username=self.cfg.get("username"),
            password=self.cfg.get("password"),
            timeout=60,
        ) as client:
            principal = client.principal()
            result: list[RemoteCalendar] = []
            for cal in principal.calendars():
                name = _display_name(cal)
                lname = name.lower()
                if include and not any(s in lname for s in include):
                    continue
                if any(s in lname for s in exclude):
                    continue
                if not _supports_events(cal):
                    continue
                rid = _remote_id(cal)
                ctag = _ctag(cal)
                k = (known or {}).get(rid) or {}
                if ctag and k.get("ctag") == ctag:
                    # Календарь не менялся с прошлой загрузки — объекты не качаем.
                    result.append(RemoteCalendar(remote_id=rid, name=name, color=_color(cal), ctag=ctag, token=k.get("token"),
                                                 unchanged=True))
                    continue
                if k.get("token"):
                    delta = _delta(cal, k["token"])
                    if delta is not None:
                        changed, deleted, token = delta
                        result.append(RemoteCalendar(remote_id=rid, name=name, color=_color(cal), ctag=ctag, token=token,
                                                     delta=True, objects=changed, deleted=deleted))
                        continue
                # Полная загрузка. Токен берём ДО неё: всё, что изменится после, придёт в следующей дельте.
                token = _initial_token(cal)
                objects: dict[str, str] = {}
                for ev in _all_events(cal):
                    data = ev.data
                    if data and "BEGIN:VEVENT" in data:
                        objects[str(ev.url)] = data
                result.append(
                    RemoteCalendar(
                        remote_id=_remote_id(cal),
                        name=name,
                        color=_color(cal),
                        objects=objects,
                        ctag=ctag,
                        token=token,
                    )
                )
            return result


def _initial_token(cal) -> str | None:
    """sync-token на сейчас (без загрузки данных). None — сервер не поддерживает sync-collection."""
    try:
        res = cal.get_objects_by_sync_token(sync_token=None, load_objects=False, disable_fallback=True)
        if getattr(res, "truncated", False):
            return None
        return str(res.sync_token) if res.sync_token else None
    except Exception as e:  # noqa: BLE001 — не поддерживается: работаем по ctag
        log.debug("sync-token недоступен: %s", e)
        return None


def _delta(cal, token: str):
    """Изменения с прошлого токена: (изменённые {href: ics}, удалённые {href}, новый токен). None — нужна полная загрузка."""
    try:
        res = cal.get_objects_by_sync_token(sync_token=token, load_objects=True, disable_fallback=True)
        if getattr(res, "truncated", False) or not res.sync_token:
            return None
        deleted = {str(u) for u in res.deleted_urls}
        changed: dict[str, str] = {}
        for obj in res:
            href = str(obj.url)
            if str(obj.url.canonical()) in deleted:
                continue
            data = obj.data
            if not data or "BEGIN:VEVENT" not in data:
                return None    # не смогли прочитать объект — надёжнее скачать всё
            changed[href] = data
        return changed, deleted, str(res.sync_token)
    except Exception as e:  # noqa: BLE001 — токен устарел или сервер не умеет: полная загрузка
        log.info("Дельта по sync-token не получилась (%s), загружаю всё", e)
        return None


def _ctag(cal) -> str | None:
    """CS:getctag — меняется при любом изменении календаря (поддерживает Яндекс, Nextcloud, Radicale)."""
    try:
        from caldav.elements.base import BaseElement

        class GetCTag(BaseElement):
            tag = "{http://calendarserver.org/ns/}getctag"

        v = cal.get_property(GetCTag())
        return str(v) if v else None
    except Exception:  # noqa: BLE001
        return None


def _remote_id(cal) -> str:
    path = str(cal.url).rstrip("/")
    return path.rsplit("/", 1)[-1] or path


def _display_name(cal) -> str:
    for getter in (lambda: cal.get_display_name(), lambda: cal.name):
        try:
            v = getter()
            if v:
                return str(v)
        except Exception:  # noqa: BLE001 — серверы отвечают по-разному
            pass
    return _remote_id(cal)


def _supports_events(cal) -> bool:
    try:
        comps = cal.get_supported_components()
        return not comps or "VEVENT" in comps
    except Exception:  # noqa: BLE001
        return True


def _all_events(cal):
    for getter in ("get_events", "events"):
        fn = getattr(cal, getter, None)
        if fn:
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                log.debug("%s failed: %s", getter, e)
    return cal.search(event=True)


def _color(cal) -> str | None:
    try:
        from caldav.elements import ical

        v = cal.get_property(ical.CalendarColor())
        if v:
            return str(v)[:7]
    except Exception:  # noqa: BLE001
        pass
    return None
