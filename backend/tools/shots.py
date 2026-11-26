"""Снимки экранов на демо-данных — для тестировщика интерфейса (помощник `ui-tester`) и ручной проверки.

    python backend/tools/shots.py                       # все виды: телефон и компьютер, светлая и тёмная тема
    python backend/tools/shots.py --views today,week    # только эти виды
    python backend/tools/shots.py --ask   # + открыть «+» и карточку события
    python backend/tools/shots.py --views none --scenes card-open,keys,settings:reminders,offline --devices phone,narrow,desktop

Сцены (--scenes, через запятую) — готовые состояния, чтобы не писать одноразовые скрипты:
    plus            быстрый ввод фразой из верхнего «+»
    card            карточка первого события («Список»)
    card-open       карточка с раскрытыми «Цвет события» и «Значок»
    editor          редактор нового события
    keys            лист «Горячие клавиши» (Shift+/; только компьютер)
    settings:<id>   страница настроек: people, calendars, trips, birthdays, reminders, sources, outside, app, news, look, wall,
                    changes, stats, system, cloud, address, devices, vps
    unusual:<вид>   полоса «Необычно на неделе» (week|family) с подставленным ответом /api/unusual (длинный текст);
                    unusual-open:<вид> — она же развёрнутая
    editor-repeat   редактор (компьютер — N, телефон — «+» → форма), начало — последняя пятница месяца, повтор «последнюю пятницу»
    push            «Напоминания» → блок «Уведомления в этом браузере» (прокручено вниз); push-dismiss — включение,
                    а браузер не дал разрешения (окно закрыто); push-on — включено (подписка подставлена)
    feedback        «Состояние» → «Сообщить о проблеме»: открытая форма с длинным текстом; feedback-sent — после отправки двух сообщений
    offline         офлайн-экран Android (assets/offline) на снимке этого сервера; offline-err — с ошибкой синхронизации

Нужно: собранный фронт (`cd frontend && npm run build`) и playwright с chromium (`python -m playwright install chromium`).
Поднимает сервер на временной базе с демо-календарями (tools/make_demo.py), ничего не трогает в настоящих данных.
Пишет PNG и index.txt (список файлов + ошибки консоли страницы на каждом снимке).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL_ROOT = ROOT   # копия, где лежит сам инструмент (--root может указать на другую)
DIST = ROOT / "frontend" / "dist"
VIEWS = ["today", "timeline", "week", "month", "family", "agenda", "lists", "free", "search", "settings"]
DEVICES = {"phone": {"width": 390, "height": 844, "mobile": True}, "narrow": {"width": 320, "height": 640, "mobile": True},
           "desktop": {"width": 1280, "height": 860, "mobile": False}, "desktop-narrow": {"width": 760, "height": 800, "mobile": False}}
OFFLINE = ROOT / "android/app/src/main/assets/offline/index.html"


def _open(page, url: str, view: str, q: str) -> None:
    page.goto(f"{url}/?view={view}&nointro{q}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def _first_card(page, url: str, q: str) -> bool:
    _open(page, url, "agenda", q)
    pill = page.locator("button.item").first
    if not pill.count():
        return False
    pill.click()
    page.wait_for_timeout(500)
    return True


UNUSUAL_FAKE = {"week": "2026-01-05", "items": [
    {"kind": "missing", "date": "", "uid": "a", "people": [], "text": "Пн: нет «Бассейн в спорткомплексе „Олимпийский“, группа продолжающих»"},
    {"kind": "moved", "date": "", "uid": "b", "people": [], "text": "Ср: «Английский язык с репетитором» в 18:30, обычно в 17:00"},
    {"kind": "absent", "date": "", "uid": "c", "people": [], "text": "Чт: Маша — не идёт на «Танцы» (болеет, справка до пятницы включительно)"},
    {"kind": "late", "date": "", "uid": "d", "people": [], "text": "Пт: поздно — «Концерт в филармонии» до 22:30 (Миша)"}]}


def scene(page, name: str, url: str, q: str, desktop: bool) -> str | None:
    """Привести страницу в состояние сцены. Возвращает None, если сцена не подходит устройству или не нашлось что открыть."""
    if name == "plus":
        _open(page, url, "today", q)
        add = page.locator("button.add-btn")
        opens_event = add.get_attribute("aria-label") == "Новое событие"
        add.click()
        if opens_event:
            editor = page.get_by_role("dialog", name="Новое событие")
            editor.get_by_role("button", name="Подробнее").click()
            editor.get_by_role("button", name="Частые события, дела и покупки").click()
    elif name in ("card", "card-open"):
        if not _first_card(page, url, q):
            return None
        if name == "card-open":
            for b in page.locator("button.color-row").all():
                b.click()
                page.wait_for_timeout(150)
    elif name == "keys":
        if not desktop:
            return None
        _open(page, url, "week", q)
        page.keyboard.press("Shift+Slash")
    elif name.startswith("settings:"):
        page.goto(f"{url}/?nointro{q}")
        page.evaluate(f"sessionStorage.setItem('settingsPage', {name.split(':', 1)[1]!r})")
        _open(page, url, "settings", q)
    elif name.startswith(("unusual:", "unusual-open:")):
        page.context.unroute("**/api/unusual*")
        page.context.route("**/api/unusual*", lambda r: r.fulfill(json=UNUSUAL_FAKE))
        _open(page, url, name.split(":", 1)[1], q)
        if name.startswith("unusual-open"):
            page.click(".uw .head")
    elif name in ("editor", "editor-repeat"):
        if desktop:
            _open(page, url, "week", q)
            page.keyboard.press("n")
        else:
            _open(page, url, "today", q)
            add = page.locator("button.add-btn")
            opens_event = add.get_attribute("aria-label") == "Новое событие"
            add.click()
            if not opens_event:   # демо без календаря с записью: открываем форму по N
                page.keyboard.press("Escape")
                page.get_by_role("dialog", name="Добавить фразой", exact=True).wait_for(state="detached")
                page.keyboard.press("n")
        page.locator(".editor").wait_for()
        if name == "editor-repeat":
            page.fill("#ee-sd", "2026-11-27")   # пятница, последняя в месяце (и 4-я)
            page.get_by_role("button", name="Подробнее").click()
            page.select_option("#ee-rep", "monthly_last")
            page.locator("#ee-rep").scroll_into_view_if_needed()
    elif name in ("push", "push-dismiss", "push-on"):
        if name == "push-dismiss":   # headless-браузер сразу «запрещено»; здесь — разрешения ещё не спрашивали, окно закрыли
            page.add_init_script("""Object.defineProperty(Notification, 'permission', { get: () => 'default' });
                Notification.requestPermission = async () => 'default'""")
        if name == "push-on":
            page.add_init_script("""PushManager.prototype.getSubscription = async () => ({ endpoint: 'https://push.example/x',
                toJSON: () => ({ endpoint: 'https://push.example/x', keys: {} }), unsubscribe: async () => true })""")
            page.context.unroute("**/api/push/**")
            page.context.route("**/api/push/**", lambda r: r.fulfill(json={"subscribed": True, "people": []}))
        page.goto(f"{url}/?nointro{q}")
        page.evaluate("sessionStorage.setItem('settingsPage', 'reminders')")
        _open(page, url, "settings", q)
        if name == "push-dismiss":
            page.click("#bp-on", force=True)
            page.wait_for_timeout(400)
            print(name, "галочка:", page.eval_on_selector("#bp-on", "e => e.checked"))
        page.locator("text=Уведомления в этом браузере").scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, 200); document.querySelectorAll('*').forEach(e => { if (e.scrollHeight > e.clientHeight + 5 && getComputedStyle(e).overflowY.match(/auto|scroll/)) e.scrollTop = e.scrollHeight })")
    elif name in ("feedback", "feedback-sent"):
        page.goto(f"{url}/?nointro{q}")
        page.evaluate("sessionStorage.setItem('settingsPage', 'system')")
        _open(page, url, "settings", q)
        long = "На неделе не открывается карточка бассейна у Маши, а в «Семье» полоса необычной недели перекрывает заголовок, если повернуть телефон"
        rounds = 2 if name == "feedback-sent" else 1
        for k in range(rounds):
            page.get_by_text("Что-то не так — написать разработчику").click()
            page.fill("textarea", long if k == 0 else "Коротко")
            if name == "feedback-sent":
                page.get_by_role("button", name="Отправить").click()
                page.wait_for_timeout(500)
        page.locator("text=Сообщить о проблеме").scroll_into_view_if_needed()
    elif name in ("offline", "offline-err"):
        snap = json.loads(urllib.request.urlopen(url + "/api/snapshot", timeout=30).read())
        status = {"error": "нет связи с Яндекс.Диском (timeout)"} if name == "offline-err" else {}
        page.add_init_script("window.HomeHubApp = { getSnapshot: () => %s, getPending: () => '[]', syncStatus: () => %s, syncNow(){}, retryHome(){} }"
                             % (json.dumps(json.dumps(snap, ensure_ascii=False)), json.dumps(json.dumps(status, ensure_ascii=False))))
        page.goto(OFFLINE.as_uri())
    else:
        raise SystemExit(f"неизвестная сцена: {name}")
    page.wait_for_timeout(500)
    return name.replace(":", "-")


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, sec: float = 40) -> None:
    end = time.time() + sec
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit(f"сервер не поднялся: {url}")


def start_demo(tmp: Path) -> tuple[subprocess.Popen, str]:
    demo = tmp / "demo"
    subprocess.run([sys.executable, str(ROOT / "backend/tools/make_demo.py"), str(demo)], check=True, capture_output=True)
    conf = next((p for p in (ROOT / "demo/config.yaml", TOOL_ROOT / "demo/config.yaml") if p.exists()), None)
    if conf:
        cfg = conf.read_text(encoding="utf-8").replace("url: demo/", f"url: {demo}/")
    else:
        import yaml

        people = [
            {"id": "papa", "name": "Папа", "color": "#4f7cff"},
            {"id": "mama", "name": "Мама", "color": "#ad438c"},
            {"id": "masha", "name": "Маша", "color": "#248355", "needs_escort": True},
        ]
        owners = {person["id"]: [person["id"]] for person in people}
        owners["family"] = ["papa", "mama", "masha"]
        sources = [
            {"id": path.stem, "type": "ics", "url": str(path), "people": owners.get(path.stem, [])}
            for path in sorted(demo.glob("*.ics"))
        ]
        cfg = yaml.safe_dump({"timezone": "Asia/Yekaterinburg", "people": people, "sources": sources}, allow_unicode=True)
    (tmp / "config.yaml").write_text(cfg, encoding="utf-8")
    port = _port()
    env = {**os.environ, "HOMECAL_CONFIG": str(tmp / "config.yaml"), "HOMECAL_DATA_DIR": str(tmp / "data"), "HOMECAL_STATIC": str(DIST)}
    (tmp / "data").mkdir()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=ROOT / "backend", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    _wait(url + "/api/health")
    urllib.request.urlopen(urllib.request.Request(url + "/api/sync", method="POST"), timeout=60).read()
    for _ in range(100):   # стартовая синхронизация могла идти параллельно — ждём событий
        if json.loads(urllib.request.urlopen(url + "/api/status", timeout=5).read()).get("sources"):
            break
        time.sleep(0.2)
    return proc, url


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, help="каталог снимков (по умолчанию новый временный каталог)")
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--devices", default="phone,desktop")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--ask", action="store_true", help="ещё снимки «+» и карточки первого события (= --scenes plus,card)")
    ap.add_argument("--scenes", default="", help="готовые состояния через запятую (см. начало файла)")
    ap.add_argument("--root", default="", help="другая копия проекта (её сервер, интерфейс и демо) — для visual_diff.py")
    ap.add_argument("--freeze", default="", help="часы браузера стоят на ЧЧ:ММ сегодняшнего дня (для сравнения снимков)")
    ap.add_argument("--size", default="", help="размер текста: compact | large (как в «Внешнем виде»)")
    ap.add_argument("--url", help="снимать уже запущенный сервер (песочница прода, tools/sandbox.py) вместо демо")
    a = ap.parse_args()
    if a.root:   # снимать другую копию проекта этим же инструментом (эталон в visual_diff.py)
        global ROOT, DIST, OFFLINE
        ROOT = Path(a.root).resolve()
        DIST = ROOT / "frontend" / "dist"
        OFFLINE = ROOT / "android/app/src/main/assets/offline/index.html"
    if not (DIST / "index.html").exists():
        raise SystemExit("нет frontend/dist — сначала: cd frontend && npm run build")
    from playwright import sync_api

    q = f"&size={a.size}" if a.size else ""
    scenes = [s for s in a.scenes.split(",") if s] + (["plus", "card"] if a.ask else [])
    views = [] if a.views in ("", "none") else a.views.split(",")
    out = a.out if a.out is not None else Path(tempfile.mkdtemp(prefix="hh-shots-"))
    out.mkdir(parents=True, exist_ok=True)
    index: list[str] = []
    with tempfile.TemporaryDirectory() as t:
        proc, url = (None, a.url.rstrip("/")) if a.url else start_demo(Path(t))
        try:
            with sync_api.sync_playwright() as p:
                browser = p.chromium.launch()
                for dev in a.devices.split(","):
                    d = DEVICES[dev]
                    for theme in a.themes.split(","):
                        ctx = browser.new_context(viewport={"width": d["width"], "height": d["height"]}, is_mobile=d["mobile"],
                                                  has_touch=d["mobile"], color_scheme=theme, timezone_id="Asia/Yekaterinburg", locale="ru-RU",
                                                  device_scale_factor=2 if d["mobile"] else 1)
                        ctx.add_init_script("try { localStorage.setItem('homecal.prefs', JSON.stringify({ onboarded: true, newsSeen: 999 })) } catch (e) {}")
                        # Внешний мир (погода и т.п.) не нужен и в песочнице недоступен — отрезаем, чтобы не шуметь в ошибках.
                        ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith((url, "file:")) else r.abort())
                        page = ctx.new_page()
                        if a.freeze:   # линия «сейчас», «через N мин» и т.п. одинаковы в обоих снимках (visual_diff.py)
                            from datetime import datetime as _dt, time as _t
                            from zoneinfo import ZoneInfo
                            hh, mm = map(int, a.freeze.split(":"))
                            page.clock.set_fixed_time(_dt.combine(_dt.now(ZoneInfo("Asia/Yekaterinburg")).date(), _t(hh, mm),
                                                                  ZoneInfo("Asia/Yekaterinburg")))
                        errors: list[str] = []
                        page.on("console", lambda m: m.type == "error" and "net::ERR_FAILED" not in m.text and errors.append(m.text[:300]))
                        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
                        for view in views:
                            errors.clear()
                            page.goto(f"{url}/?view={view}&nointro{q}")
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(700)
                            name = f"{dev}-{theme}{'-' + a.size if a.size else ''}-{view}.png"
                            page.screenshot(path=str(out / name), full_page=dev == "desktop")
                            index.append(name + ("  ОШИБКИ: " + " | ".join(errors) if errors else ""))
                        for sc in scenes:
                            errors.clear()
                            sp = ctx.new_page() if sc.startswith("offline") else page   # офлайн-экран — своя вкладка с мостом
                            if sp is not page:
                                sp.on("pageerror", lambda e: errors.append(str(e)[:300]))
                                sp.on("console", lambda m: m.type == "error" and errors.append(m.text[:300]))
                            tag = scene(sp, sc, url, q, not d["mobile"])
                            if tag:
                                name = f"{dev}-{theme}{'-' + a.size if a.size else ''}-{tag}.png"
                                sp.screenshot(path=str(out / name))
                                wide = sp.evaluate("document.documentElement.scrollWidth > innerWidth + 1")
                                index.append(name + ("  ШИРЕ ЭКРАНА" if wide else "") + ("  ОШИБКИ: " + " | ".join(errors) if errors else ""))
                            if sp is not page:
                                sp.close()
                            else:
                                page.keyboard.press("Escape")
                        ctx.close()
                browser.close()
        finally:
            if proc:
                proc.terminate()
                proc.wait(10)
    (out / "index.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{len(index)} снимков в {out}")
    for line in index:
        if "ОШИБКИ" in line:
            print(line)


if __name__ == "__main__":
    main()
