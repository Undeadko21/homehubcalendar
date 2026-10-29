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

BAD_FILE="$APP_DIR/data/.bad_commit"   # коммит, после которого сервер не поднялся (чтобы не пытаться снова и снова)
PORT="${HOMECAL_PORT:-8080}"

if [ "$LOCAL" = "$REMOTE" ] && [ "${1:-}" != "--force" ]; then
  exit 0
fi
if [ "$REMOTE" = "$(cat "$BAD_FILE" 2>/dev/null || true)" ] && [ "${1:-}" != "--force" ]; then
  exit 0
fi

healthy() {  # ждём до 90 секунд, пока /api/health ответит
  for _ in $(seq 1 45); do
    if curl -fsS -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

echo "$(date -Is) обновление $LOCAL → $REMOTE"
git reset -q --hard "origin/$BRANCH"   # config/ и data/ в .gitignore — не затрагиваются
chmod +x deploy/*.sh
if docker compose up -d --build --remove-orphans && healthy; then
  rm -f "$BAD_FILE"
  docker image prune -f >/dev/null
  echo "$(date -Is) версия: $(git log -1 --format='%h %s')"
  exit 0
fi

# Не поднялось — возвращаем прошлую рабочую версию.
echo "$(date -Is) ОШИБКА: $REMOTE не запустился, откат на $LOCAL" >&2
docker compose logs --tail 40 >&2 || true
mkdir -p "$(dirname "$BAD_FILE")" && echo "$REMOTE" > "$BAD_FILE"
git reset -q --hard "$LOCAL"
docker compose up -d --build --remove-orphans
healthy && echo "$(date -Is) откат выполнен, работает $(git log -1 --format='%h %s')" || echo "$(date -Is) откат не помог, нужна ручная проверка" >&2
exit 1
