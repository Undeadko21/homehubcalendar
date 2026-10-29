"""Сквозные тесты в настоящем браузере: приложение + настоящий CalDAV-сервер (Radicale).

Запуск: нужен собранный фронтенд (`cd frontend && npm run build`), `pip install playwright radicale`
и `playwright install chromium`. Без них тесты пропускаются.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("radicale")
sync_api = pytest.importorskip("playwright.sync_api")
import caldav  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"
pytestmark = pytest.mark.skipif(not (DIST / "index.html").exists(), reason="фронтенд не собран")


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def _wait(port, path="/", tries=100):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1).read()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    raise RuntimeError(f"порт {port} не поднялся")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    rp, ap = _port(), _port()
    (tmp / "rad.cfg").write_text(f"[server]\nhosts = 127.0.0.1:{rp}\n[auth]\ntype = none\n[storage]\nfilesystem_folder = {tmp / 'rad'}\n")
    rad = subprocess.Popen([sys.executable, "-m", "radicale", "--config", str(tmp / "rad.cfg")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait(rp)
    client = caldav.DAVClient(url=f"http://127.0.0.1:{rp}", username="u", password="p")
    cal = client.principal().make_calendar(name="Дом", supported_calendar_component_set=["VEVENT"])
    tomorrow = date.today() + timedelta(days=1)
    t = tomorrow.strftime("%Y%m%d")
    cal.save_event(f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:x\nBEGIN:VEVENT\nUID:yoga@e2e\nDTSTAMP:20261029T000000Z\n"
                   f"DTSTART;TZID=Asia/Yekaterinburg:{t}T100000\nDTEND;TZID=Asia/Yekaterinburg:{t}T110000\nSUMMARY:Йога\nEND:VEVENT\nEND:VCALENDAR\n")
    (tmp / "c.yaml").write_text(
        f"timezone: Asia/Yekaterinburg\nsources:\n  - id: ya\n    type: caldav\n    url: http://127.0.0.1:{rp}\n"
        f"    username: u\n    password: p\n    people: [anna]\npeople:\n  - id: anna\n    name: Анна\n")
    env = {**os.environ, "HOMECAL_CONFIG": str(tmp / "c.yaml"), "HOMECAL_DATA_DIR": str(tmp), "HOMECAL_STATIC": str(DIST)}
    app = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(ap)], cwd=ROOT / "backend", env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait(ap, "/api/health")
    req = urllib.request.Request(f"http://127.0.0.1:{ap}/api/sync", method="POST")
    urllib.request.urlopen(req, timeout=60).read()
    yield {"url": f"http://127.0.0.1:{ap}", "cal": cal, "tomorrow": tomorrow.isoformat()}
    app.terminate(); rad.terminate()
    app.wait(10); rad.wait(10)


@pytest.fixture
def page(stack):
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"нет браузера: {e}")
        # Часовой пояс браузера = пояс календаря, иначе в CI (UTC) 10:00 по Екатеринбургу уходит за границу шкалы недели
        pg = b.new_context(viewport={"width": 1200, "height": 900}, timezone_id="Asia/Yekaterinburg").new_page()
        pg.goto(stack["url"])
        pg.wait_for_selector("text=Сегодня")
        yield pg
        b.close()


def _open_new(pg):
    pg.click('button[aria-label="Новое событие"], button:has-text("+")')
    pg.wait_for_selector("input[placeholder='Название']")


def _titles(cal):
    return sorted(str(e.icalendar_component.get("SUMMARY")) for e in cal.events())


def test_create_event_warns_about_conflict_and_writes_to_caldav(page, stack):
    _open_new(page)
    page.fill("#ee-sd", stack["tomorrow"]); page.fill("#ee-ed", stack["tomorrow"])
    page.locator("input[type=time]").nth(0).fill("10:30"); page.locator("input[type=time]").nth(1).fill("11:30")
    page.fill("input[placeholder='Название']", "Врач")
    page.wait_for_selector(".warns", timeout=5000)
    assert "Йога" in page.inner_text(".warns")
    page.click("button:has-text('Сохранить')")
    page.wait_for_selector("input[placeholder='Название']", state="detached", timeout=10000)
    assert "Врач" in _titles(stack["cal"])


def test_section_wizard_creates_series(page, stack):
    _open_new(page)
    page.click("text=Секция или кружок")
    page.fill("input[placeholder^='Название']", "Ушу")
    page.click("button.day:has-text('вт')"); page.click("button.day:has-text('чт')")
    page.click("button:has-text('Создать')")
    page.wait_for_selector(".wiz", state="detached", timeout=10000)
    evs = [e for e in stack["cal"].events() if "Ушу" in e.data]
    assert len(evs) == 1 and "BYDAY=TU,TH" in evs[0].data     # вт+чт с одинаковым временем — одна серия


def test_live_update_between_two_pages(page, stack):
    """Событие, созданное через API, появляется на открытой странице без перезагрузки."""
    page.click("text=Список")
    t = stack["tomorrow"]
    body = json.dumps({"calendar": next(c["key"] for c in json.load(urllib.request.urlopen(stack["url"] + "/api/config"))["calendars"]),
                       "title": "Живое событие", "start": f"{t}T15:00:00", "end": f"{t}T16:00:00"}).encode()
    time.sleep(1.5)
    urllib.request.urlopen(urllib.request.Request(stack["url"] + "/api/event", body, {"Content-Type": "application/json"}), timeout=30)
    page.wait_for_selector("text=Живое событие", timeout=8000)


def test_selftest_in_settings(page, stack):
    page.click("text=Настройки")
    page.click("text=Состояние")
    page.click("button:has-text('Проверить запись')")
    page.wait_for_selector("text=Удалить тестовое событие", timeout=30000)
    assert page.locator("span.err:has-text('✕')").count() == 0


def test_drag_event_in_week_view_moves_it_in_caldav(page, stack):
    """Перетаскивание на «Неделе» переносит событие на сервере (без конфликтов — без вопроса)."""
    page.click("text=Неделя")
    ev = page.locator(".fc-timegrid-event:has-text('Йога')").first
    ev.wait_for(timeout=10000)
    bb = ev.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + 8)
    page.mouse.down()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + 8 + 160, steps=15)   # на ~3 часа ниже
    page.mouse.up()
    deadline = time.time() + 10
    start = ""
    while time.time() < deadline:
        data = next(e.data for e in stack["cal"].events() if "Йога" in e.data)
        start = next(l for l in data.splitlines() if l.startswith("DTSTART"))
        if "T100000" not in start:
            break
        time.sleep(0.4)
    assert "T100000" not in start, start
