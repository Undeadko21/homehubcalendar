#!/usr/bin/env bash
# Настройка VPS (Ubuntu 22.04/24.04) как внешнего входа в домашний календарь. Запускать от root:
#   bash setup-vps.sh cal.example.ru "ssh-ed25519 AAAA... homehub-tunnel"
# Домен уже должен указывать (A-запись) на IP этого сервера. Публичный ключ печатает setup-home.sh.
set -euo pipefail
DOMAIN="${1:?Укажите домен, например cal.example.ru}"
PUBKEY="${2:?Укажите публичный ключ дома (его печатает setup-home.sh)}"
[ "$(id -u)" = 0 ] || { echo "Запустите от root"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ufw fail2ban unattended-upgrades curl gnupg debian-keyring debian-archive-keyring apt-transport-https

# Caddy из официального репозитория (сам получает и продлевает сертификат HTTPS)
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

# Пользователь для туннеля: без пароля и оболочки, ключу разрешено только одно — слушать 127.0.0.1:18080
id tunnel >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin tunnel
install -d -m 700 -o tunnel -g tunnel /home/tunnel/.ssh
echo "restrict,port-forwarding,permitlisten=\"127.0.0.1:18080\" $PUBKEY" > /home/tunnel/.ssh/authorized_keys
chown tunnel:tunnel /home/tunnel/.ssh/authorized_keys
chmod 600 /home/tunnel/.ssh/authorized_keys

cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy no-referrer
		-Server
	}
	reverse_proxy 127.0.0.1:18080 {
		flush_interval -1
	}
}
EOF
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

# Брандмауэр: только SSH, HTTP (для сертификата) и HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl enable --now fail2ban

echo
echo "Готово. Теперь дома: systemctl start homehub-tunnel, затем откройте https://$DOMAIN"
echo "Совет: отключите вход по паролю в SSH (PasswordAuthentication no в /etc/ssh/sshd_config), когда убедитесь, что заходите по ключу."
