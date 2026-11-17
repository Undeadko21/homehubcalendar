#!/usr/bin/env bash
# Проверка прода после выкатки. Без токена — только публичное (версия, раздача приложений);
# с WATCH_TOKEN (токен дозора, из окружения, не из репозитория) — ещё и состояние: проблемы, ошибки экранов, медленные запросы.
#   deploy/postcheck.sh [ожидаемый-коммит] [минут-ждать=25]
# Код выхода 0 — всё хорошо; 1 — выкатка не пришла в срок; 2 — прод стал хуже (проблемы/ошибки).
set -u
BASE="${HH_BASE:-https://homehubcalendar.ru}"
WANT="${1:-}"; WANT="${WANT:0:7}"
WAIT_MIN="${2:-25}"
get() { curl -fsS --max-time 20 "$@" 2>/dev/null; }

ver=""
deadline=$(( $(date +%s) + WAIT_MIN*60 ))
while :; do
  ver=$(get "$BASE/api/health" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true)
  # выкатка пришла, если на проде этот коммит или более новый (после него могли лечь сборки приложений)
  prod="${ver##*+}"
  if [ -n "$ver" ] && { [ -z "$WANT" ] || [[ "$ver" == *"+$WANT"* ]] || git merge-base --is-ancestor "$WANT" "$prod" 2>/dev/null; }; then break; fi
  [ "$(date +%s)" -ge "$deadline" ] && { echo "ПРОВАЛ: за ${WAIT_MIN} мин на проде версия «${ver:-нет ответа}», ждали коммит $WANT"; exit 1; }
  sleep 30
done
echo "версия на проде: $ver"

bad=0
for p in /api/app /api/app-ios /api/app-mac; do
  code=000
  for _ in 1 2 3; do   # соединение иногда сбрасывается по пути — повторяем
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$BASE$p"); [ "$code" = "200" ] && break; sleep 3
  done
  [ "$code" = "200" ] && echo "$p: ok" || { echo "ПРОБЛЕМА: $p → $code"; bad=1; }
done

if [ -n "${WATCH_TOKEN:-}" ]; then
  w=$(get -H "X-Watch-Token: $WATCH_TOKEN" "$BASE/api/watch") || { echo "ПРОБЛЕМА: /api/watch не отвечает"; exit 2; }
  python3 - "$w" <<'PY' || bad=1
import json, sys
w = json.loads(sys.argv[1]); bad = 0
for p in w.get("problems", []):
    print("ПРОБЛЕМА (Состояние):", p); bad = 1
for e in w.get("client_errors", [])[-5:]:
    print("ошибка экрана:", e.get("at"), e.get("where"), (e.get("message") or "")[:120])
slow = [r for r in w.get("perf", {}).get("routes", []) if (r.get("p95") or 0) > 1500 and (r.get("n") or 0) >= 5]
for r in slow:
    print("медленно:", r); bad = 1
print("watch: проблем %d, медленных маршрутов %d" % (len(w.get("problems", [])), len(slow)))
sys.exit(bad)
PY
else
  echo "(WATCH_TOKEN не задан — состояние не проверяется)"
fi
[ "$bad" = 0 ] && echo "OK: прод в порядке" || { echo "ПРОД ХУЖЕ"; exit 2; }
