"""Расшифровать резервную копию с Яндекс.Диска (папка приложения → backups).

Ключ — поле «k» кода подключения приложения (или HOMEHUB_KEY навыка Алисы), base64url.
Для копии с вложениями скачайте папку приложения files и укажите --encrypted-files.
Остановите сервер перед восстановлением. Расшифрованные вложения сохранятся рядом с базой в files/.
"""
import argparse
import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.backup import attachment_sizes, check_db, restore_attachments, unseal  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Зашифрованный файл базы")
    parser.add_argument("key", help="Ключ резервной копии")
    parser.add_argument("target", type=Path, help="Путь для восстановленной базы")
    parser.add_argument("--encrypted-files", type=Path, help="Скачанная папка зашифрованных вложений")
    args = parser.parse_args()
    key = base64.urlsafe_b64decode(args.key + "=" * (-len(args.key) % 4))
    data = unseal(key, args.source.read_bytes())
    check_db(data)
    sizes = attachment_sizes(data)
    if sizes and args.encrypted_files is None:
        parser.error("в копии есть вложения; укажите --encrypted-files")
    with tempfile.TemporaryDirectory(dir=args.target.parent) as d:
        staging = Path(d)
        database = staging / "backup.sqlite3"
        database.write_bytes(data)
        if sizes:
            restore_attachments(sizes, key, lambda fid: (args.encrypted_files / fid).read_bytes(), staging)
            files = args.target.parent / "files"
            files.mkdir(mode=0o700, exist_ok=True)
            for fid in sizes:
                (staging / fid).replace(files / fid)
        database.replace(args.target)
    print("Готово:", args.target)


if __name__ == "__main__":
    main()
