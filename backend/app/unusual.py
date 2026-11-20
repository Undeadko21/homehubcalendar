"""«Необычная неделя» (v0.21): чем эта неделя отличается от обычной — по сериям за прошлые 4 недели.

- серия не состоится в свой обычный день: «Ср: нет «Бассейн»» (вся неделя — одной строкой «… на этой неделе нет»);
- вхождение серии сдвинуто на 30+ минут: «Пт: «Бассейн» в 18:30, обычно в 17:00»;
- ребёнок не идёт (болеет/уехал): «Чт: Марк не идёт на «Бассейн» — болеет»;
- разовое событие ребёнка поздно (конец после 21:00) или рано (начало до 7:00).

Обычный день серии — день недели, в который она шла хотя бы в 3 из 4 прошлых недель; обычное время — самое частое.
Серия считается живой, если у неё есть вхождения после этой недели (иначе закончилась — не «пропуск»).
Личные события («Занят»), дежурства, дни рождения не учитываются. Только чтение ленты — ничего не пишет.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, time

WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WD_FULL = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]
LATE, EARLY = time(21, 0), time(7, 0)
SHIFT_MIN = 30


def _dt(s: str, tz) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=tz)


def week(events, monday: date, tz, people: list[dict]) -> list[dict]:
    """events — EventService; monday — понедельник недели. Возвращает [{kind, date, text, uid, people}] по дням."""
    start = datetime.combine(monday, time(0), tz)
    evs = events.events(start - timedelta(weeks=4), start + timedelta(weeks=4))
    kids = {p["id"] for p in people if p.get("needs_escort")}
    names = {p["id"]: p["name"] for p in people}
    cur_end = start + timedelta(weeks=1)

    series: dict[str, list[dict]] = defaultdict(list)
    singles: list[dict] = []   # разовые этой недели — среди них «только это» перенесённые занятия серий
    out: list[dict] = []
    for e in evs:
        if e.get("private") or e.get("duty") or e.get("birthday") or e.get("holiday"):
            continue
        s = _dt(e["start"], tz)
        if e.get("recurring") and e.get("uid"):
            series[e["uid"]].append({**e, "_s": s})
        elif start <= s < cur_end:
            singles.append({**e, "_s": s})
            if e.get("all_day") or not kids & set(e.get("people") or []):
                continue
            end = _dt(e["end"], tz) if e.get("end") else s
            who = ", ".join(names.get(p, p) for p in e["people"] if p in kids)
            if end - s >= timedelta(hours=20):   # многодневное (лагерь, поездка) — не «поздно»
                continue
            if end.time() > LATE or (end.date() > s.date() and end.time() > time(0)):
                out.append({"kind": "late", "date": s.date().isoformat(), "uid": e.get("uid"), "people": e["people"],
                            "text": f"{WD[s.weekday()]}: поздно — «{e['title']}» до {end:%H:%M} ({who})"})
            elif s.time() < EARLY:
                out.append({"kind": "early", "date": s.date().isoformat(), "uid": e.get("uid"), "people": e["people"],
                            "text": f"{WD[s.weekday()]}: рано — «{e['title']}» в {s:%H:%M} ({who})"})

    for uid, occ in series.items():
        past = [o for o in occ if o["_s"] < start]
        cur = [o for o in occ if start <= o["_s"] < cur_end]
        after = [o for o in occ if o["_s"] >= cur_end]
        if not past or not after:      # новая серия или закончилась — сравнивать не с чем
            continue
        weeks_by_wd: dict[int, set[int]] = defaultdict(set)
        times_by_wd: dict[int, Counter] = defaultdict(Counter)
        for o in past:
            wk = (start - o["_s"]).days // 7
            weeks_by_wd[o["_s"].weekday()].add(wk)
            if not o.get("all_day"):
                times_by_wd[o["_s"].weekday()][o["_s"].strftime("%H:%M")] += 1
        usual = sorted(wd for wd, w in weeks_by_wd.items() if len(w) >= 3)
        if not usual:
            continue
        title = occ[-1]["title"]
        ppl = occ[-1].get("people") or []
        have = {o["_s"].weekday(): o for o in cur}
        missing = [wd for wd in usual if wd not in have]
        # «Только это» перенесено в HomeHub (EXDATE + отдельное событие): разовое с тем же названием на этой неделе
        moved_single = {}
        for wd in list(missing):
            twin = next((x for x in singles if x["title"].strip().lower() == title.strip().lower()
                         and (not ppl or set(ppl) & set(x.get("people") or []))), None)
            if twin:
                missing.remove(wd)
                moved_single[wd] = twin
                singles.remove(twin)
        for wd, x in moved_single.items():
            s2 = x["_s"]
            when = WD[s2.weekday()] + ("" if x.get("all_day") else f" {s2:%H:%M}")
            out.append({"kind": "moved", "date": s2.date().isoformat(), "uid": uid, "people": ppl,
                        "text": f"{WD[wd]}: «{title}» перенесено на {when}" if s2.weekday() != wd else
                                f"{WD[wd]}: «{title}» в {s2:%H:%M}" + (f", обычно в {times_by_wd[wd].most_common(1)[0][0]}"
                                                                      if times_by_wd.get(wd) else "")})
        if missing and len(missing) == len(usual) and len(usual) > 1:
            out.append({"kind": "missing", "date": monday.isoformat(), "uid": uid, "people": ppl,
                        "text": f"«{title}» на этой неделе нет"})
        else:
            for wd in missing:
                out.append({"kind": "missing", "date": (monday + timedelta(days=wd)).isoformat(), "uid": uid, "people": ppl,
                            "text": f"{WD[wd]}: нет «{title}»"})
        for wd, o in have.items():
            if o.get("absent"):
                who_ids = o["absent"].get("people") or []
                who = ", ".join(names.get(p, p) for p in who_ids) or "никто"
                verb = "не идут" if len(who_ids) > 1 else "не идёт"
                note = o["absent"].get("note") or ""
                out.append({"kind": "absent", "date": o["_s"].date().isoformat(), "uid": uid, "people": ppl,
                            "text": f"{WD[wd]}: {who} {verb} на «{title}»" + (f" ({note})" if note and not note.startswith("не ид") else "")})
                continue
            usual_t = times_by_wd[wd].most_common(1)[0][0] if times_by_wd.get(wd) else None
            if usual_t and not o.get("all_day"):
                h, m = map(int, usual_t.split(":"))
                diff = abs((o["_s"].hour * 60 + o["_s"].minute) - (h * 60 + m))
                if diff >= SHIFT_MIN:
                    out.append({"kind": "moved", "date": o["_s"].date().isoformat(), "uid": uid, "people": ppl,
                                "text": f"{WD[wd]}: «{title}» в {o['_s']:%H:%M}, обычно в {usual_t}"})
    out.sort(key=lambda x: (x["date"], x["kind"] != "missing", x["text"]))
    return out


def mondays(events, today: date, horizon_days: int, tz, people: list[dict]) -> dict:
    """Для утренней сводки понедельника: {понедельник: [строки]} для понедельников в пределах горизонта снимка."""
    out = {}
    for d in range(0, horizon_days + 1):
        day = today + timedelta(days=d)
        if day.weekday() == 0:
            try:
                out[day] = [i["text"] for i in week(events, day, tz, people)]
            except Exception:  # noqa: BLE001 — сводка без этой строки лучше, чем без сводки
                out[day] = []
    return out
