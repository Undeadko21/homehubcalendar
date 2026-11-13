#!/usr/bin/env bash
# Проверка перед пушем в main (пуш = сразу прод). Любая неудача => код возврата != 0.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== тесты бэкенда"
(cd backend && python -m pytest -q)
echo "== тесты интерфейса"
(cd frontend && npm test --silent >/tmp/homehub-vitest.log 2>&1 || { tail -40 /tmp/homehub-vitest.log; exit 1; })
echo "== сборка фронтенда"
(cd frontend && npm run build >/tmp/homehub-build.log 2>&1 || { tail -30 /tmp/homehub-build.log; exit 1; })
echo "== тесты навыка Алисы"
python -m pytest -q alice/test_handler.py
echo "OK: можно пушить"
