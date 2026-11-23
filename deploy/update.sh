#!/usr/bin/env bash
# Обновление из репозитория (таймер systemd, раз в 15 минут): новые коммиты → пересборка.
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

healthy() {  # ждём до 90 секунд: процесс отвечает (/api/health) и лента собирается (/api/ready)                                       
  for _ in $(seq 1 "${HEALTH_TRIES:-45}"); do
    if curl -fsS -m 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 \
       && curl -fsS -m 10 "http://127.0.0.1:$PORT/api/ready" >/dev/null 2>&1; then return 0; fi
    sleep "${HEALTH_SLEEP:-2}"
  done
  return 1
}

echo "$(date -Is) обновление $LOCAL → $REMOTE"
git reset -q --hard "origin/$BRANCH"   # config/ и data/ в .gitignore — не затрагиваются
# Всё дальнейшее — одна функция: bash разбирает её целиком до выполнения, поэтому откат (git reset на прошлый коммит
# подменяет этот файл) не заставит его дочитывать чужие строки со старого смещения.
deploy_tail() {
  chmod +x deploy/*.sh
  export GIT_SHA="$(git rev-parse --short HEAD)"   # попадёт в образ: «Версия 0.11.4+abc1234»

  # --- Проверка на копии настоящей базы ДО подмены (песочница прода, backend/tools/sandbox.py --canary) ---
  # Новый образ собирается, но работающий контейнер не трогаем: в образе без сети поднимается сервер на копии базы
  # (секреты из копии удаляются) и прогоняются основные запросы. Ошибка — версия не ставится, работает прежняя.
  # Отключить: файл data/.no_canary. Отчёт — только коды и время, без содержимого календаря.
  canary() {
    # Итог проверки — в data/.canary_last («ok|skipped|off|failed коммит»): /api/health показывает его без входа (v0.21)
    last() { echo "$1 ${REMOTE:0:7}" > "$APP_DIR/data/.canary_last"; }
    [ -e "$APP_DIR/data/.no_canary" ] && { echo "проверка на копии базы выключена (data/.no_canary)"; last off; return 0; }
    local note="$APP_DIR/data/.canary_note"   # пропуск проверки виден в «Состоянии» (deploywatch), снимается после проверки
    local running
    running=$(docker inspect -f '{{.State.Running}}' homehub-calendar 2>/dev/null || true)
    if [ "$running" != true ] && [ ! -f "$APP_DIR/data/homecal.sqlite3" ]; then
      echo "проверка на копии базы: базы ещё нет — пропуск"; echo "нет базы для проверки" > "$note"; last skipped; return 0
    fi
    local dir="$APP_DIR/data/.canary"
    rm -rf "$dir" && mkdir -p "$dir" && chmod 700 "$dir"
    local backup_sqlite="import sqlite3; s=sqlite3.connect('file:/data/homecal.sqlite3?mode=ro', uri=True); d=sqlite3.connect('/data/.canary/copy.sqlite3'); s.backup(d); d.close(); s.close()"
    local copied=0
    if [ "$running" = true ]; then
      docker exec homehub-calendar python -c "$backup_sqlite" && copied=1
    else
      docker run --rm --network none --entrypoint python -v "$APP_DIR/data:/data" homehub-calendar:local -c "$backup_sqlite" && copied=1
    fi
    if [ "$copied" = 0 ]; then
      rm -rf "$dir"; echo "ОШИБКА: не удалось снять копию базы"; echo "не удалось снять копию базы" > "$APP_DIR/data/.canary_report"; last failed; return 1
    fi
    local rc=0
    # --init: python в контейнере не процесс 1 и останавливается по сигналу; имя — чтобы добить контейнер после таймаута
    docker rm -f hh-canary >/dev/null 2>&1 || true
    timeout -k 30 600 docker run --rm --init --name hh-canary --network none -e HH_SANDBOX_APP_DIR=/app -e HOMECAL_STATIC=/app/static \
      -v "$APP_DIR/backend/tools:/hh/backend/tools:ro" -v "$dir:/canary" homehub-calendar:local \
      python /hh/backend/tools/sandbox.py /canary/copy.sqlite3 --canary --rollback-db /canary/migrated.sqlite3 > "$dir/report.txt" 2>&1 || rc=$?
    docker rm -f hh-canary >/dev/null 2>&1 || true
    if [ "$rc" = 0 ] && [ -f "$dir/migrated.sqlite3" ]; then
      echo "Схема изменилась: проверяем предыдущую версию на обновлённой копии" >> "$dir/report.txt"
      if [ -n "$OLD_IMG" ]; then
        timeout -k 30 600 docker run --rm --init --name hh-canary --network none -e HH_SANDBOX_APP_DIR=/app -e HOMECAL_STATIC=/app/static \
          -v "$APP_DIR/backend/tools:/hh/backend/tools:ro" -v "$dir:/canary" "$OLD_IMG" \
          python /hh/backend/tools/sandbox.py /canary/migrated.sqlite3 --canary >> "$dir/report.txt" 2>&1 || rc=$?
        docker rm -f hh-canary >/dev/null 2>&1 || true
      else
        echo "ОШИБКА: предыдущий образ недоступен для проверки отката" >> "$dir/report.txt"
        rc=1
      fi
      if [ "$rc" != 0 ]; then
        echo "ОШИБКА: предыдущая версия не прошла проверку на новой схеме" >> "$dir/report.txt"
      elif ! { chmod 600 "$dir/copy.sqlite3" && mv -f "$dir/copy.sqlite3" "$APP_DIR/data/.before-migration.sqlite3"; }; then
        echo "ОШИБКА: не удалось сохранить предрелизную копию базы" >> "$dir/report.txt"
        rc=1
      fi
    fi
    cat "$dir/report.txt"
    grep -E "ОШИБКА|упал|ПРОБЛЕМ|Error|не поднялся" "$dir/report.txt" | head -5 | cut -c1-160 > "$APP_DIR/data/.canary_report" || true
    [ "$rc" = 124 ] || [ "$rc" = 137 ] && echo "проверка не уложилась в 10 минут" >> "$APP_DIR/data/.canary_report"
    rm -rf "$dir"
    if [ "$rc" = 0 ]; then rm -f "$note"; last ok; else last failed; fi
    return $rc
  }

  OLD_IMG=$(docker inspect -f '{{.Image}}' homehub-calendar 2>/dev/null || true)
  OLD_IMG="${OLD_IMG:-$(docker image inspect -f '{{.Id}}' homehub-calendar:local 2>/dev/null || true)}"
  reject() {
    echo "$1" > "$APP_DIR/data/.bad_reason"
    echo "$REMOTE" > "$BAD_FILE"
    git reset -q --hard "$LOCAL"
    if [ -n "$OLD_IMG" ]; then docker tag "$OLD_IMG" homehub-calendar:local; fi
    exit 1
  }

  if ! docker compose build; then
    rm -f "$APP_DIR/data/.canary_report"
    reject "не удалось собрать образ"
  fi
  if ! canary; then
    reject "не прошло проверку на копии базы"
  fi
  rm -f "$APP_DIR/data/.bad_reason" "$APP_DIR/data/.canary_report"

  if docker compose up -d --no-build --remove-orphans && healthy; then
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
  export GIT_SHA="$(git rev-parse --short HEAD)"
  if [ -n "$OLD_IMG" ]; then
    docker tag "$OLD_IMG" homehub-calendar:local
    docker compose up -d --no-build --remove-orphans
  else
    docker compose up -d --build --remove-orphans
  fi
  healthy && echo "$(date -Is) откат выполнен, работает $(git log -1 --format='%h %s')" || echo "$(date -Is) откат не помог, нужна ручная проверка" >&2
  exit 1
}
deploy_tail; exit $?
