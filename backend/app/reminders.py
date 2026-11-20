"""Напоминания для телефона: сервер считает, приложение показывает локальными уведомлениями.

Виды:
  duty   — «пора ехать»: за lead минут до начала окна поездки (только для выбранных людей);
  digest — вечером накануне: у событий детей на следующий день конфликт поездок или не назначен водитель;
  event  — перед обычной встречей: у каждого человека свои интервалы (kv settings:event_reminders),
           `people` — те, кому нужно именно это напоминание, `at` посчитан сервером;
  bday   — утром в день рождения и накануне вечером.
  «Пора выезжать» (id go:…) и утренняя сводка «мой день» (id morning:…) отдаются как kind=event с `people`
  и `at` — старые приложения показывают их без доработок и фильтруют по «чьи напоминания» на телефоне.
Идентификатор стабилен, поэтому приложение не показывает одно и то же дважды.

Для облачного снимка (lead=None) у duty-напоминаний отдаётся `start` и `people`, а `at` не считается:
время «за N минут» и фильтр по людям определяет само приложение — у каждого телефона они свои.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .birthdays import AUTO_RE, upcoming
from .db import Database

EVENT_KEY = "settings:event_reminders"
LEAD_CHOICES = (5, 10, 15, 30, 45, 60, 120, 1440)


def load_rules(db: Database) -> dict[str, list[int]]:
    """{человек: [за сколько минут напомнить, ...]}"""
    return (db.kv_get(EVENT_KEY)[0] or {}).get("people", {})


def save_rules(db: Database, people: dict, known: set[str]) -> dict[str, list[int]]:
    clean: dict[str, list[int]] = {}
    for pid, leads in (people or {}).items():
        if pid not in known:
            continue
        vals = sorted({int(x) for x in leads or [] if 1 <= int(x) <= 10080}, reverse=True)[:4]
        if vals:
            clean[pid] = vals
    cur = db.kv_get(EVENT_KEY)[0] or {}
    cur["people"] = clean
    db.kv_set(EVENT_KEY, cur)
    return clean


def load_allday(db: Database) -> dict:
    """События на весь день: {people: [id…], time: "HH:MM"} — вечером накануне напомнить выбранным людям."""
    v = (db.kv_get(EVENT_KEY)[0] or {}).get("allday") or {}
    t = v.get("time") or "19:00"
    return {"people": list(v.get("people") or []), "time": t}


def save_allday(db: Database, people: list, time_: str, known: set[str]) -> dict:
    try:
        h, m = (int(x) for x in str(time_ or "19:00").split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except (ValueError, AssertionError):
        time_ = "19:00"
    else:
        time_ = f"{h:02d}:{m:02d}"
    cur = db.kv_get(EVENT_KEY)[0] or {}
    cur["allday"] = {"people": [p for p in dict.fromkeys(people or []) if p in known], "time": time_}
    db.kv_set(EVENT_KEY, cur)
    return load_allday(db)


MORNING_KEY = "settings:morning"


def load_morning(db: Database) -> dict:
    """{enabled, time, people}: по умолчанию включено всем взрослым в 07:30."""
    v = db.kv_get(MORNING_KEY)[0] or {}
    adults = [p["id"] for p in db.list_people() if not p.get("needs_escort") and not p.get("hidden") and not p["id"].startswith("_")]
    people = v.get("people")
    return {"enabled": v.get("enabled", True), "time": v.get("time") or "07:30",
            "people": [p for p in people if p in adults] if people is not None else adults, "go": v.get("go", True),
            "changes": v.get("changes", True)}


def save_morning(db: Database, enabled: bool | None, time_: str | None, people: list[str] | None, go: bool | None,
                 changes_: bool | None = None) -> dict:
    cur = dict(db.kv_get(MORNING_KEY)[0] or {})
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    if time_ is not None:
        hh, mm = (int(x) for x in time_.split(":"))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("время вида 07:30")
        cur["time"] = f"{hh:02d}:{mm:02d}"
    if people is not None:
        known = {p["id"] for p in db.list_people()}
        cur["people"] = [p for p in dict.fromkeys(people) if p in known]
    if go is not None:
        cur["go"] = bool(go)
    if changes_ is not None:
        cur["changes"] = bool(changes_)
    db.kv_set(MORNING_KEY, cur)
    return load_morning(db)


def _morning(events: list[dict], today, now: datetime, tz: ZoneInfo, people: set[str] | None,
             morning: dict, weather: dict, horizon_days: int, names: dict | None = None,
             unusual: dict | None = None) -> list[dict]:
    """Утренняя сводка каждому взрослому: его события, его поездки, погода."""
    out = []
    hh, mm = (int(x) for x in morning["time"].split(":"))
    for d in range(0, max(1, horizon_days) + 1):
        day = today + timedelta(days=d)
        at = datetime.combine(day, time(hh, mm), tz)
        if at < now - timedelta(hours=3):
            continue
        for pid in morning["people"]:
            if people is not None and pid not in people:
                continue
            lines, n_ev, n_trip = [], 0, 0
            for e in events:
                if pid not in e["people"] or e.get("absent") or e["start"][:10] != day.isoformat():
                    continue
                if e["all_day"]:
                    if not AUTO_RE.search(e["title"]):
                        lines.append(f"весь день: {e['title']}")
                    continue
                s = datetime.fromisoformat(e["start"]).astimezone(tz)
                lines.append(f"{s.strftime('%H:%M')} {e['title']}")
                if e.get("duty"):
                    n_trip += 1
                else:
                    n_ev += 1
            parts = []
            if n_ev:
                parts.append(f"{n_ev} {_plural(n_ev, 'событие', 'события', 'событий')}")
            if n_trip:
                parts.append(f"{n_trip} {_plural(n_trip, 'поездка', 'поездки', 'поездок')}")
            # имя — чтобы на общем телефоне (без выбора «чьи напоминания») было понятно, чья сводка
            who_name = (names or {}).get(pid)
            title = (f"{who_name}, ваш день: " if who_name else "Ваш день: ") + (", ".join(parts) if parts else "свободно")
            lines = lines[:7]
            if weather.get(day):
                lines.append(f"Погода: {weather[day]}")
            odd = (unusual or {}).get(day) or []   # понедельник: чем неделя необычна (unusual.py, v0.21)
            if odd:
                lines.append("Необычно на неделе: " + "; ".join(odd[:3]) + (f" и ещё {len(odd) - 3}" if len(odd) > 3 else ""))
            out.append({"id": f"morning:{pid}:{day.isoformat()}", "kind": "event", "at": at.isoformat(timespec="seconds"),
                        "start": at.isoformat(timespec="seconds"), "people": [pid], "title": title, "text": "\n".join(lines)})
    return out


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _lead_text(m: int) -> str:
    if m % 1440 == 0:
        d = m // 1440
        return "завтра" if d == 1 else f"через {d} дн."
    if m % 60 == 0:
        h = m // 60
        return "через 1 час" if h == 1 else f"через {h} ч"
    return f"через {m} мин"


def build(events: list[dict], birthdays_manual: list[dict], now: datetime, tz: ZoneInfo,
          people: set[str] | None, lead: int | None = 30, horizon_days: int = 2,
          event_rules: dict[str, list[int]] | None = None,
          allday: dict | None = None, todos: list[dict] | None = None,
          sync_statuses: list[dict] | None = None, names: dict[str, str] | None = None,
          morning: dict | None = None, weather: dict | None = None,
          event_lists: dict[str, list] | None = None, change_items: list[dict] | None = None,
          unusual: dict | None = None) -> list[dict]:
    now = now.astimezone(tz)
    today = now.date()
    out: list[dict] = []
    event_lists = event_lists or {}

    def take(e: dict) -> str:
        """«Взять: шапочка, очки» — неотмеченное из списка вещей события (eventlists.py)."""
        t = [x["text"] if isinstance(x, dict) else x for x in event_lists.get(e.get("uid") or "", [])]
        return ("\nВзять: " + ", ".join(t[:8]) + (f" и ещё {len(t) - 8}" if len(t) > 8 else "")) if t else ""

    def take_ids(e: dict) -> dict:
        """Для кнопки «Всё взял» (Android 2.12): id пунктов, которые отметить. Только у своего списка события —
        общий (например, «Покупки») кнопкой не трогаем."""
        ids = [x["id"] for x in event_lists.get(e.get("uid") or "", []) if isinstance(x, dict) and x.get("own")]
        return {"take_ids": ids} if ids else {}

    # Дела со сроком: утром в день срока и накануне вечером. С исполнителем — как напоминание о встрече (фильтр по людям
    # на устройстве), без исполнителя — всем.
    for it in todos or []:
        if it.get("done") or not it.get("due"):
            continue
        try:
            due = datetime.fromisoformat(it["due"][:10]).date()
        except ValueError:
            continue
        who = [it["person_id"]] if it.get("person_id") else []
        if who and people is not None and not (set(who) & people):
            continue
        kind = "event" if who else "todo"
        base = {"kind": kind, "people": who, "start": datetime.combine(due, time(9, 0), tz).isoformat(timespec="seconds")}
        if due >= today:
            out.append({**base, "id": f"todo:{it['id']}:{due.isoformat()}:0",
                        "at": max(datetime.combine(due, time(9, 0), tz), now).isoformat(timespec="seconds") if due == today
                        else datetime.combine(due, time(9, 0), tz).isoformat(timespec="seconds"),
                        "title": f"Дело на сегодня: {it['text']}", "text": ""})
        if due > today:
            out.append({**base, "id": f"todo:{it['id']}:{due.isoformat()}:1",
                        "at": datetime.combine(due - timedelta(days=1), time(19, 0), tz).isoformat(timespec="seconds"),
                        "title": f"Завтра срок: {it['text']}", "text": ""})

    # Синхронизация молчит больше суток: одно напоминание на каждую «остановку» (время считаем от последнего успеха,
    # поэтому снимок не меняется между пересборками).
    out += sync_alerts(sync_statuses or [], now, tz)

    for e in events:
        duty = e.get("duty")
        if not duty or e["all_day"]:
            continue
        if people is not None and not (set(e["people"]) & people):
            continue
        start = datetime.fromisoformat(e["start"])
        head, _, rest = e["title"].partition(": ")
        conflicts = (duty["parent"].get("escort") or {}).get(duty["role"], {}).get("conflicts", [])
        text = rest or e["title"]
        if e.get("location"):
            text += f" · {e['location']}"
        if conflicts:
            text += " · занят(а): " + ", ".join(c["title"] for c in conflicts)
        item = {"id": f"duty:{e['id']}:{e['start']}", "kind": "duty", "start": e["start"],
                "people": [p for p in e["people"] if not p.startswith("_")],
                "title": f"{head} — в {start.strftime('%H:%M')}", "text": text + take(e), **take_ids(e)}
        if lead is not None:
            item["at"] = (start - timedelta(minutes=lead)).isoformat()
        out.append(item)
        # «Пора выезжать», если время в дороге известно. «Отвезти»: окно уже начинается с выезда (дорога + запас);
        # «забрать»: окно начинается с конца события — выезжать раньше на дорогу и запас.
        esc = (duty["parent"].get("escort") or {})
        tr = esc.get("travel") or {}
        mins = tr.get("minutes")
        go_at = start if duty["role"] == "dropoff" else start - timedelta(minutes=(mins or 0) + (tr.get("buffer") or 0))
        # опоздавшее «пора выезжать» хуже, чем никакого: старые телефоны показывают напоминание до 3 ч после срока
        if mins and (morning or {}).get("go", True) and go_at >= now - timedelta(minutes=20):
            go_text = f"в пути ~{mins} мин"
            if e.get("location"):
                go_text += f" · {e['location']}"
            out.append({"id": f"go:{e['id']}:{e['start']}", "kind": "event", "at": go_at.isoformat(timespec="seconds"),
                        "start": e["start"], "people": item["people"],
                        "title": f"Пора выезжать — {head[:1].lower() + head[1:]}: {rest}" if rest else f"Пора выезжать: {e['title']}",
                        "text": go_text + take(e), **take_ids(e),
                        **({"route": e["location"]} if e.get("location") and "://" not in e["location"] else {})})   # кнопка «Маршрут» (Android 2.12)

    # Обычные встречи: у каждого человека свои интервалы.
    if event_rules:
        for e in events:
            if e.get("duty") or e["all_day"] or e.get("private") or e.get("absent"):
                continue
            start = datetime.fromisoformat(e["start"])
            by_lead: dict[int, list[str]] = {}
            for pid in e["people"]:
                for m in event_rules.get(pid, []):
                    by_lead.setdefault(m, []).append(pid)
            for m, who in by_lead.items():
                if people is not None and not (set(who) & people):
                    continue
                at = start - timedelta(minutes=m)
                if at < now - timedelta(hours=3) or start < now:
                    continue
                text = f"в {start.strftime('%H:%M')}"
                if e.get("location"):
                    text += f" · {e['location']}"
                out.append({"id": f"event:{e['id']}:{e['start']}:{m}", "kind": "event", "at": at.isoformat(timespec="seconds"),
                            "start": e["start"], "people": who,
                            "title": f"{e['title']} — {_lead_text(m)}", "text": text + take(e), **take_ids(e)})

    # События на весь день: накануне вечером (дни рождения напоминает блок bday ниже).
    if allday and allday.get("people"):
        wanted_ad = set(allday["people"])
        hh, mm = (int(x) for x in (allday.get("time") or "19:00").split(":"))
        for e in events:
            if not e["all_day"] or e.get("duty") or e.get("private") or e.get("absent") or AUTO_RE.search(e["title"]):
                continue
            who = [p for p in e["people"] if p in wanted_ad]
            if not who or (people is not None and not (set(who) & people)):
                continue
            day = datetime.fromisoformat(e["start"]).date()
            if day <= today:
                continue
            at = datetime.combine(day - timedelta(days=1), time(hh, mm), tz)
            if at < now - timedelta(hours=3):
                continue
            out.append({"id": f"allday:{e['id']}:{e['start']}", "kind": "event", "at": at.isoformat(timespec="seconds"),
                        "start": e["start"], "people": who, "title": f"Завтра: {e['title']}",
                        "text": e.get("location") or "на весь день"})

    # Дайджест проблем с поездками: накануне в 20:00 для каждого из ближайших дней.
    for d in range(1, max(1, horizon_days) + 1):
        day = today + timedelta(days=d)
        problems = []
        for e in events:
            if e.get("duty") or e["all_day"] or not e.get("escort_issue"):
                continue
            s = datetime.fromisoformat(e["start"])
            if s.date() != day:
                continue
            label = "Конфликт" if e["escort_issue"] == "conflict" else "Нет водителя"
            problems.append(f"{label}: {e['title']} ({s.strftime('%H:%M')})")
        if problems:
            at = max(datetime.combine(day - timedelta(days=1), time(20, 0), tz), now)
            out.append({"id": f"digest:{day.isoformat()}", "kind": "digest", "at": at.isoformat(timespec="seconds"),
                        "title": f"Завтра: проблемы с поездками ({len(problems)})", "text": "\n".join(problems)})

    # Срочно: поездка в ближайшие 12 часов без водителя или с занятым водителем — сразу, не дожидаясь вечернего дайджеста.
    # `at` считаем от начала события (а не от «сейчас»), чтобы снимок не менялся между пересборками.
    names = names or {}
    for e in events:
        if e.get("duty") or e["all_day"] or e.get("private") or not e.get("escort_issue"):
            continue
        s = datetime.fromisoformat(e["start"])
        if not (now <= s <= now + timedelta(hours=12)):
            continue
        what = "некому отвезти или забрать" if e["escort_issue"] != "conflict" else "водитель занят в это время"
        # Что именно не закрыто — чтобы телефон мог предложить «Отвезу я» прямо в уведомлении.
        esc = e.get("escort") or {}
        need = [{"role": r, "person": esc[r].get("person"), "free": esc[r].get("free", [])}
                for r in ("dropoff", "pickup")
                if r in esc and not esc[r].get("skip") and (not esc[r].get("person") or esc[r].get("conflicts"))]
        out.append({"id": f"alert:trip:{e['id']}:{e['start']}:{e['escort_issue']}", "kind": "alert",
                    "at": (s - timedelta(hours=12)).isoformat(timespec="seconds"), "start": e["start"],
                    "title": f"{e['title']} в {s.astimezone(tz).strftime('%H:%M')}: {what}", "text": "Откройте календарь и назначьте водителя",
                    "trip": {"uid": e.get("uid"), "occurrence": e["start"] if e.get("recurring") else None, "need": need,
                             "names": {pid: names[pid] for n in need for pid in [*n["free"], n["person"]] if pid in names}}})

    if change_items and (morning or {}).get("changes", True):
        out += change_items   # «Изменено: …» (changes.py) — уже отфильтрованы по людям

    if morning and morning.get("enabled") and morning.get("people"):
        out += _morning(events, today, now, tz, people, morning, weather or {}, horizon_days, names, unusual)

    for b in upcoming(birthdays_manual, events, today, horizon_days):
        day = date_of(b)
        age = f" ({b['turns']})" if b.get("turns") else ""
        # Утром в сам день и накануне вечером.
        out.append({"id": f"bday:{b['name']}:{b['date']}:0", "kind": "bday",
                    "at": max(datetime.combine(day, time(9, 0), tz), now).isoformat(timespec="seconds"),
                    "title": f"Сегодня день рождения: {b['name']}{age}", "text": ""})
        if b["days"] >= 1:
            out.append({"id": f"bday:{b['name']}:{b['date']}:1", "kind": "bday",
                        "at": datetime.combine(day - timedelta(days=1), time(18, 0), tz).isoformat(timespec="seconds"),
                        "title": f"Завтра день рождения: {b['name']}{age}", "text": ""})
    out.sort(key=lambda r: r.get("at") or r["start"])
    return out


STALE_HOURS = 24


def sync_alerts(statuses: list[dict], now: datetime, tz: ZoneInfo) -> list[dict]:
    items = []
    for st in statuses:
        ok = st.get("last_ok")
        if not ok:
            continue
        try:
            last = datetime.fromisoformat(ok)
        except ValueError:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=tz)
        at = last + timedelta(hours=STALE_HOURS)
        if at > now or now - at > timedelta(hours=36):
            continue
        items.append({"id": f"alert:sync:{st.get('source_id')}:{last.isoformat(timespec='minutes')}", "kind": "alert",
                      "at": at.astimezone(tz).isoformat(timespec="seconds"),
                      "title": "Календарь давно не обновлялся",
                      "text": f"Источник «{st.get('source_id')}» не отвечает с {last.astimezone(tz).strftime('%d.%m %H:%M')}"})
    return items


def date_of(b: dict):
    from datetime import date
    return date.fromisoformat(b["date"])
