"""Источник: ICS-ссылка (подписка) или локальный .ics-файл."""
from __future__ import annotations

from pathlib import Path

import httpx

from .base import RemoteCalendar, Source, register


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
            try:
                resp = httpx.get(url, timeout=30, follow_redirects=True)
            except httpx.HTTPError as e:
                raise RuntimeError(f"Нет связи с сервером подписки ({type(e).__name__})") from None
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
        return [RemoteCalendar(remote_id="feed", name=name, objects={"feed.ics": text})]


def _calname(text: str) -> str | None:
    for line in text.splitlines():
        if line.upper().startswith("X-WR-CALNAME:"):
            return line.split(":", 1)[1].strip()
    return None
