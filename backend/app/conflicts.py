"""Предупреждения в момент создания или переноса события: занятость людей и поездки детей.

Событие примеряется к ленте на ±1 день (в самой ленте оно не сохраняется): считаем те же правила, что и в календаре,
и сообщаем только то, что НОВОЕ — конфликты, которых до этого не было.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

from . import escorts
from .events import UNASSIGNED, EventService
from .expand import Occurrence

NEW_UID = "__new__"
VERB = {"dropoff": "отвезти", "pickup": "забрать"}


def _hm(iso: str) -> str:
    return iso[11:16]


def check(svc: EventService, *, calendar: str, title: str, start: datetime, end: datetime | None, all_day: bool,
          people: list[str] | None, uid: str | None = None, location: str = "") -> list[dict]:
    if all_day:
        return []
    end = end or start + timedelta(hours=1)
    if end <= start:
        return []
    pmap = {p["id"]: p for p in svc.db.list_people()}
    name = lambda pid: pmap.get(pid, {}).get("name", pid)  # noqa: E731

    cal = next((c for c in svc.db.list_calendars() if c["key"] == calendar), None)
    raw = Occurrence(uid=NEW_UID, title=title or "Новое событие", start=start.isoformat(), end=end.isoformat(),
                     all_day=False, location=location).to_dict()
    raw.update(calendar=calendar, owners=[p for p in (cal["people"] if cal else []) if p in pmap], cal_private=False)
    overrides = {NEW_UID: list(people)} if people is not None else None
    merged = svc._merge([raw], pmap, overrides)
    if not merged:
        return []
    new = merged[0]
    new["id"] = NEW_UID

    base = [e for e in svc._build(start - timedelta(days=1), end + timedelta(days=1)) if e["uid"] != uid]
    cfg = svc.escort_settings()
    home_words = [w.strip() for w in str(cfg.get("home_words") or "").split(",") if w.strip()]
    kw = dict(before_min=cfg["before_minutes"], after_min=cfg["after_minutes"], home_words=home_words,
              home_address=str(cfg.get("home_address") or "").strip(), templates=svc.db.templates(),
              places=cfg.get("places") or [], travel_buffer=int(cfg.get("travel_buffer") or 0))
    assignments = svc.db.escorts()

    before = copy.deepcopy(base)
    escorts.annotate(before, pmap, assignments, **kw)
    issues_before = {e["id"]: e.get("escort_issue") for e in before}

    after = copy.deepcopy(base) + [new]
    escorts.annotate(after, pmap, assignments, **kw)
    duties = escorts.add_to_adults(after, pmap)

    out: list[dict] = []
    # 1. Занятость участников.
    s_iso, e_iso = start.isoformat(), end.isoformat()
    for pid in new["people"]:
        if pid == UNASSIGNED:
            continue
        for ev in after + duties:
            if ev["id"] == NEW_UID or ev["all_day"] or not ev.get("busy", True) or pid not in ev["people"]:
                continue
            if ev["start"] < e_iso and ev["end"] > s_iso:
                kind = "duty" if ev.get("duty") else "event"
                out.append({"level": "warn", "kind": kind, "person": pid,
                            "text": f"У {_gen(name(pid))} в это время: {ev['title']} ({_hm(ev['start'])}–{_hm(ev['end'])})"})

    # 2. Поездки самого события.
    esc = new.get("escort")
    if esc and esc["mode"] == "escort":
        kid = " и ".join(escorts.accusative(name(k)) for k in esc["children"])
        for role in escorts.ROLES:
            r = esc[role]
            if r["skip"]:
                continue
            verb = VERB[role]
            if r["person"] and r["conflicts"]:
                c = r["conflicts"][0]
                out.append({"level": "warn", "kind": "escort", "person": r["person"],
                            "text": f"{name(r['person'])} не сможет {verb} {kid}: {c['title']}"})
            elif not r["person"]:
                if not r["free"]:
                    out.append({"level": "warn", "kind": "escort",
                                "text": f"Некому {verb} {kid}: все взрослые заняты ({_hm(r['window'][0])}–{_hm(r['window'][1])})"})
                else:
                    who = ", ".join(name(p) for p in r["free"])
                    out.append({"level": "info", "kind": "escort",
                                "text": f"Нужно назначить, кто {_future(verb)} {kid}. Свободны: {who}"})

    # 3. Новое событие сломало поездки других детей.
    for ev in after:
        if ev["id"] == NEW_UID or ev.get("escort_issue") != "conflict" or issues_before.get(ev["id"]) == "conflict":
            continue
        for role in escorts.ROLES:
            r = (ev.get("escort") or {}).get(role)
            if r and r["person"] and r["conflicts"] and not r["skip"]:
                out.append({"level": "warn", "kind": "escort", "person": r["person"],
                            "text": f"Из-за этого {name(r['person'])} не сможет {VERB[role]}: {ev['title']}"})
    return out


def _gen(n: str) -> str:
    """«У Оли», «У Марка»: родительный падеж простыми правилами."""
    if not n or not n[-1].isalpha():
        return n
    last = n[-1].lower()
    if last == "а":
        return n[:-1] + "ы" if n[-2:-1].lower() not in "гкхжчшщ" else n[:-1] + "и"
    if last == "я":
        return n[:-1] + "и"
    if last in "йь":
        return n[:-1] + "я"
    if last in "бвгджзклмнпрстфхцчшщ":
        return n + "а"
    return n


def _future(verb: str) -> str:
    return {"отвезти": "отвезёт", "забрать": "заберёт"}.get(verb, verb)
