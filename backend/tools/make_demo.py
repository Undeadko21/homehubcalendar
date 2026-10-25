"""Генерирует демо-календари (относительно текущей недели) для проверки интерфейса.

    python tools/make_demo.py ../demo
и в config.yaml источники type: ics с url: /путь/к/demo/<имя>.ics
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

today = date.today()
monday = today - timedelta(days=today.weekday())
if today.weekday() >= 5:  # в выходные показываем ближайшую неделю
    monday += timedelta(days=7)


def dt(day_offset: int, hh: int, mm: int = 0) -> str:
    d = monday + timedelta(days=day_offset)
    return datetime(d.year, d.month, d.day, hh, mm).strftime("%Y%m%dT%H%M%S")


def d(day_offset: int) -> str:
    return (monday + timedelta(days=day_offset)).strftime("%Y%m%d")


def vevent(uid, summary, start, end, extra=""):
    allday = len(start) == 8
    p = ";VALUE=DATE" if allday else ""
    return (f"BEGIN:VEVENT\nUID:{uid}\nDTSTART{p}:{start}\nDTEND{p}:{end}\n"
            f"SUMMARY:{summary}\n{extra}END:VEVENT\n")


def cal(name, events):
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:demo\nX-WR-CALNAME:{name}\n{''.join(events)}END:VCALENDAR\n"


shared_meeting = vevent("parents-meeting@demo", "Родительское собрание", dt(2, 18, 30), dt(2, 19, 30),
                        "LOCATION:Школа №12, каб. 204\n")
dinner = vevent("dinner@demo", "Ужин у бабушки", dt(5, 17), dt(5, 20), "LOCATION:ул. Ленина, 5\n")

FILES = {
    "papa": cal("Папа", [
        vevent("standup@demo", "Планёрка", dt(0, 9, 30), dt(0, 10), "RRULE:FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR;COUNT=40\n"),
        vevent("gym-p@demo", "Спортзал", dt(1, 19), dt(1, 20, 30), "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=20\n"),
        vevent("dentist@demo", "Стоматолог", dt(3, 12), dt(3, 13), "CLASS:PRIVATE\n"),
        vevent("trip@demo", "Командировка в Пермь", d(8), d(11)),
        shared_meeting, dinner,
    ]),
    "mama": cal("Мама", [
        vevent("yoga@demo", "Йога", dt(0, 8), dt(0, 9), "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=30\n"),
        vevent("call@demo", "Созвон с клиентом", dt(1, 11), dt(1, 12, 30)),
        vevent("doctor@demo", "Педиатр с Машей", dt(4, 15), dt(4, 16), "LOCATION:Детская поликлиника\n"),
        vevent("bday@demo", "ДР Оли", d(6), d(7), "RRULE:FREQ=YEARLY\n"),
        shared_meeting,
        vevent("dinner-copy@demo", "Ужин у бабушки", dt(5, 17), dt(5, 20)),
    ]),
    "masha": cal("Маша", [
        vevent("school@demo", "Школа", dt(0, 8), dt(0, 13, 30), "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;COUNT=50\n"),
        vevent("dance@demo", "Танцы", dt(1, 16), dt(1, 17, 30), "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;COUNT=20\n"
               "LOCATION:ДК Железнодорожников\n"),
        vevent("english@demo", "Английский", dt(2, 15), dt(2, 16), "RRULE:FREQ=WEEKLY;BYDAY=WE,SA;COUNT=20\n"),
        vevent("party@demo", "День рождения у Кати", dt(6, 12), dt(6, 15)),
    ]),
    "family": cal("Семья", [
        vevent("rent@demo", "Оплатить квартплату", d(3), d(4)),
        vevent("cinema@demo", "Кино всей семьёй", dt(5, 13), dt(5, 15, 30), "LOCATION:Киномакс\n"),
        vevent("vacation@demo", "Отпуск 🏖", d(20), d(30)),
        dinner,
    ]),
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo")
    out.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        (out / f"{name}.ics").write_text(text, encoding="utf-8")
    print(f"Демо-календари записаны в {out.resolve()}")
