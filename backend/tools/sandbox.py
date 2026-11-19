"""Песочница прода: поднимает копию сервера на копии настоящей базы и прогоняет основные запросы и экраны ДО пуша.

    python backend/tools/sandbox.py /путь/homecal.sqlite3              # готовая база (копия через `sqlite3 homecal.sqlite3 ".backup файл"` — не живой файл)
    python backend/tools/sandbox.py backup.db.gz.enc --key <ключ k>    # зашифрованная копия с Яндекс.Диска (app:/backups)
    python backend/tools/sandbox.py ... --ui                           # ещё открыть экраны в браузере и собрать ошибки консоли
    python backend/tools/sandbox.py ... --keep-data                    # не стирать временную папку (там данные семьи!)
    python /hh/backend/tools/sandbox.py копия --canary                   # проверка дома перед подменой (deploy/update.sh, внутри
                                                                        # нового образа без сети): медленно — предупреждение, не провал

Безопасность: база копируется во временную папку; зашифрованные секреты (токены Диска, пароль CalDAV) из копии УДАЛЯЮТСЯ — сервер без них
не может ни синхронизироваться, ни писать в Диск; планировщик выключен; весь исходящий трафик заведён в никуда (прокси-заглушка).
В отчёт идут только коды ответов, время и размеры, число событий — содержимое календаря не печатается. По окончании папка стирается.
Расшифровать копию может только тот, у кого есть ключ (поле `k` кода подключения) — в репозитории его нет.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# В образе (проверка перед подменой, deploy/update.sh) код сервера лежит в /app, собранный интерфейс — в /app/static.
APP_DIR = Path(os.environ.get("HH_SANDBOX_APP_DIR") or ROOT / "backend")
STATIC_DIR = os.environ.get("HOMECAL_STATIC") or str(ROOT / "frontend" / "dist")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from shots import _port, _wait  # noqa: E402

SLOW_MS = 1500


def prepare(src: Path, key: str | None, data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    dst = data / "homecal.sqlite3"
    if key:
        from app.backup import unseal
        raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
        dst.write_bytes(unseal(raw, src.read_bytes()))
    else:
        # через backup API: берёт и содержимое журнала WAL, если рядом лежит работающая база
        a, b = sqlite3.connect(f"file:{src}?mode=ro", uri=True), sqlite3.connect(dst)
        with b:
            a.backup(b)
        a.close()
        b.close()
    con = sqlite3.connect(dst)
    try:
        # секреты (enc1:…) зашифрованы ключом настоящего сервера — здесь их не открыть, и они не нужны; убираем, чтобы ничего не ходило наружу
        n = con.execute("""DELETE FROM kv WHERE value LIKE '"enc1:%'""").rowcount
        con.commit()
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if ok != "ok":
        raise SystemExit(f"копия базы повреждена: {ok}")
    print(f"копия базы готова (секретов убрано: {n})")
    return dst


def start(tmp: Path) -> tuple[subprocess.Popen, str]:
    (tmp / "config.yaml").write_text("timezone: Asia/Yekaterinburg\nsources: []\n", encoding="utf-8")
    port = _port()
    env = {**os.environ, "HOMECAL_CONFIG": str(tmp / "config.yaml"), "HOMECAL_DATA_DIR": str(tmp / "data"),
           "HOMECAL_STATIC": STATIC_DIR, "HOMECAL_NO_SCHEDULER": "1", "HOMECAL_PIN": "",
           # исходящее — в никуда: ни Яндекс, ни погода, ни карты, ни ntfy
           "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9",
           "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=APP_DIR, env=env,
                            stdout=subprocess.DEVNULL, stderr=(tmp / "server.err").open("w"))
    url = f"http://127.0.0.1:{port}"
    _wait(url + "/api/health", 180)
    return proc, url


def checks() -> list[tuple[str, str]]:
    t = date.today()
    mon = t - timedelta(days=t.weekday())
    d = lambda x: x.isoformat()  # noqa: E731
    rng = lambda a, b: f"start={d(a)}T00:00:00&end={d(b)}T00:00:00"  # noqa: E731
    return [
        ("config", "/api/config"), ("status", "/api/status"), ("system", "/api/system"),
        ("events день", "/api/events?" + rng(t, t + timedelta(days=1))),
        ("events неделя", "/api/events?" + rng(mon, mon + timedelta(days=7))),
        ("events месяц", "/api/events?" + rng(t.replace(day=1), t.replace(day=1) + timedelta(days=42))),
        ("events год назад-вперёд", "/api/events?" + rng(t - timedelta(days=180), t + timedelta(days=180))),
        ("holidays", f"/api/holidays?start={d(mon)}&end={d(mon + timedelta(days=42))}"),
        ("lists", "/api/lists"), ("birthdays", "/api/birthdays"), ("countdowns", "/api/countdowns"),
        ("stats", "/api/stats?" + rng(t.replace(day=1), t.replace(day=1) + timedelta(days=31))),
        ("search", "/api/search?q=%D0%B0"), ("recent-events", "/api/recent-events"), ("devices", "/api/devices"),
        ("widget", "/api/widget"), ("snapshot", "/api/snapshot"),
    ]


def get(url: str):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            body = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    except Exception as e:  # noqa: BLE001
        return 0, int((time.time() - t0) * 1000), 0, None, type(e).__name__
    ms = int((time.time() - t0) * 1000)
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    return code, ms, len(body), data, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--key", default=os.environ.get("HH_SANDBOX_KEY"), help="ключ k (лучше через переменную HH_SANDBOX_KEY — аргументы видны в ps)")
    ap.add_argument("--ui", action="store_true")
    ap.add_argument("--keep-data", action="store_true")
    ap.add_argument("--canary", action="store_true", help="проверка перед подменой версии дома: провал — только ошибки и падение")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="hh-sandbox-"))
    proc = None
    bad = 0
    try:
        prepare(Path(a.src), a.key, tmp / "data")
        proc, url = start(tmp)
        get(url + "/api/events?start=2000-01-01T00:00:00&end=2000-01-02T00:00:00")   # прогрев кэша, чтобы холодный старт не дал «медленно»
        time.sleep(1.5)
        for name, path in checks():
            code, ms, size, data, err = get(url + path)
            n = len(data) if isinstance(data, list) else (len(data["events"]) if isinstance(data, dict) and isinstance(data.get("events"), list) else "")
            flag = ""
            if code != 200:
                flag, bad = f"  ← ОШИБКА {code} {err}", bad + 1
            elif ms > SLOW_MS:   # дома на настоящем железе «медленно» бывает и без вины версии — там только предупреждаем
                flag, bad = "  ← МЕДЛЕННО", bad + (0 if a.canary else 1)
            print(f"{name:26} {code}  {ms:5d} мс  {size:8d} Б  {('n=' + str(n)) if n != '' else ''}{flag}")
        if a.ui:
            out = tmp / "shots"
            r = subprocess.run([sys.executable, str(ROOT / "backend/tools/shots.py"), "--url", url, "--out", str(out), "--devices", "phone,desktop", "--themes", "light"],
                               capture_output=True, text=True)
            lines = [l for l in r.stdout.splitlines() if "ОШИБКИ" in l]
            print("экраны:", r.stdout.splitlines()[0] if r.stdout else r.stderr[-300:])
            for l in lines:   # тексты ошибок консоли могут содержать названия событий — в отчёт только имя снимка и число ошибок
                print("  ", l.split("  ОШИБКИ")[0], "— ошибок:", l.count(" | ") + 1)
            bad += len(lines) + (r.returncode != 0)
        if proc.poll() is not None:
            print("сервер упал (последние строки журнала могут содержать данные — смотрите только в --keep-data):", proc.returncode)
            bad += 1
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if a.keep_data:
            print("данные оставлены в", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("OK: песочница чистая" if not bad else f"ПРОБЛЕМ: {bad}")
    if not bad and not a.canary:
        mark_ok()
    return 1 if bad else 0


RISKY = ["db", "events", "expand", "snapshot", "writer", "writeq", "ops", "sync", "cloud", "backup", "core", "main"]


def mark_ok() -> None:
    """Отметка для deploy/check.sh: песочница пройдена на ЭТИХ правках рискованных файлов (хеш их диффа с origin/main)."""
    try:
        git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, check=True).stdout  # noqa: E731
        try:
            base = git("merge-base", "HEAD", "origin/main").strip()
        except subprocess.CalledProcessError:
            base = "HEAD"
        files = [l for l in set(git("diff", "--name-only", base).split() + git("ls-files", "--others", "--exclude-standard").split())
                 if l.startswith("backend/app/sources/") or l in {f"backend/app/{n}.py" for n in RISKY}]
        if not files:
            return
        import hashlib
        files = sorted(files)
        diff = subprocess.run(["git", "-C", str(ROOT), "diff", base, "--", *files], capture_output=True).stdout
        new = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard", "--", *files],
                             capture_output=True, text=True).stdout.split()
        for f in sorted(new):   # содержимое новых файлов — как в deploy/check.sh
            diff += (ROOT / f).read_bytes()
        mark = Path(git("rev-parse", "--git-path", "hh-sandbox-ok").strip())   # в worktree .git — файл, не каталог
        (mark if mark.is_absolute() else ROOT / mark).write_text(hashlib.sha256(diff).hexdigest()[:16])
        print("отметка для deploy/check.sh записана")
    except Exception as e:  # noqa: BLE001
        print("отметку записать не вышло:", e)


if __name__ == "__main__":
    sys.exit(main())
