"""«Кто отвозит / кто забирает» для событий детей и поиск конфликтов.

Ребёнок — человек с needs_escort=1. У каждого его события со временем есть две роли:
  dropoff — отвезти: окно [начало − before, начало];
  pickup  — забрать: окно [конец, конец + after].
Назначение ищется сначала для конкретного вхождения (occurrence = время начала),
потом для всей серии ('*'). Значение '-' — сопровождение не нужно.

Конфликт: у назначенного взрослого в окне есть другое занятое событие
(со временем, не «свободен») или другая поездка.

Как добирается (role='mode', значения escort | together | home):
  escort   — кто-то отвозит и забирает (роли выше);
  together — едут все вместе, выбирать водителя не нужно;
  home     — событие дома, везти не нужно.
Если не задано вручную, определяется само: «дома» — по словам в названии/месте
или домашнему адресу; «вместе» — если среди участников есть взрослый.
"""
from __future__ import annotations

import re

from datetime import datetime, timedelta

ROLES = ("dropoff", "pickup")
SKIP = "-"
MODES = ("escort", "together", "home")


def _home_match(e: dict, words: list[str], address: str) -> str | None:
    """Почему событие «дома» (или None). Слова ищутся целиком, без учёта регистра."""
    text = f"{e.get('title', '')} {e.get('location', '')}".lower()
    for w in words:
        if w and re.search(rf"(?<!\w){re.escape(w.lower())}(?!\w)", text):
            return f"в названии или месте есть «{w}»"
    if address and address.lower() in (e.get("location") or "").lower():
        return "место совпадает с домашним адресом"
    return None


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def annotate(events: list[dict], people: dict[str, dict], assignments: dict[tuple[str, str, str], str],
             before_min: int = 30, after_min: int = 30,
             home_words: list[str] | None = None, home_address: str = "") -> None:
    """Добавляет каждому событию ребёнка поле escort и уровень проблемы escort_issue."""
    children = {pid for pid, p in people.items() if p.get("needs_escort")}
    adults = [pid for pid, p in people.items() if not p.get("needs_escort") and not p.get("hidden")]
    if not children:
        return

    # Занятость взрослых: события со временем, где они участвуют.
    busy: dict[str, list[tuple[datetime, datetime, dict]]] = {pid: [] for pid in adults}
    for e in events:
        if e["all_day"] or not e.get("busy", True):
            continue
        s, en = _dt(e["start"]), _dt(e["end"])
        for pid in e["people"]:
            if pid in busy:
                busy[pid].append((s, en, e))

    before, after = timedelta(minutes=before_min), timedelta(minutes=after_min)
    duties: list[tuple[str, datetime, datetime, dict, str]] = []  # (person, w0, w1, event, role)

    for e in events:
        kids = [pid for pid in e["people"] if pid in children]
        if not kids or e["all_day"]:
            continue
        s, en = _dt(e["start"]), _dt(e["end"])

        # Как добирается: ручной выбор (на день или на серию) или автоматически.
        m_once = assignments.get((e["uid"], e["start"], "mode"))
        m_series = assignments.get((e["uid"], "*", "mode"))
        manual = m_once if m_once in MODES else (m_series if m_series in MODES else None)
        grown = [pid for pid in e["people"] if pid in people and pid not in children]
        home_reason = _home_match(e, home_words or [], home_address)
        if manual:
            mode, reason = manual, None
        elif home_reason:
            mode, reason = "home", home_reason
        elif grown:
            names = ", ".join(people[g].get("name", g) for g in grown)
            mode, reason = "together", f"в событии участвует {names}"
        else:
            mode, reason = "escort", None

        info: dict = {
            "children": kids,
            "mode": mode,
            "mode_auto": manual is None,
            "mode_reason": reason,
            "mode_scope": "once" if m_once in MODES else ("series" if m_series in MODES else None),
        }
        for role in ROLES:
            w0, w1 = (s - before, s) if role == "dropoff" else (en, en + after)
            once = assignments.get((e["uid"], e["start"], role))
            series = assignments.get((e["uid"], "*", role))
            value = once if once is not None else series
            person = value if value and value != SKIP and value in people else None
            skip = value == SKIP or mode != "escort"
            if mode != "escort":
                person = None
            info[role] = {
                "person": person,
                "skip": skip,
                "scope": "once" if once is not None else ("series" if series is not None else None),
                "series_person": series if series and series != SKIP else None,
                "window": [w0.isoformat(), w1.isoformat()],
                "conflicts": [],
                "free": [],
            }
            # Кто свободен в это окно (подсказка при выборе).
            for pid in adults:
                if not any(_overlaps(w0, w1, b0, b1) and ev["id"] != e["id"] for b0, b1, ev in busy[pid]):
                    info[role]["free"].append(pid)
            if person:
                duties.append((person, w0, w1, e, role))
        e["escort"] = info

    # Конфликты с занятостью и с другими поездками.
    for person, w0, w1, e, role in duties:
        conflicts = e["escort"][role]["conflicts"]
        for b0, b1, ev in busy.get(person, []):
            if ev["id"] != e["id"] and _overlaps(w0, w1, b0, b1):
                conflicts.append({"title": ev["title"], "start": ev["start"], "end": ev["end"], "kind": "event"})
        for p2, v0, v1, e2, role2 in duties:
            if p2 == person and (e2["id"], role2) != (e["id"], role) and _overlaps(w0, w1, v0, v1):
                verb = "отвезти" if role2 == "dropoff" else "забрать"
                conflicts.append({"title": f"{verb}: {e2['title']}", "start": v0.isoformat(), "end": v1.isoformat(),
                                  "kind": "escort"})
    # Взрослый, у которого уже есть поездка в это время, — не «свободен» для другой.
    for person, w0, w1, e, role in duties:
        for e2 in events:
            esc = e2.get("escort")
            if not esc:
                continue
            for r in ROLES:
                if person in esc[r]["free"] and (e2["id"], r) != (e["id"], role):
                    a0, a1 = (_dt(x) for x in esc[r]["window"])
                    if _overlaps(w0, w1, a0, a1):
                        esc[r]["free"].remove(person)

    for e in events:
        esc = e.get("escort")
        if not esc:
            continue
        roles = [esc[r] for r in ROLES if not esc[r]["skip"]]
        if any(r["conflicts"] for r in roles):
            e["escort_issue"] = "conflict"
        elif any(not r["person"] for r in roles):
            e["escort_issue"] = "unassigned"
        else:
            e["escort_issue"] = None


def duty_intervals(events: list[dict]) -> list[tuple[str, datetime, datetime, dict, str]]:
    """Все назначенные поездки: (взрослый, начало окна, конец окна, событие, роль)."""
    out = []
    for e in events:
        esc = e.get("escort")
        if not esc:
            continue
        for role in ROLES:
            r = esc[role]
            if r["person"] and not r["skip"]:
                w0, w1 = (_dt(x) for x in r["window"])
                out.append((r["person"], w0, w1, e, role))
    return out
