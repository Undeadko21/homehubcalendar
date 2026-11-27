from datetime import datetime
from zoneinfo import ZoneInfo

from app import widget


def test_widget_accepts_calendar_week_without_hiding_earlier_events():

    zone = ZoneInfo("Asia/Yekaterinburg")
    now = datetime(2026, 11, 27, 14, tzinfo=zone)
    monday = now.date().replace(day=23)
    events = [
        {"id": str(i), "title": str(i), "start": f"2026-11-{i}T08:00:00+05:00",
         "end": f"2026-11-{i}T09:00:00+05:00", "all_day": False, "people": []}
        for i in (23, 27)
    ]
    week = widget.build(events, {}, zone, now, 7, start_date=monday)
    assert week["generated"] == "2026-11-27T14:00:00+05:00"
    assert [d["date"] for d in week["days"]] == [f"2026-11-{i}" for i in range(23, 30)]
    assert week["days"][0]["events"][0]["title"] == "23"
    assert week["days"][4]["events"][0]["title"] == "27"
    assert widget.build(events, {}, zone, now)["days"][0]["events"] == []
