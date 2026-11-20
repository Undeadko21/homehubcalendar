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
  git fetch -q origin main 2>/dev/null || true   # на проде может быть коммит новее нашего (сборки приложений)
  if [ -n "$ver" ] && { [ -z "$WANT" ] || [[ "$ver" == *"+$WANT"* ]] || git merge-base --is-ancestor "$WANT" "$prod" 2>/dev/null; }; then break; fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    can=$(get "$BASE/api/health" | python3 -c 'import sys,json; c=json.load(sys.stdin).get("canary") or {}; print(c.get("state",""), c.get("commit",""))' 2>/dev/null || true)
    [ "${can%% *}" = "failed" ] && [ "${can##* }" = "$WANT" ] && { echo "ПРОВАЛ: $WANT не прошёл проверку на копии базы дома — работает прежняя версия; причина — в «Состоянии»"; exit 1; }
    echo "ПРОВАЛ: за ${WAIT_MIN} мин на проде версия «${ver:-нет ответа}», ждали коммит $WANT"; exit 1
  fi
  sleep 30
done
echo "версия на проде: $ver"
can=$(get "$BASE/api/health" | python3 -c 'import sys,json; c=json.load(sys.stdin).get("canary") or {}; print(c.get("state","—"), c.get("commit",""))' 2>/dev/null || true)
case "${can%% *}" in
  ok) echo "проверка на копии базы: пройдена (${can##* })" ;;
  skipped) echo "заметка: выкатка поставлена БЕЗ проверки на копии базы (${can##* }) — причина в «Состоянии»" ;;
  off) echo "заметка: проверка на копии базы выключена (data/.no_canary)" ;;
  *) echo "проверка на копии базы: нет данных (${can:-—})" ;;
esac

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
import json, os, sys
w = json.loads(sys.argv[1]); bad = 0
# В GitHub Actions (HH_QUIET=1) журнал публичный — только счётчики, без текстов (в них бывают имена и названия событий),
# и провал — только по выкатке («Обновление …») и скорости; прочие проблемы «Состояния» разберёт дозор.
quiet = os.environ.get("HH_QUIET") == "1"
NOTE = ("Шум:", "Тренд:", "Сообщение:")   # зависят от дня семьи, не от выкатки — сообщаем, но не откатываем
other = 0
for p in w.get("problems", []):
    if p.startswith(NOTE):
        print("заметка:", p.split(":")[0] if quiet else p)
        continue
    if quiet and not p.startswith("Обновление"):
        other += 1
        continue
    print("ПРОБЛЕМА (Состояние):", "обновление не встало (подробности — в «Состоянии»)" if quiet else p); bad = 1
if other:
    print(f"заметка: в «Состоянии» ещё {other} проблем(ы) не про выкатку — утренний дозор разберёт")
errs = w.get("client_errors", [])
if quiet:
    print("ошибок экранов за сутки:", len(errs))
else:
    for e in errs[-5:]:
        print("ошибка экрана:", e.get("at"), e.get("where"), (e.get("message") or "")[:120])
# Медленно — провал, только если медленных запросов к маршруту 3+ (один выброс: правка в Яндексе заняла 9 с и лента ждала её —
# при n≈20 он и есть p95; такое бывает и без вины выкатки — v0.21.1)
perf = w.get("perf", {})
times = {}
for s in perf.get("slow", []):
    times[s.get("route")] = times.get(s.get("route"), 0) + 1
slow = []
for r in perf.get("routes", []):
    if (r.get("p95") or 0) > 1500 and (r.get("n") or 0) >= 5:
        info = {k: r.get(k) for k in ("route", "p95", "n")} if quiet else r
        if times.get(r.get("route"), 0) >= 3:
            slow.append(r)
            print("медленно:", info, "— медленных запросов:", times[r.get("route")]); bad = 1
        else:
            print("заметка: единичный медленный запрос:", info)
print("watch: проблем %d, медленных маршрутов %d" % (len(w.get("problems", [])), len(slow)))
sys.exit(bad)
PY
else
  echo "(WATCH_TOKEN не задан — состояние не проверяется)"
fi
[ "$bad" = 0 ] && echo "OK: прод в порядке" || { echo "ПРОД ХУЖЕ"; exit 2; }
