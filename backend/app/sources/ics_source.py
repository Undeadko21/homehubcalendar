"""Источник: ICS-ссылка (подписка) или локальный .ics-файл."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import httpx

from .base import RemoteCalendar, Source, register


RETRY_PAUSES = (2, 6)   # секунды между попытками скачать подписку


@register("ics")
class IcsSource(Source):
    """config.yaml:
        - id: school
          type: ics
          url: https://calendar.yandex.ru/export/ics.xml?private_token=...
          name: Школа          # необязательно
    url может быть и путём к локальному файлу (удобно для тестов).
    """

    def fetch(self, known: dict[str, dict] | None = None) -> list[RemoteCalendar]:
        url: str = self.cfg["url"]
        if url.startswith(("http://", "https://", "webcal://")):
            url = url.replace("webcal://", "https://", 1)
            # Ссылка подписки содержит секретный токен — в тексты ошибок её не пускаем.
            resp = None
            for attempt, pause in enumerate(RETRY_PAUSES + (None,)):    # разовый сбой связи или 5xx — пробуем ещё
                try:
                    resp = httpx.get(url, timeout=30, follow_redirects=True)
                    if resp.status_code < 500:
                        break
                except httpx.HTTPError as e:
                    if pause is None:
                        raise RuntimeError(f"Нет связи с сервером подписки ({type(e).__name__})") from None
                if pause is not None:
                    time.sleep(pause)
            if resp.status_code in (401, 403, 404):
                raise RuntimeError(f"Подписка недоступна (ответ {resp.status_code}): проверьте ссылку, возможно, она отозвана")
            if resp.status_code >= 400:
                raise RuntimeError(f"Сервер подписки ответил {resp.status_code}")
            text = resp.text
            if "BEGIN:VCALENDAR" not in text[:2000].upper():
                raise RuntimeError("По ссылке не календарь (ICS). Нужна ссылка вида …/calendar.ics")
        else:
            text = Path(url.removeprefix("file://")).read_text(encoding="utf-8")

        name = self.cfg.get("name") or _calname(text) or self.id
        return [RemoteCalendar(remote_id="feed", name=name, objects=split_feed(text))]


def _calname(text: str) -> str | None:
    for line in text.splitlines():
        if line.upper().startswith("X-WR-CALNAME:"):
            return line.split(":", 1)[1].strip()
    return None


_UID_RE = re.compile(r"^UID[:;][^\r\n]*?:?([^\r\n]*)$", re.M)


def split_feed(text: str) -> dict[str, str]:
    """Режет подписку на отдельные объекты по UID (серия + её исключения вместе).

    Один большой файл приходилось разбирать целиком при каждом открытии календаря; по одному событию
    expand.py пропускает всё, что вне нужных дат, не разбирая. Исходные строки сохраняются как есть.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    header: list[str] = []      # заголовок VCALENDAR и VTIMEZONE — кладём в каждый объект
    groups: dict[str, list[list[str]]] = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        up = line.upper()
        if up == "BEGIN:VEVENT":
            j = i
            while j < n and lines[j].upper() != "END:VEVENT":
                j += 1
            block = lines[i:j + 1]
            m = _UID_RE.search("\n".join(block))
            uid = (m.group(1).strip() if m else "") or hashlib.sha1("\n".join(block).encode()).hexdigest()
            groups.setdefault(uid, []).append(block)
            i = j + 1
        elif up in ("END:VCALENDAR", ""):
            i += 1
        elif up == "BEGIN:VTIMEZONE":
            j = i
            while j < n and lines[j].upper() != "END:VTIMEZONE":
                j += 1
            header.extend(lines[i:j + 1])
            i = j + 1
        else:
            header.append(line)
            i += 1
    if not groups:
        return {"feed.ics": text}
    head = [l for l in header if not l.upper().startswith("X-WR-")] or ["BEGIN:VCALENDAR"]
    if head[0].upper() != "BEGIN:VCALENDAR":
        head.insert(0, "BEGIN:VCALENDAR")
    out = {}
    for uid, blocks in groups.items():
        body = [l for b in blocks for l in b]
        out[hashlib.sha1(uid.encode()).hexdigest()[:20] + ".ics"] = "\r\n".join(head + body + ["END:VCALENDAR"]) + "\r\n"
    return out
