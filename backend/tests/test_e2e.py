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
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    today = datetime.now(ZoneInfo("Asia/Yekaterinburg")).date()
    monday = today + timedelta(days=7 - today.weekday())
    t = monday.strftime("%Y%m%d")
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
    # Если в этот момент уже шла стартовая синхронизация, ручная возвращается сразу — ждём, пока календарь действительно появится.
    for _ in range(150):
        cfg = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{ap}/api/config", timeout=5).read())
        if any(c.get("writable") for c in cfg.get("calendars", [])):
            break
        time.sleep(0.2)
    yield {"url": f"http://127.0.0.1:{ap}", "cal": cal, "event_day": monday.isoformat()}
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
        ctx = b.new_context(viewport={"width": 1200, "height": 900}, timezone_id="Asia/Yekaterinburg")
        # знакомство для нового устройства в тестах не нужно
        ctx.add_init_script("try { localStorage.setItem('homecal.prefs', JSON.stringify({ onboarded: true })) } catch (e) {}")
        pg = ctx.new_page()
        pg.clock.set_fixed_time(datetime.fromisoformat(stack["event_day"] + "T08:00:00+05:00"))
        pg.goto(stack["url"])
        pg.wait_for_selector("text=Сегодня")
        # «+» рисуется только после загрузки настроек (есть пишущий календарь) — ждём именно его, а не первую надпись
        pg.wait_for_selector("button.add-btn", timeout=20000)
        yield pg
        b.close()


def _open_new(pg):
    pg.locator('header .add-btn[aria-label="Новое событие"]').click()
    pg.wait_for_selector("input[placeholder='Название']")


def _titles(cal):
    return sorted(str(e.icalendar_component.get("SUMMARY")) for e in cal.events())


def _wait_for_title(cal, title):
    deadline = time.monotonic() + 10
    while title not in _titles(cal):
        assert time.monotonic() < deadline, f"Событие «{title}» не появилось в CalDAV"
        time.sleep(0.1)


def test_create_event_warns_about_conflict_and_writes_to_caldav(page, stack):
    _open_new(page)
    assert not page.locator("#ee-ed").is_visible()
    assert not page.locator("#ee-rep").is_visible()
    page.fill("#ee-sd", stack["event_day"])
    page.locator("input[type=time]").nth(0).fill("10:30"); page.locator("input[type=time]").nth(1).fill("11:30")
    page.fill("input[placeholder='Название']", "Врач")
    page.wait_for_selector(".warns", timeout=5000)
    assert "Йога" in page.inner_text(".warns")
    page.click("button:has-text('Сохранить')")
    page.wait_for_selector("input[placeholder='Название']", state="detached", timeout=10000)
    _wait_for_title(stack["cal"], "Врач")
    page.click("text=Список")
    page.locator("button.item").filter(has_text="Врач").click()
    page.get_by_text("Последняя правка отправлена в Яндекс.", exact=True).wait_for()


def test_section_wizard_creates_series(page, stack):
    _open_new(page)
    page.get_by_role("button", name="Подробнее").click()
    page.click(".editor >> text=Секция или кружок")
    page.fill(".wiz input[placeholder^='Название']", "Ушу")
    page.click("button.day:has-text('вт')"); page.click("button.day:has-text('чт')")
    page.click("button:has-text('Создать')")
    page.wait_for_selector(".wiz", state="detached", timeout=10000)
    evs = [e for e in stack["cal"].events() if "Ушу" in e.data]
    assert len(evs) == 1 and "BYDAY=TU,TH" in evs[0].data     # вт+чт с одинаковым временем — одна серия


def test_create_multiday_event_with_collapsed_details(page, stack):
    _open_new(page)
    day = datetime.fromisoformat(stack["event_day"])
    last_day = (day + timedelta(days=2)).date().isoformat()
    page.get_by_role("textbox", name="Название").fill("Семейная поездка на три дня")
    page.locator("#ee-all").check()
    page.get_by_role("button", name="Подробнее").click()
    page.fill("#ee-ed", last_day)
    page.get_by_role("button", name="Подробнее").click()
    assert page.locator("#ee-ed").input_value() == last_day
    assert not page.locator("input[type=time]").count()
    page.get_by_role("button", name="Сохранить").click()
    page.locator(".editor").wait_for(state="detached", timeout=10000)
    _wait_for_title(stack["cal"], "Семейная поездка на три дня")
    event = next(e.icalendar_component for e in stack["cal"].events()
                 if e.icalendar_component.get("SUMMARY") == "Семейная поездка на три дня")
    assert event.decoded("DTSTART") == day.date()
    assert event.decoded("DTEND") == (day + timedelta(days=3)).date()


def test_create_event_retry_after_lost_response_uses_same_request(page, stack):
    requests = []

    def lose_first_response(route):
        requests.append(route.request.post_data_json)
        if len(requests) == 1:
            response = route.fetch(timeout=10000)
            assert response.ok and response.json()["uid"]
            route.abort("connectionreset")
        else:
            route.continue_()

    page.route("**/api/event", lose_first_response)
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    event.get_by_role("textbox", name="Название").fill("Проверка повтора записи")
    event.get_by_role("button", name="Сохранить").click()
    sync_api.expect(event.get_by_role("alert")).to_contain_text("Нет подтверждения сохранения")
    assert event.get_by_role("textbox", name="Название").input_value() == "Проверка повтора записи"
    event.get_by_role("button", name="Повторить").click()
    event.wait_for(state="detached", timeout=10000)
    assert len(requests) == 2 and requests[0] == requests[1] and requests[0]["request_id"]
    _wait_for_title(stack["cal"], "Проверка повтора записи")
    assert _titles(stack["cal"]).count("Проверка повтора записи") == 1


def test_create_event_timeout_shows_progress_then_retry(page):
    page.evaluate("""() => {
        const fetchReal = window.fetch.bind(window)
        const setTimeoutReal = window.setTimeout.bind(window)
        window.setTimeout = (fn, ms, ...args) => setTimeoutReal(fn, ms === 12000 ? 900 : ms, ...args)
        window.fetch = (url, init) => url === '/api/event' && init.method === 'POST'
            ? new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason)))
            : fetchReal(url, init)
    }""")
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    event.get_by_role("textbox", name="Название").fill("Проверка таймаута")
    event.get_by_role("button", name="Сохранить").click()
    sync_api.expect(event.get_by_text("Сохраняем событие…", exact=True)).to_be_visible()
    sync_api.expect(event.get_by_role("alert")).to_contain_text("Нет подтверждения сохранения")
    sync_api.expect(event.get_by_role("button", name="Повторить")).to_be_enabled()


def test_create_event_reports_invalid_time_before_sending(page):
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    event.get_by_role("textbox", name="Название").fill("Время обязательно")
    event.locator("input[type=time]").last.fill("")
    event.get_by_role("button", name="Сохранить").click()
    sync_api.expect(event.get_by_role("alert")).to_contain_text("Укажите корректное время")


def test_event_phrase_fills_current_form_with_one_parse(page, stack):
    requests = []

    def parsed(route):
        requests.append(route.request.post_data_json["text"])
        route.fulfill(json={"kind": "event", "title": "Танцы", "date": stack["event_day"], "start": "18:15",
                            "end": "19:45", "all_day": False, "people": [], "notes": [], "repeat": {"freq": "weekly"}})

    page.route("**/api/quick", parsed)
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    event.get_by_role("textbox", name="Место").fill("Спортзал")
    phrase = event.get_by_role("textbox", name="Добавить фразой", exact=True)
    phrase.fill("Танцы в 18:15–19:45 каждую неделю")
    phrase.press("Enter")
    sync_api.expect(event.get_by_role("textbox", name="Название")).to_have_value("Танцы")
    assert not page.get_by_role("dialog", name="Добавить фразой", exact=True).is_visible()
    assert event.get_by_role("textbox", name="Место").input_value() == "Спортзал"
    assert page.locator("input[type=time]").evaluate_all("inputs => inputs.map(input => input.value)") == ["18:15", "19:45"]
    assert not page.locator("#ee-rep").is_visible()
    page.get_by_role("button", name="Подробнее").click()
    assert page.locator("#ee-rep").input_value() == "weekly"
    assert requests == ["Танцы в 18:15–19:45 каждую неделю"]


def test_event_microphone_fills_same_dialog_on_phone(page, stack):
    page.set_viewport_size({"width": 320, "height": 640})
    page.add_init_script("""
        window.HomeHubApp = {
            canVoice: () => true,
            startVoice: () => window.__hhVoice('Встреча в 18:00'),
        }
    """)
    def parsed(route):
        text = route.request.post_data_json["text"]
        if text == "Купить молоко":
            route.fulfill(json={"kind": "shopping", "items": ["молоко"]})
        else:
            assert text == "Встреча в 18:00"
            route.fulfill(json={"kind": "event", "title": "Встреча", "date": stack["event_day"],
                                "start": "18:00", "end": "19:00", "all_day": False, "people": [], "notes": []})

    page.route("**/api/quick", parsed)
    page.reload()
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    title = event.get_by_role("textbox", name="Название")
    title.fill("День рождения")
    event.get_by_role("textbox", name="Добавить фразой", exact=True).fill("Купить молоко")
    event.get_by_role("button", name="Заполнить", exact=True).click()
    sync_api.expect(event.get_by_role("alert")).to_contain_text("Введите фразу о событии")
    assert title.input_value() == "День рождения"
    mic = event.get_by_role("button", name="Сказать голосом", exact=True)
    sync_api.expect(mic).to_be_in_viewport()
    mic.click()
    sync_api.expect(title).to_have_value("Встреча")
    assert event.locator("input[type=time]").first.input_value() == "18:00"


def test_event_phrase_keeps_manually_selected_date_time_and_repeat(page, stack):
    _open_new(page)
    event = page.get_by_role("dialog", name="Новое событие", exact=True)
    selected_date = (datetime.fromisoformat(stack["event_day"]) + timedelta(days=2)).date().isoformat()
    event.locator("#ee-sd").fill(selected_date)
    event.locator("input[type=time]").first.fill("18:00")
    event.locator("input[type=time]").last.fill("20:00")
    event.get_by_role("button", name="Подробнее").click()
    event.locator("#ee-rep").select_option("weekly")
    phrase = event.get_by_role("textbox", name="Добавить фразой", exact=True)
    phrase.fill("Танцы")
    phrase.press("Enter")
    sync_api.expect(event.get_by_role("textbox", name="Название")).to_have_value("Танцы")
    assert event.locator("#ee-sd").input_value() == selected_date
    assert event.locator("input[type=time]").evaluate_all("inputs => inputs.map(input => input.value)") == ["18:00", "20:00"]
    assert event.locator("#ee-rep").input_value() == "weekly"


def test_live_update_between_two_pages(page, stack):
    """Событие, созданное через API, появляется на открытой странице без перезагрузки."""
    page.click("text=Список")
    t = stack["event_day"]
    body = json.dumps({"calendar": next(c["key"] for c in json.load(urllib.request.urlopen(stack["url"] + "/api/config"))["calendars"]),
                       "title": "Живое событие", "start": f"{t}T15:00:00", "end": f"{t}T16:00:00"}).encode()
    time.sleep(1.5)
    urllib.request.urlopen(urllib.request.Request(stack["url"] + "/api/event", body, {"Content-Type": "application/json"}), timeout=30)
    page.wait_for_selector("text=Живое событие", timeout=8000)


def test_selftest_in_settings(page, stack):
    page.click("text=Настройки")
    page.click(".menu-col .menu-row:has-text('Состояние и копии')")
    page.click(".detail .menu-row:has-text('Проверки')")
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


def test_drag_on_empty_week_slot_opens_new_event_for_that_time(page, stack):
    """Протянуть мышью по пустому месту «Недели» — форма нового события на этот отрезок (шаг 15 минут)."""
    page.click("text=Неделя")
    page.locator(".fc-timegrid-event").first.wait_for(timeout=10000)
    page.wait_for_timeout(1500)   # неделя дорисовывается (праздники, подсветка выходных) — протяжку во время перерисовки она теряет
    lane = page.locator(".fc-timegrid-slot-lane[data-time='20:00:00']").first
    lane.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, 200)")   # чтобы протяжка вниз тоже была на экране
    col = page.locator(".fc-timegrid-col").last.bounding_box()
    slot = lane.bounding_box()
    x, y = col["x"] + col["width"] / 2, slot["y"] + 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + slot["height"] * 3, steps=10)   # ~1,5 часа вниз
    page.mouse.up()
    page.wait_for_selector("input[placeholder='Название']")
    t = page.locator("input[type=time]")
    a, b = t.nth(0).input_value(), t.nth(1).input_value()
    assert a == "20:00", (a, b)
    assert b > a and b[3:] in ("00", "15", "30", "45"), (a, b)
    page.click("text=Отмена")


def test_offline_shell_and_last_data(page, stack):
    """Офлайн-версия: без связи страница открывается из кэша, показывает последние данные и полосу «Нет связи»."""
    page.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller !== null", timeout=20000)
    page.evaluate("navigator.serviceWorker.ready.then((r) => r.active.postMessage('precache'))")
    page.evaluate("fetch('/api/lists').then((r) => r.json())")
    # все файлы экранов из списка сборки должны оказаться в кэше (в том числе ещё не открытые «Настройки»)
    page.wait_for_function(
        """async () => { const want = await (await fetch('/precache.json')).json(); const c = await caches.open('hh-shell-v1');
                         const have = (await c.keys()).map((r) => new URL(r.url).pathname);
                         return want.every((f) => have.includes(f)) && have.includes('/') }""", timeout=20000)
    page.context.set_offline(True)
    page.reload()
    page.wait_for_selector("button.add-btn", timeout=20000)          # настройки взялись из кэша
    page.wait_for_selector(".netbar", timeout=20000)
    cached = page.evaluate("fetch('/api/lists').then(async (r) => ({ mark: r.headers.get('X-HH-Cached'), ok: Array.isArray((await r.json())) || true }))")
    assert cached["mark"] == "1"
    page.click("text=Настройки")                                     # отдельный файл экрана — тоже из кэша
    page.wait_for_selector(".settings", timeout=10000)
    page.context.set_offline(False)
