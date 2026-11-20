#!/usr/bin/env python3
"""Что изменилось на экранах: снимки этой рабочей копии против эталона — того же экрана из main (то, что сейчас на проде).

Эталон снимается тут же, в тот же день, на тех же демо-данных и с остановленными часами браузера, поэтому разница —
это только то, что поменяла правка (а не смена даты). Ничего не правит и не коммитит.

    python backend/tools/visual_diff.py                       # основные экраны и сцены, телефон и компьютер, светлая тема
    python backend/tools/visual_diff.py --views week,today --scenes card-open --devices narrow --themes dark
    python backend/tools/visual_diff.py --base origin/main~3  # эталон — другая версия

Итог: /tmp/visual/index.txt — список «экран — % изменённых точек», и для каждого изменившегося
/tmp/visual/diff/<имя>.png: слева эталон, справа сейчас, посередине — что изменилось (красным).
Код выхода всегда 0 (изменения вида — обычно цель правки); ошибки консоли и «шире экрана» — видно в index.txt.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VIEWS = "today,week,month,family,agenda,lists,settings"
DEFAULT_SCENES = "plus,card-open,settings:reminders"


def run(*a, cwd=None, quiet=True):
    return subprocess.run(list(a), cwd=cwd, check=True, capture_output=quiet, text=True)


def base_tree(ref: str, tmp: Path) -> Path:
    """Рабочая копия эталона (git worktree) с собранным интерфейсом. node_modules — общие, если package-lock тот же."""
    wt = tmp / "base"
    run("git", "-C", str(ROOT), "worktree", "add", "--detach", str(wt), ref)
    same_lock = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", ref, "--", "frontend/package-lock.json"]).returncode == 0
    if same_lock and (ROOT / "frontend/node_modules").exists():
        (wt / "frontend/node_modules").symlink_to(ROOT / "frontend/node_modules")
    else:
        run("npm", "ci", "--silent", cwd=wt / "frontend")
    run("npm", "run", "build", "--silent", cwd=wt / "frontend")
    return wt


def shoot(tree: Path, out: Path, a) -> None:
    # Оба дерева снимает ТЕКУЩИЙ shots.py (--root): сцены и настройки одинаковые, даже если в эталоне инструмент старее.
    args = [sys.executable, str(ROOT / "backend/tools/shots.py"), "--root", str(tree), "--out", str(out),
            "--views", a.views or "none", "--devices", a.devices, "--themes", a.themes, "--freeze", a.freeze]
    if a.scenes:
        args += ["--scenes", a.scenes]
    subprocess.run(args, check=True, cwd=ROOT)


def compare(base: Path, cur: Path, out: Path) -> list[str]:
    from PIL import Image, ImageChops
    (out / "diff").mkdir(parents=True, exist_ok=True)
    lines = []
    names = sorted({p.name for p in base.glob("*.png")} | {p.name for p in cur.glob("*.png")})
    for n in names:
        b, c = base / n, cur / n
        if not b.exists() or not c.exists():
            lines.append(f"{n:48s} {'новый экран' if c.exists() else 'экрана больше нет'}")
            if c.exists():
                shutil.copy(c, out / "diff" / n)
            continue
        ib, ic = Image.open(b).convert("RGB"), Image.open(c).convert("RGB")
        w, h = max(ib.width, ic.width), max(ib.height, ic.height)
        pb, pc = Image.new("RGB", (w, h), "white"), Image.new("RGB", (w, h), "white")
        pb.paste(ib), pc.paste(ic)
        mask = ImageChops.difference(pb, pc).convert("L").point(lambda v: 255 if v > 24 else 0)
        changed = mask.histogram()[255] / (w * h) * 100
        size = "" if ib.size == ic.size else f"  размер {ib.width}×{ib.height} → {ic.width}×{ic.height}"
        lines.append(f"{n:48s} {changed:5.1f}%{size}")
        if changed >= 0.05 or size:
            red = Image.new("RGB", (w, h), (255, 40, 40))
            mid = Image.composite(red, pc.point(lambda v: 150 + v // 3), mask)   # бледный «сейчас», изменения — красным
            sheet = Image.new("RGB", (w * 3 + 20, h), "white")
            sheet.paste(pb, (0, 0)), sheet.paste(mid, (w + 10, 0)), sheet.paste(pc, (2 * w + 20, 0))
            sheet.save(out / "diff" / n)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--views", default=DEFAULT_VIEWS)
    ap.add_argument("--scenes", default=DEFAULT_SCENES)
    ap.add_argument("--devices", default="phone,desktop")
    ap.add_argument("--themes", default="light")
    ap.add_argument("--freeze", default="10:00")
    ap.add_argument("--out", default="/tmp/visual")
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="hh-visual-"))
    try:
        print(f"эталон: {a.base} …")
        wt = base_tree(a.base, tmp)
        shoot(wt, out / "base", a)
        print("сейчас: рабочая копия …")
        run("npm", "run", "build", "--silent", cwd=ROOT / "frontend")
        shoot(ROOT, out / "now", a)
        lines = compare(out / "base", out / "now", out)
        changed = [l for l in lines if not l.rstrip().endswith(" 0.0%")]
        idx = ["# экран — доля изменённых точек (эталон " + a.base + ")"] + lines
        errs = (out / "now/index.txt").read_text(encoding="utf-8") if (out / "now/index.txt").exists() else ""
        idx += ["", "# ошибки и «шире экрана» (сейчас):"] + [l for l in errs.splitlines() if "ОШИБКИ" in l or "ШИРЕ" in l]
        (out / "index.txt").write_text("\n".join(idx) + "\n", encoding="utf-8")
        print("\n".join(changed) or "изменений вида нет")
        print(f"итог: {out}/index.txt, картинки различий: {out}/diff/")
    finally:
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tmp / "base")], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
