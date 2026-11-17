"""Песочница прода: копия базы без секретов, содержимое не меняется."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def test_prepare_strips_secrets_and_keeps_data(tmp_path):
    import sandbox
    src = tmp_path / "src.sqlite3"
    con = sqlite3.connect(src)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated TEXT)")
    con.executemany("INSERT INTO kv VALUES (?,?,?)", [("auth:widget", '"enc1:AAAA"', "x"), ("settings:x", '{"a": 1}', "x")])
    con.commit()      # без close: часть данных ещё в WAL
    dst = sandbox.prepare(src, None, tmp_path / "data")
    con.close()
    rows = dict(sqlite3.connect(dst).execute("SELECT key, value FROM kv").fetchall())
    assert rows == {"settings:x": '{"a": 1}'}
    assert not (tmp_path / "data" / "secret.key").exists()
