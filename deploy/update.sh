#!/usr/bin/env bash
# Обновление из репозитория: если в ветке появились новые коммиты —
# подтягиваем и пересобираем контейнер. Запускается таймером systemd
# (homecal-update.timer) каждые 15 минут, можно и вручную.
set -euo pipefail
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$APP_DIR"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch -q origin "$BRANCH"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ] && [ "${1:-}" != "--force" ]; then
  exit 0
fi

echo "$(date -Is) обновление $LOCAL → $REMOTE"
git reset -q --hard "origin/$BRANCH"   # config/ и data/ в .gitignore — не затрагиваются
chmod +x deploy/*.sh
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
echo "$(date -Is) версия: $(git log -1 --format='%h %s')"
