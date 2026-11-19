#!/usr/bin/env bash
# Проверка перед пушем в main (пуш = сразу прод). Любая неудача => код возврата != 0.
set -euo pipefail
cd "$(dirname "$0")/.."

# Что меняется относительно прода: закоммиченное и нет (origin/main может быть не скачан — тогда только рабочее дерево)
base=$(git merge-base HEAD origin/main 2>/dev/null || echo HEAD)
changed=$( { git diff --name-only "$base"; git diff --name-only; git diff --name-only --cached; git ls-files --others --exclude-standard; } | LC_ALL=C sort -u)
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")

echo "== приложения iPhone/Mac — только через pull request"
# Swift здесь не собирается: в main он попадает лишь после зелёной сборки iOS/macOS в PR (CLAUDE.md, правило 6).
swift=$(echo "$changed" | grep -E '^(ios/|macos/)' | grep -vE '^(ios|macos)/release/' || true)
if [ -n "$swift" ] && [ "$branch" = "main" ] && [ "${HH_SWIFT_PR_OK:-}" = "" ]; then
  echo "СТОП: правки Swift в main напрямую:"; echo "$swift" | sed 's/^/  /'
  echo "Сделайте ветку и pull request (сборки iOS/macOS пройдут в нём), затем gh pr merge."
  echo "Если сборка уже прошла в PR и это его содержимое — HH_SWIFT_PR_OK=<номер PR> ./deploy/check.sh"
  exit 1
fi

echo "== песочница прода для рискованных правок"
# Лента, снимок, база, запись, команды из облака — прогнать код на копии настоящей базы (backend/tools/sandbox.py).
risky=$(echo "$changed" | grep -E '^backend/app/(db|events|expand|snapshot|writer|writeq|ops|sync|cloud|backup|core|main)\.py$|^backend/app/sources/' || true)
if [ -n "$risky" ]; then
  # хеш: дифф рискованных файлов + содержимое новых (неотслеживаемых) — так же считает sandbox.py mark_ok()
  want=$( { git diff "$base" -- $risky; for f in $(git ls-files --others --exclude-standard -- $risky | LC_ALL=C sort); do cat "$f"; done; } | sha256sum | cut -c1-16)
  have=$(cat "$(git rev-parse --git-path hh-sandbox-ok)" 2>/dev/null || true)   # --git-path: и в worktree исполнителя
  if [ "$have" = "$want" ]; then
    echo "песочница пройдена на этих правках"
  elif [ -n "${HH_SANDBOX_SKIP:-}" ]; then
    echo "ВНИМАНИЕ: песочница пропущена — ${HH_SANDBOX_SKIP}. Сообщить пользователю в отчёте о выкатке."
  else
    echo "СТОП: рискованные файлы без прогона песочницы:"; echo "$risky" | sed 's/^/  /'
    echo "  python backend/tools/sandbox.py <копия базы> [--key …]   (успех запишет отметку для этих правок)"
    echo "  или HH_SANDBOX_SKIP=\"почему нельзя\" ./deploy/check.sh — и сказать об этом пользователю"
    exit 1
  fi
fi

echo "== тесты бэкенда"
(cd backend && python -m pytest -q)
echo "== проверка кода интерфейса (eslint)"
(cd frontend && npx eslint . >/tmp/homehub-eslint.log 2>&1 || { tail -40 /tmp/homehub-eslint.log; exit 1; })
echo "== тесты интерфейса"
(cd frontend && npm test --silent >/tmp/homehub-vitest.log 2>&1 || { tail -40 /tmp/homehub-vitest.log; exit 1; })
echo "== сборка фронтенда"
(cd frontend && npm run build >/tmp/homehub-build.log 2>&1 || { tail -30 /tmp/homehub-build.log; exit 1; })
echo "== тесты навыка Алисы"
python -m pytest -q alice/test_handler.py
echo "OK: можно пушить"
