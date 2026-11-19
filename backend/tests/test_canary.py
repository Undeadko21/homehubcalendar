"""Проверка на копии базы перед подменой версии (deploy/update.sh → sandbox.py --canary) — сообщения сервера."""
from app import deploywatch


def test_canary_failure_texts(tmp_path):
    assert deploywatch.problems(tmp_path) == []
    (tmp_path / ".bad_commit").write_text("abcdef1234567\n")
    assert "не запустилось" in deploywatch.problems(tmp_path)[0]
    (tmp_path / ".bad_reason").write_text("не прошло проверку на копии базы\n")
    (tmp_path / ".canary_report").write_text("events неделя  500  ← ОШИБКА\nПРОБЛЕМ: 1\n")
    p = deploywatch.problems(tmp_path)[0]
    assert p.startswith("Обновление abcdef1 не прошло проверку на копии базы") and "ОШИБКА" in p


def test_sandbox_canary_mode_runs_in_image_layout(tmp_path, monkeypatch):
    """--canary: медленно — не провал; путь к коду сервера и интерфейсу — из окружения (в образе /app, /app/static)."""
    import importlib
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    monkeypatch.setenv("HH_SANDBOX_APP_DIR", "/app")
    monkeypatch.setenv("HOMECAL_STATIC", "/app/static")
    import sandbox
    sb = importlib.reload(sandbox)
    assert str(sb.APP_DIR) == "/app" and sb.STATIC_DIR == "/app/static"
    monkeypatch.delenv("HH_SANDBOX_APP_DIR")
    monkeypatch.delenv("HOMECAL_STATIC")
    importlib.reload(sandbox)


def test_canary_note_and_notification(tmp_path, api):
    """Пропуск проверки — заметка в «Состоянии»; провал — уведомление с причиной, один раз на коммит."""
    (tmp_path / ".canary_note").write_text("копию базы сделать не вышло\n")
    assert deploywatch.problems(tmp_path) == ["Последнее обновление поставлено без проверки на копии базы: копию базы сделать не вышло"]
    (tmp_path / ".bad_commit").write_text("abcdef1234567\n")
    (tmp_path / ".bad_reason").write_text("не прошло проверку на копии базы\n")
    sent = []
    import app.deploywatch as dw
    orig = dw.access.notify
    dw.access.notify = lambda db, title, text, **k: sent.append(text)
    try:
        assert dw.check(api.core.db, tmp_path, "0.20.2") == "abcdef1234567"
        dw.check(api.core.db, tmp_path, "0.20.2")
    finally:
        dw.access.notify = orig
    assert len(sent) == 1 and "не прошло проверку на копии базы и не установлено" in sent[0]
