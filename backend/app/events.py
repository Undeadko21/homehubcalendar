"""Сборка ленты событий: разворачивание → привязка к людям → склейка дублей."""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import escorts
from .db import Database
from .expand import expand_ics

ESCORT_DEFAULTS = {"before_minutes": 30, "after_minutes": 30, "home_words": "дома", "home_address": ""}

UNASSIGNED = "_unassigned"


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", t.lower())).strip()


def _event_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _in_range(e: dict, start: datetime, end: datetime) -> bool:
    if e["all_day"]:
        s = datetime.fromisoformat(e["start"]).replace(tzinfo=start.tzinfo)
        en = datetime.fromisoformat(e["end"]).replace(tzinfo=start.tzinfo)
    else:
        s, en = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
    return s < end and (en > start or (en == s and s >= start))


class EventService:
    def __init__(self, db: Database, tz: ZoneInfo, fuzzy_dedup: bool = True, respect_event_class: bool = False):
        self.db = db
        # Яндекс помечает CLASS:PRIVATE почти все события собственных календарей,
        # поэтому по умолчанию детали скрывает только флаг календаря «только занят».
        self.respect_event_class = respect_event_class
        self.tz = tz
        self.fuzzy_dedup = fuzzy_dedup
        self._cache: dict[tuple, list[dict]] = {}
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def events(self, start: datetime, end: datetime) -> list[dict]:
        key = (start.isoformat(), end.isoformat())
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        # Строим с запасом в сутки: конфликты поездок зависят от соседних событий.
        wide = self._build(start - timedelta(days=1), end + timedelta(days=1))
        people = {p["id"]: p for p in self.db.list_people()}
        cfg = self.escort_settings()
        escorts.annotate(wide, people, self.db.escorts(), cfg["before_minutes"], cfg["after_minutes"],
                         [w.strip() for w in str(cfg.get("home_words") or "").split(",") if w.strip()],
                         str(cfg.get("home_address") or "").strip())
        # Поездки и «все вместе» — в календари взрослых.
        wide += escorts.add_to_adults(wide, people)
        wide.sort(key=lambda e: (e["start"][:10], not e["all_day"], e["start"], e["title"]))
        result = [e for e in wide if _in_range(e, start, end)]
        with self._lock:
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = result
        return result

    def escort_settings(self) -> dict:
        value, _ = self.db.kv_get("settings:escort")
        return {**ESCORT_DEFAULTS, **(value or {})}

    def _build(self, start: datetime, end: datetime) -> list[dict]:
        people = {p["id"]: p for p in self.db.list_people()}
        raw: list[dict] = []
        for cal in self.db.list_calendars():
            if cal["hidden"]:
                continue
            owners = [pid for pid in cal["people"] if pid in people]
            for ics in self.db.objects_for(cal["key"]):
                for occ in expand_ics(ics, start, end, self.tz):
                    d = occ.to_dict()
                    d["calendar"] = cal["key"]
                    d["owners"] = owners
                    d["cal_private"] = bool(cal["private"])
                    raw.append(d)
        return self._merge(raw, people, self.db.event_people())

    def _merge(self, raw: list[dict], people: dict[str, dict] | None = None,
               overrides: dict[str, list[str]] | None = None) -> list[dict]:
        """Склейка дублей и определение, чьё это событие.

        Склейка:
        1) точная — одинаковые UID и время начала (приглашение, которое лежит
           в календарях нескольких людей);
        2) нечёткая (dedup.fuzzy) — одинаковые название, начало и конец в разных
           календарях (событие скопировали вручную).

        Чьё событие (по приоритету):
        1) участники, выбранные вручную в карточке события (по UID, на все повторы);
        2) иначе владельцы всех календарей, где лежит событие,
           плюс люди, чьи слова автопривязки встречаются в названии.
        Скрытые люди убираются; событие без людей попадает в «Без владельца».
        """
        people = people or {}
        overrides = overrides or {}
        keywords = {
            pid: [w.strip().lower() for w in (p.get("keywords") or "").split(",") if w.strip()]
            for pid, p in people.items()
        }

        merged: dict[str, dict] = {}
        for e in raw:
            k = _event_id("uid", e["uid"], e["start"])
            merged.setdefault(k, {**e, "owners": [], "calendars": [], "uids": [], "_priv": []})
            m = merged[k]
            m["owners"] += e["owners"]
            m["calendars"].append(e["calendar"])
            m["uids"].append(e["uid"])
            m["_priv"].append(e["cal_private"] or (self.respect_event_class and e["private"]))

        if self.fuzzy_dedup:
            by_sig: dict[tuple, str] = {}
            for k in list(merged):
                m = merged[k]
                sig = (_norm_title(m["title"]), m["start"], m["end"])
                if sig in by_sig and not set(merged[by_sig[sig]]["calendars"]) & set(m["calendars"]):
                    target = merged[by_sig[sig]]
                    for f in ("owners", "calendars", "uids", "_priv"):
                        target[f] += m[f]
                    del merged[k]
                else:
                    by_sig.setdefault(sig, k)

        out = []
        for k, m in merged.items():
            uids = list(dict.fromkeys(m.pop("uids")))
            override = next((overrides[u] for u in uids if u in overrides), None)
            if override is not None:
                assigned = list(override)
            else:
                title = m["title"].lower()
                auto = [pid for pid, words in keywords.items() if any(w in title for w in words)]
                assigned = list(m["owners"]) + auto
            assigned = [pid for pid in dict.fromkeys(assigned) if pid in people]
            visible = [pid for pid in assigned if not people[pid].get("hidden")]
            if assigned and not visible:
                continue  # событие только скрытых людей
            m["people"] = visible or [UNASSIGNED]
            m["people_override"] = override is not None

            # Событие приватно, только если оно приватно во всех копиях.
            private = all(m.pop("_priv"))
            for f in ("cal_private", "calendar", "owners"):
                m.pop(f, None)
            m["calendars"] = list(dict.fromkeys(m["calendars"]))
            m["id"] = k
            m["private"] = private
            if private:
                m.update(title="Занят", location="", description="", url="", attendees=[])
            out.append(m)
        out.sort(key=lambda e: (e["start"][:10], not e["all_day"], e["start"], e["title"]))
        return out
