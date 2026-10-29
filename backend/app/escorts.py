"""«Кто отвозит / кто забирает» для событий детей и поиск конфликтов.

Ребёнок — человек с needs_escort=1. У каждого его события со временем есть две роли:
  dropoff — отвезти: окно [начало − before, начало];
  pickup  — забрать: окно [конец, конец + after].
Назначение ищется сначала для конкретного вхождения (occurrence = время начала),
потом для всей серии ('*'). Значение '-' — сопровождение не нужно.

Конфликт: у назначенного взрослого в окне есть другое занятое событие
(со временем, не «свободен») или другая поездка.

Время в дороге: если у события (или места по правилам из настроек) задано «минут в пути»,
окно «отвезти» = [начало − дорога − запас, начало], «забрать» = [конец, конец + дорога + запас];
иначе используются фиксированные before/after. Дорога события хранится как role='travel'
(значение — число минут), правила по местам — settings:escort.places.

Шаблоны: «по вторникам кружок — везёт Толя, забирает Оля» (escort_templates) — значение
по умолчанию, когда для события ничего не назначено вручную; разовые замены и серия важнее.

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


def _words(text: str) -> list[str]:
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()]


def _template_value(templates: list[dict], kids: list[str], e: dict, weekday: int, role: str) -> str | None:
    """Назначение из шаблона; конкретные шаблоны (со словами) важнее общих."""
    title = e.get("title", "").lower()
    best: tuple[int, str] | None = None
    for t in templates:
        if t["child_id"] not in kids or t["weekday"] != weekday or not t.get(role):
            continue
        words = _words(t.get("match", ""))
        if words and not any(w in title for w in words):
            continue
        rank = 1 if words else 0
        if best is None or rank > best[0]:
            best = (rank, t[role])
    return best[1] if best else None


def _place_minutes(e: dict, places: list[dict]) -> int | None:
    text = f"{e.get('title', '')} {e.get('location', '')}".lower()
    for p in places:
        if any(w in text for w in _words(p.get("words", ""))):
            try:
                return max(0, int(p.get("minutes")))
            except (TypeError, ValueError):
                continue
    return None


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def annotate(events: list[dict], people: dict[str, dict], assignments: dict[tuple[str, str, str], str],
             before_min: int = 30, after_min: int = 30,
             home_words: list[str] | None = None, home_address: str = "",
             templates: list[dict] | None = None, places: list[dict] | None = None,
             travel_buffer: int = 5) -> None:
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
        # Время в пути: на этот день → на серию → правило по месту.
        t_once = assignments.get((e["uid"], e["start"], "travel"))
        t_series = assignments.get((e["uid"], "*", "travel"))
        travel, t_source = None, None
        for raw, src in ((t_once, "once"), (t_series, "series")):
            if raw is not None and str(raw).isdigit():
                travel, t_source = int(raw), src
                break
        if travel is None:
            pm = _place_minutes(e, places or [])
            if pm is not None:
                travel, t_source = pm, "place"
        info["travel"] = {"minutes": travel, "source": t_source,
                          "buffer": travel_buffer if travel is not None else None}
        lead = timedelta(minutes=travel + travel_buffer) if travel is not None else None

        for role in ROLES:
            if lead is not None:
                w0, w1 = (s - lead, s) if role == "dropoff" else (en, en + lead)
            else:
                w0, w1 = (s - before, s) if role == "dropoff" else (en, en + after)
            once = assignments.get((e["uid"], e["start"], role))
            series = assignments.get((e["uid"], "*", role))
            value = once if once is not None else series
            from_template = None
            if value is None:
                from_template = _template_value(templates or [], kids, e, s.weekday(), role)
                value = from_template
            person = value if value and value != SKIP and value in people else None
            skip = value == SKIP or mode != "escort"
            if mode != "escort":
                person = None
            info[role] = {
                "person": person,
                "skip": skip,
                "scope": "once" if once is not None else ("series" if series is not None
                                                          else ("template" if from_template else None)),
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


def accusative(name: str) -> str:
    """Имя в винительном падеже для «Отвезти Марка / Машу / Олю». Простые правила, без словаря."""
    if not name or not name[-1].isalpha() or not any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in name):
        return name
    last = name[-1].lower()
    if last == "а":
        return name[:-1] + ("у" if name[-1] == "а" else "У")
    if last == "я":
        return name[:-1] + ("ю" if name[-1] == "я" else "Ю")
    if last in "йь":
        return name[:-1] + "я"
    if last in "бвгджзклмнпрстфхцчшщ":
        return name + "а"
    return name


def add_to_adults(events: list[dict], people: dict[str, dict]) -> list[dict]:
    """Показывает поездки и «все вместе» в календарях взрослых.

    - Для каждого назначенного «отвезти/забрать» добавляет взрослому событие-поездку
      (поле duty, ссылка на исходное событие в duty.parent).
    - Событие в режиме «все вместе» без взрослых участников показывается у всех взрослых.
    Возвращает новые события-поездки (исходный список дополняется участниками на месте).
    """
    adults = [pid for pid, p in people.items() if not p.get("needs_escort") and not p.get("hidden")]
    duties: list[dict] = []
    for e in events:
        esc = e.get("escort")
        if not esc:
            continue
        kids = " и ".join(accusative(people[k].get("name", k)) for k in esc["children"] if k in people)
        if esc["mode"] == "together":
            if not any(p in adults for p in e["people"]):
                e["people"] = list(dict.fromkeys([*e["people"], *adults]))
            esc["together_people"] = [p for p in e["people"] if p in adults]
            continue
        if esc["mode"] != "escort":
            continue
        parent = {k: v for k, v in e.items()}
        for role in ROLES:
            r = esc[role]
            if r["skip"] or not r["person"] or r["person"] not in adults:
                continue
            verb = "Отвезти" if role == "dropoff" else "Забрать"
            w0, w1 = r["window"]
            duties.append({
                "id": f"{e['id']}:{role}",
                "uid": e["uid"],
                "title": f"{verb} {kids}: {e['title']}",
                "start": w0,
                "end": w1,
                "all_day": False,
                "location": e.get("location", ""),
                "description": "",
                "url": "",
                "private": False,
                "busy": True,
                "tentative": False,
                "recurring": e.get("recurring", False),
                "attendees": [],
                "people": [r["person"]],
                "people_override": False,
                "calendars": e.get("calendars", []),
                "duty": {"role": role, "parent": parent},
                "escort_issue": "conflict" if r["conflicts"] else None,
            })
    return duties


def suggest_templates(events: list[dict], templates: list[dict], min_count: int = 3) -> list[dict]:
    """Подсказки «сделать правилом»: один и тот же человек, назначенный вручную на похожие события
    ребёнка в один день недели не меньше min_count раз, а шаблона для этого ещё нет.
    Назначение «на всю серию» считается один раз (это уже правило для события, а не повтор вручную)."""
    groups: dict[tuple, dict[str, dict[tuple, str]]] = {}
    for e in events:
        esc = e.get("escort")
        if not esc or e.get("all_day") or e.get("duty") or esc.get("mode") != "escort":
            continue
        try:
            weekday = datetime.fromisoformat(e["start"]).weekday()
        except (ValueError, KeyError):
            continue
        title = " ".join(re.sub(r"[^\w\s]", " ", e.get("title", "").lower()).split())
        if not title:
            continue
        for kid in esc.get("children", []):
            key = (kid, weekday, title)
            for role in ROLES:
                r = esc.get(role) or {}
                if r.get("scope") not in ("once", "series") or not r.get("person"):
                    continue
                unit = ("once", e["start"]) if r["scope"] == "once" else ("series", e["uid"])
                groups.setdefault(key, {}).setdefault(role, {})[unit] = r["person"]
    out = []
    for (kid, weekday, title), roles in groups.items():
        chosen = {}
        for role, units in roles.items():
            counts: dict[str, int] = {}
            for person in units.values():
                counts[person] = counts.get(person, 0) + 1
            person, n = max(counts.items(), key=lambda kv: kv[1])
            if n >= min_count and n >= 0.75 * len(units):
                chosen[role] = (person, n)
        if not chosen:
            continue
        fake = {"title": title}
        # Если шаблон с этим значением уже есть — подсказывать нечего.
        chosen = {r: v for r, v in chosen.items() if _template_value(templates, [kid], fake, weekday, r) != v[0]}
        if not chosen:
            continue
        out.append({"child_id": kid, "weekday": weekday, "match": title,
                    "dropoff": chosen.get("dropoff", ("", 0))[0], "pickup": chosen.get("pickup", ("", 0))[0],
                    "count": max(n for _, n in chosen.values())})
    out.sort(key=lambda x: -x["count"])
    return out[:5]
