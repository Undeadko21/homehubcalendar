"""Расшифровать резервную копию с Яндекс.Диска (папка приложения → backups).

    python backend/tools/restore_backup.py homehub-20261028-0330.db.gz.enc <ключ> data/calendar.db

Ключ — поле «k» кода подключения приложения (или HOMEHUB_KEY навыка Алисы), base64url.
Остановите сервер, замените файл базы результатом и запустите снова.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backup import unseal  # noqa: E402

if len(sys.argv) != 4:
    sys.exit(__doc__)
src, key, dst = sys.argv[1:]
raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
Path(dst).write_bytes(unseal(raw, Path(src).read_bytes()))
print("Готово:", dst)
