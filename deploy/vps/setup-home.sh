#!/usr/bin/env bash
# Дома (в LXC, где работает Docker с календарём), от root:
#   bash setup-home.sh IP_ИЛИ_ИМЯ_VPS
# Создаёт ключ, печатает его публичную часть и ставит службу постоянного туннеля до VPS.
set -euo pipefail
VPS="${1:?Укажите адрес VPS}"
PORT="${2:-8080}"   # порт календаря на этой машине
[ "$(id -u)" = 0 ] || { echo "Запустите от root"; exit 1; }
command -v ssh >/dev/null || { apt-get update -y && apt-get install -y openssh-client; }

KEY=/root/.ssh/homehub_tunnel
install -d -m 700 /root/.ssh
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C "homehub-tunnel" -f "$KEY"
ssh-keyscan -T 10 "$VPS" >> /root/.ssh/known_hosts 2>/dev/null || { echo "VPS не отвечает на SSH"; exit 1; }
sort -u /root/.ssh/known_hosts -o /root/.ssh/known_hosts

cat > /etc/systemd/system/homehub-tunnel.service <<EOF
[Unit]
Description=HomeHub: туннель до VPS (календарь снаружи)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/ssh -N -T -i $KEY -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -R 127.0.0.1:18080:127.0.0.1:$PORT tunnel@$VPS
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable homehub-tunnel

echo
echo "Публичный ключ (передайте его скрипту на VPS):"
cat "$KEY.pub"
echo
echo "После настройки VPS запустите: systemctl start homehub-tunnel  (проверка: systemctl status homehub-tunnel)"
