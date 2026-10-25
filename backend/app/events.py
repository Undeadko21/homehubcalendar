"""Сборка ленты событий: разворачивание → привязка к людям → склейка дублей."""
from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from .db import Database
from .expand import expand_ics

UNASSIGNED = "_unassigned"


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", t.lower())).strip()


def _event_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


class EventService:
    def __init__(self, db: Database, tz: ZoneInfo, fuzzy_dedup: bool = True):
        self.db = db
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
        result = self._build(start, end)
        with self._lock:
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = result
        return result

    def _build(self, start: datetime, end: datetime) -> list[dict]:
        people = {p["id"]: p for p in self.db.list_people()}
        raw: list[dict] = []
        for cal in self.db.list_calendars():
            if cal["hidden"]:
                continue
            person_id = cal["person_id"] if cal["person_id"] in people else UNASSIGNED
            if person_id != UNASSIGNED and people[person_id]["hidden"]:
                continue
            for ics in self.db.objects_for(cal["key"]):
                for occ in expand_ics(ics, start, end, self.tz):
                    d = occ.to_dict()
                    d["calendar"] = cal["key"]
                    d["person"] = person_id
                    d["cal_private"] = bool(cal["private"])
                    raw.append(d)
        return self._merge(raw)

    def _merge(self, raw: list[dict]) -> list[dict]:
        """Склейка дублей.

        1) Точная: одинаковые UID и время начала (приглашение, которое лежит
           в календарях нескольких людей).
        2) Нечёткая (dedup.fuzzy): одинаковые название, начало и конец в разных
           календарях — когда событие вручную скопировали.
        """
        merged: dict[str, dict] = {}
        for e in raw:
            k = _event_id("uid", e["uid"], e["start"])
            merged.setdefault(k, {**e, "people": [], "calendars": [], "_priv": []})
            m = merged[k]
            m["people"].append(e["person"])
            m["calendars"].append(e["calendar"])
            m["_priv"].append(e["private"] or e["cal_private"])

        if self.fuzzy_dedup:
            by_sig: dict[tuple, str] = {}
            for k in list(merged):
                m = merged[k]
                sig = (_norm_title(m["title"]), m["start"], m["end"])
                if sig in by_sig and not set(merged[by_sig[sig]]["calendars"]) & set(m["calendars"]):
                    target = merged[by_sig[sig]]
                    target["people"] += m["people"]
                    target["calendars"] += m["calendars"]
                    target["_priv"] += m["_priv"]
                    del merged[k]
                else:
                    by_sig.setdefault(sig, k)

        out = []
        for k, m in merged.items():
            # Событие приватно, только если оно приватно во всех копиях.
            private = all(m.pop("_priv"))
            m.pop("cal_private", None)
            m.pop("calendar", None)
            m.pop("person", None)
            m["people"] = list(dict.fromkeys(m["people"]))
            m["calendars"] = list(dict.fromkeys(m["calendars"]))
            m["id"] = k
            m["private"] = private
            if private:
                m.update(title="Занят", location="", description="", url="", attendees=[])
            out.append(m)
        out.sort(key=lambda e: (e["start"][:10], not e["all_day"], e["start"], e["title"]))
        return out
