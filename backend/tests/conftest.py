import importlib

import pytest


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Приложение с настоящей БД во временной папке и подставным CalDAV-приёмником (`fake.store`)."""
    cfg = tmp_path / "c.yaml"
    cfg.write_text("timezone: Asia/Yekaterinburg\nsources:\n  - id: ya\n    type: caldav\n    url: http://x\n"
                   "    username: u\n    password: p\npeople:\n  - id: anna\n    name: Анна\n")
    monkeypatch.setenv("HOMECAL_CONFIG", str(cfg))
    monkeypatch.setenv("HOMECAL_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from app import core, main
    importlib.reload(core)
    importlib.reload(main)

    class Fake:
        def __init__(self):
            self.store = {}
            self.n = 0

        def create(self, rid, ics):
            self.n += 1
            href = f"/e{self.n}.ics"
            self.store[href] = ics
            return href

        def update(self, rid, href, ics):
            self.store[href] = ics

        def read(self, rid, href):
            return self.store.get(href)

        def delete(self, rid, href):
            del self.store[href]

    fake = Fake()
    monkeypatch.setattr(core, "make_target", lambda key: fake)
    core.db.touch_calendar("ya/home", "ya", "home", "Дом", {"people": ["anna"]})
    client = TestClient(main.app)
    client.fake, client.main, client.core = fake, main, core
    return client
