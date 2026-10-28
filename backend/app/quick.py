"""Быстрое создание события обычной фразой: «Йога завтра в 18:30 у Оли», «врач 15 ноября в 10».

Разбор намеренно простой и прозрачный: найденные части вырезаются из фразы, остаток — название.
Результат показывается в форме для проверки, сразу ничего не создаётся.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

WEEKDAYS = {"понедельник": 0, "пн": 0, "вторник": 1, "вт": 1, "среду": 2, "среда": 2, "ср": 2, "четверг": 3, "чт": 3,
            "пятницу": 4, "пятница": 4, "пт": 4, "субботу": 5, "суббота": 5, "сб": 5, "воскресенье": 6, "вс": 6}
WD_PL = {"понедельникам": 0, "вторникам": 1, "средам": 2, "четвергам": 3, "пятницам": 4, "субботам": 5, "воскресеньям": 6}
MONTHS = {"января": 1, "янв": 1, "февраля": 2, "фев": 2, "марта": 3, "мар": 3, "апреля": 4, "апр": 4, "мая": 5,
          "июня": 6, "июн": 6, "июля": 7, "июл": 7, "августа": 8, "авг": 8, "сентября": 9, "сен": 9, "сент": 9,
          "октября": 10, "окт": 10, "ноября": 11, "ноя": 11, "нояб": 11, "декабря": 12, "дек": 12}
REPEATS = [(r"каждый\s+день|ежедневно", "daily"), (r"каждую\s+неделю|еженедельно", "weekly"),
           (r"каждый\s+месяц|ежемесячно", "monthly"), (r"каждый\s+год|ежегодно", "yearly")]


def _cut(text: str, m: re.Match) -> str:
    return (text[:m.start()] + " " + text[m.end():])


def parse(text: str, now: datetime, people: list[dict]) -> dict:
    t = " " + text.strip() + " "
    low = t.lower()
    today = now.date()
    out: dict = {"date": None, "start": None, "end": None, "all_day": False, "repeat": None, "people": [], "notes": []}

    def take(pattern: str):
        nonlocal t, low
        m = re.search(pattern, low)
        if m:
            t = _cut(t, m)
            low = _cut(low, m)
        return m

    # повтор
    for pat, freq in REPEATS:
        if take(rf"(?<!\w)(?:{pat})(?!\w)"):
            out["repeat"] = {"freq": freq}
    m = take(r"(?<!\w)по\s+(" + "|".join(WD_PL) + r")(?!\w)")
    if m:
        out["repeat"] = {"freq": "weekly"}
        out["date"] = _next_weekday(today, WD_PL[m.group(1)], now)

    # время: интервал, затем одиночное
    m = take(r"(?<![\d.])(?:с\s+)?(\d{1,2})[:.](\d{2})\s*(?:-|–|до)\s*(\d{1,2})[:.](\d{2})(?!\d)")
    if m:
        out["start"], out["end"] = f"{int(m[1]):02d}:{m[2]}", f"{int(m[3]):02d}:{m[4]}"
    else:
        m = take(r"(?<![\w.])(?:в|к|с)\s+(\d{1,2})[:.](\d{2})(?!\d)") or take(r"(?<![\d.])(\d{1,2}):(\d{2})(?!\d)")
        if m:
            out["start"] = f"{int(m[1]):02d}:{m[2]}"
        else:
            m = take(r"(?<!\w)(?:в|к)\s+(\d{1,2})\s*(утра|дня|вечера|ночи)?(?!\d|\s*(?:" + "|".join(MONTHS) + "))")
            if m and int(m[1]) <= 23:
                h = int(m[1])
                if m[2] in ("дня", "вечера") and h < 12:
                    h += 12
                out["start"] = f"{h:02d}:00"
            elif m:
                t, low = t, low
    # длительность
    m = take(r"на\s+(полтора|\d+(?:[.,]\d+)?)\s*(час\w*|ч|минут\w*|мин)(?!\w)")
    dur = None
    if m:
        n = 1.5 if m[1] == "полтора" else float(m[1].replace(",", "."))
        dur = int(n * 60) if m[2].startswith(("час", "ч")) else int(n)

    # дата
    if not out["date"]:
        if take(r"(?<!\w)послезавтра(?!\w)"):
            out["date"] = today + timedelta(days=2)
        elif take(r"(?<!\w)завтра(?!\w)"):
            out["date"] = today + timedelta(days=1)
        elif take(r"(?<!\w)сегодня(?!\w)"):
            out["date"] = today
        elif (m := take(r"(?<!\w)через\s+(\d+)\s*(дн\w*|день|недел\w*)")):
            out["date"] = today + timedelta(days=int(m[1]) * (7 if m[2].startswith("недел") else 1))
        elif (m := take(r"(?<!\w)через\s+неделю(?!\w)")):
            out["date"] = today + timedelta(days=7)
        elif (m := take(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\d)")):
            out["date"] = _mk(today, int(m[2]), int(m[1]), m[3])
        elif (m := take(r"(?<!\d)(\d{1,2})\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\w*")):
            out["date"] = _mk(today, MONTHS[m[2]], int(m[1]), None)
        elif (m := take(r"(?<!\w)(?:в|во)?\s*(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")(?!\w)")):
            out["date"] = _next_weekday(today, WEEKDAYS[m[1]], now)
    # люди
    words = re.findall(r"[а-яёa-z0-9-]+", low)
    for p in people:
        name = (p["name"] or "").lower().strip()
        if not name:
            continue
        stem = name[:max(2, len(name) - 1)]
        kws = [k.strip().lower() for k in (p.get("keywords") or "").split(",") if k.strip()]
        hit = [w for w in words if (w.startswith(stem) and len(w) <= len(name) + 2) or w in kws]
        if hit:
            out["people"].append(p["id"])
            for w in [h for h in hit if h not in kws][:1]:   # слова автопривязки остаются в названии: «Футбол»
                if True:
                    t2 = re.sub(rf"(?<![\w]){re.escape(w)}(?![\w])", " ", t, count=1, flags=re.I)
                    t = t2
                    low = t.lower()

    title = re.sub(r"\s+", " ", t).strip(" ,.;-")
    title = re.sub(r"^(?:(?:у|для|с|со|в|на|к)\s+)+|(?:\s+(?:у|для|с|со|в|на|к))+$", "", title, flags=re.I).strip()
    out["title"] = title[:1].upper() + title[1:] if title else ""

    if out["date"] is None:
        out["date"] = today
        out["notes"].append("дата не указана — взято сегодня")
    if out["start"] is None:
        out["all_day"] = True
    elif out["end"] is None:
        h, mi = map(int, out["start"].split(":"))
        e = datetime.combine(out["date"], datetime.min.time()).replace(hour=h, minute=mi) + timedelta(minutes=dur or 60)
        out["end"] = e.strftime("%H:%M") if e.date() == out["date"] else "23:59"
    out["date"] = out["date"].isoformat()
    return out


def _mk(today: date, month: int, day: int, year: str | None) -> date | None:
    try:
        if year:
            y = int(year) + (2000 if len(year) == 2 else 0)
            return date(y, month, day)
        d = date(today.year, month, day)
        return d if d >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


def _next_weekday(today: date, wd: int, now: datetime) -> date:
    delta = (wd - today.weekday()) % 7
    return today + timedelta(days=delta or 7) if delta == 0 else today + timedelta(days=delta)
