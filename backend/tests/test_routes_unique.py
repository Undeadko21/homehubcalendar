"""Один адрес + метод — один обработчик. Иначе новый маршрут молча перекрывает старый
(v0.19: GET /api/changes нового журнала затёр журнал записей с «отменить»)."""
from collections import Counter


def test_no_duplicate_routes(api):
    from app.main import app
    seen = Counter()
    for r in app.routes:
        for m in getattr(r, "methods", None) or ():
            if m != "HEAD":
                seen[(m, getattr(r, "path", ""))] += 1
    dup = sorted(f"{m} {p}" for (m, p), n in seen.items() if n > 1)
    assert not dup, "Маршрут объявлен дважды: " + ", ".join(dup)
