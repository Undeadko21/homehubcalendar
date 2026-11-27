#!/usr/bin/env bash
set -euo pipefail
cd "${APP_DIR:?}"
PORT="${HOMECAL_PORT:-8080}"
STATE="$APP_DIR/data/.deployment"
BAD_FILE="$APP_DIR/data/.bad_commit"
FORCE=0
PREVIOUS_CHECKOUT=
if [[ "${1:-}" == --transition ]]; then
  PREVIOUS_CHECKOUT="$2"
  shift 2
fi
if [[ "${1:-}" == --force ]]; then FORCE=1; fi

# Код уже разобран Bash до reset. Это важно и для запуска, и для отката.
RUN_LOCK="$APP_DIR/data/.deployment.lock"
mkdir -p "$APP_DIR/data"
if command -v flock >/dev/null; then
  exec 9>"$RUN_LOCK"
  flock -n 9 || exit 0
fi

version() {
  local body
  body=$(curl -fsS -m 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null) || return 1
  [[ "$body" =~ \"version\"[[:space:]]*:[[:space:]]*\"[^\"]*\+([0-9a-f]{7,12})\" ]] || return 1
  printf '%s\n' "${BASH_REMATCH[1]}"
}

ready() {
  [[ "$(version)" == "${1:0:7}" ]] &&
    curl -fsS -m 10 "http://127.0.0.1:$PORT/api/ready" >/dev/null 2>&1
}

ready_previous() {
  [[ "$OLD_IMG" == "$(docker inspect -f '{{.Image}}' homehub-calendar 2>/dev/null || true)" ]] &&
    curl -fsS -m 10 "http://127.0.0.1:$PORT/api/ready" >/dev/null 2>&1
}

wait_ready() {
  for _ in $(seq 1 "${HEALTH_TRIES:-45}"); do
    if "$@"; then return 0; fi
    sleep "${HEALTH_SLEEP:-2}"
  done
  return 1
}

prepare_image() {
  if [[ "${HOMECAL_DEPLOY_LOCAL:-0}" == 1 ]]; then
    docker compose build
    return
  fi
  local tag="homehub-calendar:$REMOTE"
  local label='{{ index .Config.Labels "org.opencontainers.image.revision" }}'
  if [[ "$(docker image inspect -f "$label" "$tag" 2>/dev/null || true)" != "$REMOTE" ]]; then
    local url="https://github.com/Undeadko21/homehubcalendar/releases/download/server-$REMOTE/homehub-calendar.tar.gz"
    local archive="$APP_DIR/data/.deployment-image.tar.gz"
    local expected actual
    expected=$(curl --proto '=https' -fsSL --connect-timeout 15 --max-time 30 "${url}.sha256") || return 1
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || return 1
    if ! (umask 077; curl --proto '=https' -fsSL --connect-timeout 15 --max-time 900 "$url" -o "$archive"); then
      rm -f "$archive"
      return 1
    fi
    actual=$(sha256sum "$archive") || return 1
    if [[ "${actual%% *}" != "$expected" ]] || ! docker load -i "$archive"; then
      rm -f "$archive"
      return 1
    fi
    rm -f "$archive"
    [[ "$(docker image inspect -f "$label" "$tag")" == "$REMOTE" ]] || return 1
  fi
  docker tag "$tag" homehub-calendar:local
}

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

rollback() {
  local failure="$1"
  echo "$failure" > "$APP_DIR/data/.bad_reason"
  echo "$REMOTE" > "$BAD_FILE"
  if [[ -z "$OLD_IMG" ]]; then
    git reset -q --hard "$LOCAL" || return 1
    rm -f "$STATE"
    return 0
  fi
  git reset -q --hard "$LOCAL" || return 1
  docker tag "$OLD_IMG" homehub-calendar:local || return 1
  if ready_previous; then
    rm -f "$STATE"
    return 0
  fi
  GIT_SHA="${LOCAL:0:7}" docker compose up -d --no-build --remove-orphans || return 1
  wait_ready ready_previous || return 1
  rm -f "$STATE"
}

record() {
  (umask 077; printf '%s %s %s %s\n' "$1" "$LOCAL" "${OLD_IMG:--}" "$2" > "$STATE.tmp")
  mv -f "$STATE.tmp" "$STATE"
}

finish() {
  rm -f "$STATE" "$BAD_FILE" "$APP_DIR/data/.bad_reason" "$APP_DIR/data/.canary_report"
  if [[ "${HOMECAL_DEPLOY_LOCAL:-0}" != 1 ]]; then
    docker image rm "homehub-calendar:$REMOTE" >/dev/null 2>&1 || true
  fi
  docker image prune -f >/dev/null || true
  echo "$(date -Is) версия: $(git log -1 --format='%h %s')"
}

deploy() {
  local branch available running failed phase
  local head
  branch=$(git rev-parse --abbrev-ref HEAD)
  head=$(git rev-parse HEAD)
  failed=$(cat "$BAD_FILE" 2>/dev/null || true)

  if [[ -f "$STATE" ]]; then
    read -r REMOTE LOCAL OLD_IMG phase < "$STATE"
    [[ "${phase:-prepare}" == prepare || "$phase" == installing ]] || return 1
    [[ "$REMOTE" =~ ^[0-9a-f]{40}$ && "$LOCAL" =~ ^[0-9a-f]{40}$ &&
       ( "$OLD_IMG" == '-' || "$OLD_IMG" =~ ^sha256:[0-9a-f]{64}$ ) ]] || return 1
    if [[ "$OLD_IMG" == '-' ]]; then OLD_IMG=; fi
    if ready "$REMOTE"; then
      git reset -q --hard "$REMOTE"
      finish
      return 0
    fi
    if [[ "$failed" == "$REMOTE" && "$FORCE" == 0 ]]; then
      rollback "$(cat "$APP_DIR/data/.bad_reason")"
      return
    fi
    if [[ "$phase" == installing ]]; then
      if wait_ready ready "$REMOTE"; then
        git reset -q --hard "$REMOTE"
        finish
        return 0
      fi
      rollback "прерван запуск новой версии"
      return 1
    fi
    git fetch -q origin "$branch" || true
    available=$(git rev-parse "origin/$branch")
  else
    git fetch -q origin "$branch"
    available=$(git rev-parse "origin/$branch")
    REMOTE="$available"
    if [[ "$FORCE" == 0 && "$REMOTE" == "$failed" ]]; then return 0; fi
    if [[ "$FORCE" == 0 && "$head" == "$REMOTE" ]] && ready "$REMOTE"; then return 0; fi
    running=$(version || true)
    if [[ -z "$running" ]]; then
      running=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' homehub-calendar 2>/dev/null |
        sed -nE 's/^HOMECAL_BUILD=([0-9a-f]{7,12})$/\1/p' || true)
    fi
    LOCAL="${PREVIOUS_CHECKOUT:-$head}"
    if [[ -n "$running" ]]; then
      LOCAL=$(git rev-parse --verify "$running^{commit}")
    fi
    OLD_IMG=$(docker inspect -f '{{.Image}}' homehub-calendar 2>/dev/null || true)
    if [[ -n "$OLD_IMG" ]]; then
      # Держим образ отката под тегом даже при прерванном процессе.
      docker tag "$OLD_IMG" homehub-calendar:rollback
    fi
    record "$REMOTE" prepare
  fi

  export GIT_SHA="${REMOTE:0:7}"
  echo "$(date -Is) обновление $LOCAL → $REMOTE"
  if [[ "${HOMECAL_DEPLOY_LOCAL:-0}" == 1 ]]; then
    git reset -q --hard "$REMOTE"
  fi
  if ! prepare_image; then
    if [[ "${HOMECAL_DEPLOY_LOCAL:-0}" == 1 ]]; then
      rm -f "$APP_DIR/data/.canary_report"
      rollback "не удалось собрать образ"
      return 1
    fi
    echo "Образ $REMOTE пока недоступен. Повторим по таймеру." >&2
    # Если CI уже выпустил более новый коммит, следующий запуск попробует его.
    if [[ "$REMOTE" != "$available" ]]; then
      record "$available" prepare
    fi
    return 1
  fi
  git reset -q --hard "$REMOTE"
  if ! canary; then
    rollback "не прошло проверку на копии базы"
    return 1
  fi
  record "$REMOTE" installing
  if docker compose up -d --no-build --remove-orphans && wait_ready ready "$REMOTE"; then
    finish
    return 0
  fi
  echo "$(date -Is) ОШИБКА: $REMOTE не запустился, откат на $LOCAL" >&2
  docker compose logs --tail 40 >&2 || true
  rollback "версия не запустилась"
  return 1
}

deploy
