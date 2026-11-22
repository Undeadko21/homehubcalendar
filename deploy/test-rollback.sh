#!/usr/bin/env bash
# Проверка отката update.sh без настоящего Docker: подставные docker и curl, временный git-репозиторий.
#   deploy/test-rollback.sh
# Сценарий: хороший коммит → «сломанный» коммит (сервер не поднимается) → откат и запоминание плохого коммита →
# повторный запуск ничего не делает → исправляющий коммит применяется.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/origin" "$T/app/deploy" "$T/app/data"

# подставной docker: «поднимается», только если в рабочей копии нет файла BROKEN; curl отвечает так же
cat > "$T/bin/docker" <<EOF
#!/usr/bin/env bash
echo "docker \$*" >> "$T/docker.log"
if [ "\$1" = "compose" ] && [ "\$2" = "up" ]; then
  if [ -e "$T/app/BROKEN" ]; then rm -f "$T/healthy"; else touch "$T/healthy"; fi
fi
if [ "\$1" = "compose" ] && [ "\$2" = "build" ] && [ -e "$T/app/BUILD_BAD" ]; then exit 1; fi
# проверка на копии базы: «docker run» падает, если в новой версии есть файл CANARY_BAD
if [ "\$1" = "run" ] && [ -e "$T/app/CANARY_BAD" ]; then echo "events неделя  500  ← ОШИБКА"; echo "ПРОБЛЕМ: 1"; exit 1; fi
if [ "\$1" = "image" ]; then echo "sha256:old"; fi
exit 0
EOF
cat > "$T/bin/curl" <<EOF
#!/usr/bin/env bash
[ -e "$T/healthy" ]
EOF
chmod +x "$T/bin/docker" "$T/bin/curl"
export PATH="$T/bin:$PATH" HEALTH_TRIES=2 HEALTH_SLEEP=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

git init -q --bare -b main "$T/origin.git"
git init -q -b main "$T/seed"; cd "$T/seed"
git config user.email t@t; git config user.name t
mkdir deploy; cp "$HERE/update.sh" deploy/update.sh; echo v1 > VERSION
echo "data/" > .gitignore
git add -A; git commit -qm good1; git remote add origin "$T/origin.git"; git push -q origin main
git clone -q "$T/origin.git" "$T/app2"; rm -rf "$T/app"; mv "$T/app2" "$T/app"; mkdir -p "$T/app/data"
cd "$T/app"; git config user.email t@t; git config user.name t
GOOD1=$(git rev-parse HEAD)

check() { if eval "$2"; then echo "  ok: $1"; else echo "  FAIL: $1"; exit 1; fi; }

# 1. выходит сломанный коммит
cd "$T/seed"; touch BROKEN; echo v2 > VERSION; git add -A; git commit -qm broken; git push -q origin main
BAD=$(git rev-parse HEAD)
cd "$T/app"
set +e; APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1; rc=$?; set -e
check "сломанный коммит → код выхода 1" "[ $rc -eq 1 ]"
check "рабочая копия вернулась на прошлый коммит" "[ \"\$(git rev-parse HEAD)\" = \"$GOOD1\" ]"
check "плохой коммит записан" "[ \"\$(cat data/.bad_commit)\" = \"$BAD\" ]"
check "после отката сервер поднят" "[ -e \"$T/healthy\" ]"

# 2. повторный запуск не пытается снова
: > "$T/docker.log"
APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1
check "повторный запуск ничего не пересобирает" "[ ! -s \"$T/docker.log\" ]"

# 3. исправление выходит — применяется
cd "$T/seed"; git rm -q BROKEN; echo v3 > VERSION; git add -A; git commit -qm fix; git push -q origin main
FIX=$(git rev-parse HEAD)
cd "$T/app"; APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1
check "исправление применено" "[ \"\$(git rev-parse HEAD)\" = \"$FIX\" ]"
check "метка плохого коммита снята" "[ ! -e data/.bad_commit ]"

# 4. новая версия не проходит проверку на копии базы — контейнер не трогаем, остаёмся на прежней
cd "$T/seed"; touch CANARY_BAD; echo v4 > VERSION; git add -A; git commit -qm canary-bad; git push -q origin main
CB=$(git rev-parse HEAD)
cd "$T/app"; : > "$T/docker.log"
set +e; APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1; rc=$?; set -e
check "не прошла проверку → код выхода 1" "[ $rc -eq 1 ]"
check "рабочая копия осталась на прошлом коммите" "[ \"\$(git rev-parse HEAD)\" = \"$FIX\" ]"
check "плохой коммит записан, причина — проверка" "[ \"\$(cat data/.bad_commit)\" = \"$CB\" ] && grep -q 'копии базы' data/.bad_reason"
check "в отчёте — строка с ошибкой" "grep -q ОШИБКА data/.canary_report"
check "контейнер не перезапускали" "! grep -q 'compose up' \"$T/docker.log\""
check "образ вернули на прежний" "grep -q 'tag sha256:old' \"$T/docker.log\""
check "копия базы удалена" "[ ! -e data/.canary ]"

# 5. исправление после непрошедшей проверки — ставится
cd "$T/seed"; git rm -q CANARY_BAD; echo v5 > VERSION; git add -A; git commit -qm fix2; git push -q origin main
F2=$(git rev-parse HEAD)
cd "$T/app"; APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1
check "исправление после проверки применено" "[ \"\$(git rev-parse HEAD)\" = \"$F2\" ] && [ ! -e data/.bad_reason ] && [ ! -e data/.bad_commit ]"
check "проверку запускали с --init и именем (таймаут останавливает контейнер)" "grep -q 'run --rm --init --name hh-canary --network none' \"$T/docker.log\""

# 6. выключатель data/.no_canary — проверка не запускается, версия ставится
cd "$T/seed"; touch CANARY_BAD; echo v6 > VERSION; git add -A; git commit -qm no-canary; git push -q origin main
NC=$(git rev-parse HEAD)
cd "$T/app"; touch data/.no_canary; : > "$T/docker.log"; APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1
check "с data/.no_canary проверка не запускается" "[ \"\$(git rev-parse HEAD)\" = \"$NC\" ] && ! grep -q ' run ' \"$T/docker.log\""
check "успешная версия запускается без пересборки" "grep -q 'compose up -d --no-build' \"$T/docker.log\" && [ \"$(grep -c 'compose build' "$T/docker.log")\" -eq 1 ]"

# 7. ошибка сборки не подменяет рабочий контейнер
cd "$T/seed"; touch BUILD_BAD; git add -A; git commit -qm build-bad; git push -q origin main
cd "$T/app"; : > "$T/docker.log"
if APP_DIR="$T/app" bash deploy/update.sh >/dev/null 2>&1; then exit 1; fi
check "ошибка сборки оставляет прошлый коммит" "[ \"$(git rev-parse HEAD)\" = \"$NC\" ]"
check "после ошибки сборки контейнер не перезапускается" "! grep -q 'compose up' \"$T/docker.log\""
echo "Откат деплоя работает."
