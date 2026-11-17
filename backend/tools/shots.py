"""Снимки экранов на демо-данных — для тестировщика интерфейса (помощник `ui-tester`) и ручной проверки.

    python backend/tools/shots.py                       # все виды: телефон и компьютер, светлая и тёмная тема
    python backend/tools/shots.py --views today,week    # только эти виды
    python backend/tools/shots.py --out /tmp/shots --ask   # + открыть «+» и карточку события

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
DIST = ROOT / "frontend" / "dist"
VIEWS = ["today", "timeline", "week", "month", "family", "agenda", "lists", "free", "search", "settings"]
DEVICES = {"phone": {"width": 390, "height": 844, "mobile": True}, "desktop": {"width": 1280, "height": 860, "mobile": False}}


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
    cfg = (ROOT / "demo/config.yaml").read_text(encoding="utf-8").replace("url: demo/", f"url: {demo}/")
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
    ap.add_argument("--out", default="/tmp/shots")
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--devices", default="phone,desktop")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--ask", action="store_true", help="ещё снимки «+» и карточки первого события")
    a = ap.parse_args()
    if not (DIST / "index.html").exists():
        raise SystemExit("нет frontend/dist — сначала: cd frontend && npm run build")
    from playwright import sync_api

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    index: list[str] = []
    with tempfile.TemporaryDirectory() as t:
        proc, url = start_demo(Path(t))
        try:
            with sync_api.sync_playwright() as p:
                browser = p.chromium.launch()
                for dev in a.devices.split(","):
                    d = DEVICES[dev]
                    for theme in a.themes.split(","):
                        ctx = browser.new_context(viewport={"width": d["width"], "height": d["height"]}, is_mobile=d["mobile"],
                                                  has_touch=d["mobile"], color_scheme=theme, timezone_id="Asia/Yekaterinburg",
                                                  device_scale_factor=2 if d["mobile"] else 1)
                        ctx.add_init_script("try { localStorage.setItem('homecal.prefs', JSON.stringify({ onboarded: true, newsSeen: 999 })) } catch (e) {}")
                        # Внешний мир (погода и т.п.) не нужен и в песочнице недоступен — отрезаем, чтобы не шуметь в ошибках.
                        ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())
                        page = ctx.new_page()
                        errors: list[str] = []
                        page.on("console", lambda m: m.type == "error" and "net::ERR_FAILED" not in m.text and errors.append(m.text[:300]))
                        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
                        for view in a.views.split(","):
                            errors.clear()
                            page.goto(f"{url}/?view={view}&nointro")
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(700)
                            name = f"{dev}-{theme}-{view}.png"
                            page.screenshot(path=str(out / name), full_page=dev == "desktop")
                            index.append(name + ("  ОШИБКИ: " + " | ".join(errors) if errors else ""))
                        if a.ask:
                            page.goto(f"{url}/?view=today&nointro")
                            page.wait_for_load_state("networkidle")
                            page.click("button.add-btn")
                            page.wait_for_timeout(500)
                            page.screenshot(path=str(out / f"{dev}-{theme}-plus.png"))
                            index.append(f"{dev}-{theme}-plus.png")
                            page.keyboard.press("Escape")
                            page.goto(f"{url}/?view=agenda&nointro")
                            page.wait_for_load_state("networkidle")
                            pill = page.locator("button.item").first
                            if pill.count():
                                pill.click()
                                page.wait_for_timeout(500)
                                page.screenshot(path=str(out / f"{dev}-{theme}-card.png"))
                                index.append(f"{dev}-{theme}-card.png")
                        ctx.close()
                browser.close()
        finally:
            proc.terminate()
            proc.wait(10)
    (out / "index.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{len(index)} снимков в {out}")
    for line in index:
        if "ОШИБКИ" in line:
            print(line)


if __name__ == "__main__":
    main()
