#!/bin/bash
# Агент HomeHub на VPS: сторож туннеля (уведомление в ntfy), ежечасный отчёт домашнему серверу, ежедневная копия настроек.
# Запускается на VPS под root:  curl -fsS -H "Authorization: Bearer ТОКЕН" http://127.0.0.1:18080/api/vps/install.sh | bash
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Запустите под root"; exit 1; }

install -d -m 755 /var/lib/homehub-agent
umask 077
cat > /etc/homehub-agent.env <<ENV
TOKEN='@TOKEN@'
NTFY_URL='@NTFY@'
BASE='http://127.0.0.1:18080'
ENV
umask 022

cat > /usr/local/bin/homehub-agent <<'AGENT'
#!/bin/bash
# homehub-agent watch|report
. /etc/homehub-agent.env
STATE=/var/lib/homehub-agent
VERSION=2
COPIES=/var/backups/homehub
KEEP=14

notify() {
  [ -n "${NTFY_URL:-}" ] || return 0
  curl -fsS -m 15 -H "Title: Домашний календарь" -H "Priority: ${2:-high}" -d "$1" "$NTFY_URL" >/dev/null 2>&1 || true
}

once_a_day() {   # once_a_day ключ — вернёт 0 не чаще раза в сутки
  local f="$STATE/$1"
  if [ -f "$f" ] && [ $(( $(date +%s) - $(stat -c %Y "$f") )) -lt 86400 ]; then return 1; fi
  touch "$f"; return 0
}

watch() {
  if ! systemctl is-active --quiet caddy; then
    systemctl restart caddy 2>/dev/null || true
    sleep 3
    systemctl is-active --quiet caddy || { once_a_day caddy_down && notify "На VPS не запускается Caddy: календарь снаружи недоступен"; }
  fi
  local f="$STATE/fails" n
  n=$(cat "$f" 2>/dev/null || echo 0)
  if curl -fsS -m 10 "$BASE/api/health" >/dev/null 2>&1; then
    [ "$n" -ge 2 ] && notify "Календарь снова доступен" default
    echo 0 > "$f"
  else
    n=$((n + 1)); echo "$n" > "$f"
    # два промаха подряд (≈10 минут) — уведомление, дальше раз в 6 часов напоминаем
    if [ "$n" -eq 2 ] || { [ "$n" -gt 2 ] && [ $(( (n - 2) % 72 )) -eq 0 ]; }; then
      notify "Домашний календарь недоступен: туннель или домашний сервер не отвечает уже $((n * 5)) минут"
    fi
  fi
}

dbcopy() {   # раз в сутки забираем с домашнего сервера зашифрованную копию базы (расшифровка — backend/tools/restore_backup.py)
  install -d -m 700 "$COPIES"
  if once_a_day dbcopy; then
    local name="db-$(date +%Y%m%d-%H%M).bin"
    if curl -fsS -m 120 -H "Authorization: Bearer $TOKEN" "$BASE/api/vps/db-backup" -o "$COPIES/$name.part" 2>/dev/null \
        && [ -s "$COPIES/$name.part" ]; then
      mv "$COPIES/$name.part" "$COPIES/$name"
      ls -1t "$COPIES"/db-*.bin 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
    else
      rm -f "$COPIES/$name.part"; rm -f "$STATE/dbcopy"   # не вышло — попробуем при следующем отчёте
      notify "Не удалось забрать копию базы с домашнего сервера" default
    fi
  fi
}

report() {
  dbcopy
  local tmp; tmp=$(mktemp -d)
  python3 - "$tmp" <<'PY'
import json, os, re, subprocess, sys, time, shutil
tmp = sys.argv[1]
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
disk = int(sh("df --output=pcent / | tail -1").strip().rstrip("%") or 0)
domains = []
try:
    for line in open("/etc/caddy/Caddyfile"):
        m = re.match(r"^([^\s{#][^{]*)\{", line)
        if m:
            domains += [d.strip() for d in m.group(1).split(",") if d.strip() and not d.strip().startswith(":")]
except OSError:
    pass
certs = {}
for d in domains[:6]:
    out = sh(f"echo | timeout 8 openssl s_client -connect 127.0.0.1:443 -servername {d} 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null")
    m = re.search(r"notAfter=(.+)", out)
    if m:
        try:
            end = time.mktime(time.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z"))
            certs[d] = int((end - time.time()) // 86400)
        except ValueError:
            pass
rep = {"disk_pct": disk, "certs": certs, "caddy": sh("systemctl is-active caddy").strip() == "active",
       "load": sh("cut -d' ' -f1-3 /proc/loadavg").strip(),
       "uptime_days": int(float(open("/proc/uptime").read().split()[0]) // 86400), "agent": "2"}
import glob
cp = sorted(glob.glob("/var/backups/homehub/db-*.bin"))
if cp:
    rep["db_copy"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(cp[-1]))), "count": len(cp), "size": os.path.getsize(cp[-1])}
json.dump(rep, open(os.path.join(tmp, "report.json"), "w"))
PY
  python3 - "$tmp" "$STATE" <<'PY'
import base64, json, os, sys, time, subprocess, tarfile, io
tmp, state = sys.argv[1:3]
rep = json.load(open(os.path.join(tmp, "report.json")))
marker = os.path.join(state, "backup_done")
want = not os.path.exists(marker) or time.time() - os.path.getmtime(marker) > 86000
body = {"report": rep}
if want:
    files = ["/etc/caddy/Caddyfile", "/home/tunnel/.ssh/authorized_keys", "/etc/fail2ban/jail.local", "/etc/ssh/sshd_config.d"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in files:
            if os.path.exists(f):
                tar.add(f)
        ufw = subprocess.run("ufw status verbose", shell=True, capture_output=True, text=True).stdout.encode()
        info = tarfile.TarInfo("ufw-status.txt"); info.size = len(ufw); tar.addfile(info, io.BytesIO(ufw))
    body["backup"] = base64.b64encode(buf.getvalue()).decode()
json.dump(body, open(os.path.join(tmp, "body.json"), "w"))
open(os.path.join(tmp, "want"), "w").write("1" if want else "0")
PY
  if curl -fsS -m 30 -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
        --data-binary @"$tmp/body.json" "$BASE/api/vps/ingest" >/dev/null 2>&1; then
    [ "$(cat "$tmp/want")" = 1 ] && touch "$STATE/backup_done"
  fi
  # собственные предупреждения агента (раз в сутки), чтобы не зависеть от домашнего сервера
  local disk cert
  disk=$(python3 -c "import json;print(json.load(open('$tmp/report.json'))['disk_pct'])")
  [ "$disk" -ge 90 ] && once_a_day disk && notify "На VPS занято $disk% диска"
  cert=$(python3 -c "import json;v=json.load(open('$tmp/report.json'))['certs'].values();print(min(v) if v else 99)")
  [ "$cert" -lt 10 ] && once_a_day cert && notify "Сертификат на VPS истекает через $cert дн."
  rm -rf "$tmp"
  return 0
}

case "${1:-}" in
  watch) watch ;;
  report) report ;;
  *) echo "homehub-agent watch|report"; exit 1 ;;
esac
AGENT
chmod 755 /usr/local/bin/homehub-agent

for unit in watch report; do
  if [ "$unit" = watch ]; then every="5min"; else every="1h"; fi
  cat > /etc/systemd/system/homehub-$unit.service <<UNIT
[Unit]
Description=HomeHub agent ($unit)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/homehub-agent $unit
UNIT
  cat > /etc/systemd/system/homehub-$unit.timer <<UNIT
[Unit]
Description=HomeHub agent ($unit)
[Timer]
OnBootSec=2min
OnUnitActiveSec=$every
AccuracySec=30s
[Install]
WantedBy=timers.target
UNIT
done
systemctl daemon-reload
systemctl enable --now homehub-watch.timer homehub-report.timer >/dev/null
/usr/local/bin/homehub-agent report || true
echo "Готово: агент HomeHub установлен (сторож каждые 5 минут, отчёт каждый час)."
