"""«Кто что изменил»: журнал изменений событий на ближайшие две недели и уведомления о них.

Изменения находим сравнением ленты до и после пересборки (events._compose на окне, ДО фильтров каникул,
«болеет» и поездок — настройки не считаются изменениями событий): новое, удалённое, перенесённое,
переименованное, другое место. Так видно всё — правки с телефона, с компьютера и прямо в Яндекс-календаре.

Кто правил: «кто я» на устройстве пользователь не хочет, поэтому пишем ОТКУДА — устройство, если только что
была запись через приложение (`note_write`), иначе календарь, в котором событие лежит («в календаре «Работа Толя»»).

Хранится в kv `changes:log` (последние 300, свежие первыми). Массовые перемены (больше 12 за раз — скрыли
календарь, переподключили источник) — одной строкой и без уведомлений.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .db import Database

KEY = "changes:log"
KEEP = 300
MASS = 12
HORIZON_DAYS = 14
WRITE_WINDOW = timedelta(minutes=3)
_lock = threading.Lock()
_last_write: dict = {"at": None, "origin": None}

PLATFORM = {"ios": "с iPhone", "android": "с Android", "mac": "с Mac", "other": "с компьютера"}


def note_write(ua: str, via_cloud: bool = False) -> None:
    """Запись через приложение/сайт: следующие изменения в ближайшие минуты — оттуда."""
    from .sessions import platform
    _last_write.update(at=datetime.now().astimezone(), origin="вне дома (через Диск)" if via_cloud else PLATFORM.get(platform(ua), "с компьютера"))


def _origin(e: dict, names: dict[str, str]) -> str:
    at = _last_write.get("at")
    if at and datetime.now().astimezone() - at < WRITE_WINDOW:
        return _last_write["origin"]
    cal = (e.get("calendars") or [e.get("calendar")])[0] or ""
    return f"в календаре «{names.get(cal, cal.split('/')[-1])}»"


def _key(e: dict) -> tuple:
    return (e["start"], e["end"], e["title"], e.get("location") or "")


def diff(old: list[dict], new: list[dict], now: datetime) -> list[dict]:
    """Изменения событий, которые начинаются в ближайшие две недели (до или после правки)."""
    lo = now.replace(hour=0, minute=0, second=0, microsecond=0)   # с начала сегодня: и «весь день» сегодня
    hi = now + timedelta(days=HORIZON_DAYS)

    def soon(e: dict) -> bool:
        try:
            s = datetime.fromisoformat(e["start"] if len(e["start"]) > 10 else e["start"] + "T00:00:00")
            if s.tzinfo is None:
                s = s.replace(tzinfo=now.tzinfo)
        except ValueError:
            return False
        return lo <= s <= hi

    def by_uid(evs):
        out: dict[str, list[dict]] = {}
        for e in evs:
            if e.get("duty"):
                continue
            out.setdefault(e.get("uid") or e["id"], []).append(e)
        return out

    a, b = by_uid(old), by_uid(new)
    found: list[dict] = []
    for uid in set(a) | set(b):
        olds, news = a.get(uid, []), b.get(uid, [])
        if not any(soon(e) for e in olds + news):
            continue
        if not olds:
            for e in news:
                if soon(e):
                    found.append({"kind": "new", "e": e})
                    break
            continue
        if not news:
            e = next((x for x in olds if soon(x)), olds[0])
            found.append({"kind": "deleted", "e": e})
            continue
        if len(olds) == 1 and len(news) == 1:   # одиночное событие: что поменялось
            o, n = olds[0], news[0]
            if _key(o) != _key(n) and bool(o.get("private")) == bool(n.get("private")):
                found.append({"kind": "changed", "e": n, "old": o})
            continue
        # Серия: вхождения ближайших двух недель. Сначала — совпавшие по началу, затем оставшиеся — по дню
        # (перенос 16:00 → 17:00 — «Изменено», а не «Отменено» + «Новое»), что осталось — по порядку.
        ok = {x["start"]: x for x in olds if soon(x)}
        nk = {x["start"]: x for x in news if soon(x)}
        pairs = [(ok[s], nk[s]) for s in ok.keys() & nk.keys()]
        lo_, ln_ = sorted(ok.keys() - nk.keys()), sorted(nk.keys() - ok.keys())
        by_day = {}
        for s in ln_:
            by_day.setdefault(s[:10], []).append(s)
        rest_o = []
        for s in lo_:
            same = by_day.get(s[:10])
            if same:
                pairs.append((ok[s], nk[same.pop(0)]))
            else:
                rest_o.append(s)
        rest_n = sorted(x for v in by_day.values() for x in v)
        moved = []   # перенос серии на другой день недели: пары по порядку, но одной записью на серию
        while rest_o and rest_n:
            moved.append((ok[rest_o.pop(0)], nk[rest_n.pop(0)]))
        series_changed = [(o, n) for o, n in pairs + moved
                          if _key(o) != _key(n) and bool(o.get("private")) == bool(n.get("private"))]
        if len(series_changed) > 1 and all(_shape(o, n) == _shape(*series_changed[0]) for o, n in series_changed):
            o, n = series_changed[0]
            found.append({"kind": "changed", "e": n, "old": o, "series": len(series_changed)})
        else:
            found += [{"kind": "changed", "e": n, "old": o} for o, n in series_changed]
        found += [{"kind": "deleted", "e": ok[s], "one": True} for s in rest_o]
        found += [{"kind": "new", "e": nk[s], "one": True} for s in rest_n]
    return _cancel_uid_flips(found)


def _cancel_uid_flips(found: list[dict]) -> list[dict]:
    """«Удалено» + «Новое» с теми же временем, названием и местом (другой UID — та же встреча из другого календаря
    или пересоздана при синхронизации) — не изменение для семьи (v0.21: такие пары давали «Много изменений сразу»)."""
    dels: dict[tuple, list[int]] = {}
    for i, c in enumerate(found):
        if c["kind"] == "deleted":
            dels.setdefault(_key(c["e"]), []).append(i)
    drop = set()
    for i, c in enumerate(found):
        if c["kind"] == "new" and dels.get(_key(c["e"])):
            drop.add(dels[_key(c["e"])].pop())
            drop.add(i)
    return [c for i, c in enumerate(found) if i not in drop]


def _shape(o: dict, n: dict) -> tuple:
    """Одинаковая правка у всех вхождений серии: тот же сдвиг времени и те же название/место."""
    def mins(e, k):
        try:
            return datetime.fromisoformat(e[k]).timestamp() // 60
        except (ValueError, KeyError):
            return 0
    return (mins(n, "start") - mins(o, "start"), mins(n, "end") - mins(o, "end"), o["title"], n["title"],
            o.get("location") or "", n.get("location") or "")


def _fmt_when(e: dict, tz: ZoneInfo) -> str:
    if e.get("all_day") or len(e["start"]) <= 10:
        d = datetime.fromisoformat(e["start"][:10])
        return d.strftime("%d.%m")
    s = datetime.fromisoformat(e["start"]).astimezone(tz)
    return s.strftime("%d.%m %H:%M")


def describe(c: dict, tz: ZoneInfo) -> str:
    e = c["e"]
    t = e["title"]
    if c["kind"] == "new":
        return f"Новое: {t} — {_fmt_when(e, tz)}"
    if c["kind"] == "deleted":
        return f"{'Отменено' if c.get('one') else 'Удалено'}: {t} — {_fmt_when(e, tz)}"
    o = c["old"]
    hidden = e.get("private") or o.get("private")   # «Занят»: прежнее название и место не раскрываем
    parts = []
    if o["start"] != e["start"] or o["end"] != e["end"]:
        if c.get("series"):
            parts.append(f"теперь {_fmt_when(e, tz)}, было {_fmt_when(o, tz)} (всё повторение)")
        else:
            parts.append(f"{_fmt_when(o, tz)} → {_fmt_when(e, tz)}")
    if o["title"] != e["title"] and not hidden:
        parts.append(f"было «{o['title']}»")
    if (o.get("location") or "") != (e.get("location") or "") and not hidden:
        parts.append(f"место: {e.get('location') or 'убрано'}")
    return f"Изменено: {t} — " + (", ".join(parts) or "подробности скрыты")


def record(db: Database, found: list[dict], tz: ZoneInfo, cal_names: dict[str, str]) -> None:
    if not found:
        return
    now = datetime.now(tz)
    if len(found) > MASS:
        # Разбивка без названий и имён — чтобы по сводке дозора понять, откуда пачка (v0.21)
        stats: dict = {"new": 0, "deleted": 0, "changed": 0, "calendars": {}}
        for c in found:
            stats[c["kind"]] = stats.get(c["kind"], 0) + 1
            for k in c["e"].get("calendars") or []:
                stats["calendars"][k] = stats["calendars"].get(k, 0) + 1
        with _lock:
            log = list(db.kv_get(KEY)[0] or [])
            last = log[0] if log else None
            # Пачки подряд (в пределах 3 часов) — одной строкой со счётчиком, а не сотней строк в журнале
            if last and last.get("mass") and now - datetime.fromisoformat(last["at"]) < timedelta(hours=3):
                last["times"] = int(last.get("times") or 1) + 1
                last["at"] = now.isoformat(timespec="seconds")
                last["stats"] = stats
                last["text"] = f"Много изменений сразу ({len(found)}), повторилось {last['times']} раз — похоже, календарь синхронизируется неровно"
                db.kv_set(KEY, log[:KEEP])
                return
        items = [{"id": hashlib.sha1(f"mass{now.isoformat()}".encode()).hexdigest()[:12], "at": now.isoformat(timespec="seconds"),
                  "text": f"Много изменений сразу ({len(found)}) — например, календарь скрыт или переподключён", "people": [],
                  "origin": "", "mass": True, "stats": stats}]
    else:
        items = []
        for c in found:
            e = c["e"]
            text = describe(c, tz)
            items.append({"id": hashlib.sha1(f"{text}|{e.get('uid')}|{now.isoformat()}".encode()).hexdigest()[:12],
                          "at": now.isoformat(timespec="seconds"), "text": text, "origin": _origin(e, cal_names),
                          "people": [p for p in e.get("people", []) if not p.startswith("_")], "uid": e.get("uid"),
                          "event_start": e["start"]})
    with _lock:
        log = items + list(db.kv_get(KEY)[0] or [])
        db.kv_set(KEY, log[:KEEP])


def recent(db: Database, days: int = 7) -> list[dict]:
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    return [c for c in (db.kv_get(KEY)[0] or []) if datetime.fromisoformat(c["at"]) >= cutoff]


def reminders(db: Database, now: datetime, people: set[str] | None) -> list[dict]:
    """Уведомления об изменениях за последние сутки (kind=event — старые приложения покажут как есть)."""
    out = []
    since = now - timedelta(hours=24)
    # Общее событие без участников — всем взрослым: приложения пустой список людей понимают как «никому».
    adults = [p["id"] for p in db.list_people() if not p.get("needs_escort") and not p.get("hidden")
              and not str(p["id"]).startswith("_")]
    for c in db.kv_get(KEY)[0] or []:
        if c.get("mass"):
            continue
        at = datetime.fromisoformat(c["at"])
        if at < since:
            break
        who = c.get("people") or adults
        if people is not None and who and not set(who) & people:
            continue
        # +5 минут (снимок — раз в 2 мин): iPhone и Mac показывают только будущие напоминания — так успеют получить при ближайшем обновлении
        out.append({"id": f"chg:{c['id']}", "kind": "event", "at": (at + timedelta(minutes=5)).isoformat(timespec="seconds"), "start": c.get("event_start") or c["at"],
                    "people": who, "title": c["text"], "text": c.get("origin") or ""})
    return out
