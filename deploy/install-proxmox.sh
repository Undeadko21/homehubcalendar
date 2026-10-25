#!/usr/bin/env bash
# Установка HomeHub Calendar на Proxmox VE одной командой.
# Запускать в консоли Proxmox (Datacenter → узел → Shell) от root:
#
#   bash install-proxmox.sh
#
# Что делает:
#   1. создаёт LXC-контейнер с Debian 12 (непривилегированный, nesting для Docker);
#   2. ставит Docker и git;
#   3. клонирует репозиторий (для приватного — создаёт deploy key и просит добавить его в GitHub);
#   4. спрашивает логин Яндекса и пароль приложения, пишет их в config/.env;
#   5. запускает приложение и включает автообновление из репозитория каждые 15 минут.
#
# Параметры можно переопределить переменными окружения:
#   CTID, CT_HOSTNAME, CT_STORAGE, CT_BRIDGE, CT_MEMORY, CT_DISK, REPO, BRANCH, TZ_NAME
set -euo pipefail

REPO="${REPO:-git@github.com:Undeadko21/homehubcalendar.git}"
REPO_HTTPS="${REPO_HTTPS:-https://github.com/Undeadko21/homehubcalendar.git}"
BRANCH="${BRANCH:-main}"
CT_HOSTNAME="${CT_HOSTNAME:-homehub-calendar}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
CT_MEMORY="${CT_MEMORY:-1024}"
CT_DISK="${CT_DISK:-6}"
TZ_NAME="${TZ_NAME:-Asia/Yekaterinburg}"
APP_DIR=/opt/homehub-calendar

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mОшибка:\033[0m %s\n' "$*" >&2; exit 1; }

command -v pct >/dev/null || die "это нужно запускать на хосте Proxmox VE"
[ "$(id -u)" = 0 ] || die "нужны права root"

# ---------- 1. контейнер ----------
# Повторный запуск продолжает работу с уже созданным контейнером (по имени хоста).
EXISTING=$(pct list | awk -v h="$CT_HOSTNAME" 'NR>1 && $NF==h {print $1; exit}')
if [ -n "$EXISTING" ] && [ -z "${CTID:-}" ]; then
  CTID="$EXISTING"
  say "Контейнер $CTID ($CT_HOSTNAME) уже есть — продолжаю установку в нём"
  pct status "$CTID" | grep -q running || pct start "$CTID"
else
  CTID="${CTID:-$(pvesh get /cluster/nextid)}"
  if [ -z "${CT_STORAGE:-}" ]; then
    CT_STORAGE=$(pvesm status -content rootdir 2>/dev/null | awk 'NR>1 && $3=="active" {print $1; exit}')
    [ -n "$CT_STORAGE" ] || die "не нашёл хранилище для контейнеров, укажите CT_STORAGE=..."
  fi

  say "Готовлю шаблон Debian 12"
  TPL_STORAGE=$(pvesm status -content vztmpl | awk 'NR>1 && $3=="active" {print $1; exit}')
  [ -n "$TPL_STORAGE" ] || die "не нашёл хранилище для шаблонов (vztmpl)"
  echo "   Хранилище шаблонов: $TPL_STORAGE, хранилище контейнеров: $CT_STORAGE"

  # Если шаблон Debian 12 уже скачан — используем его и в интернет не ходим.
  TEMPLATE=$(pveam list "$TPL_STORAGE" 2>/dev/null | awk '{print $1}' | grep -o 'debian-12-standard[^ ]*' | sort -V | tail -1 || true)
  if [ -n "$TEMPLATE" ]; then
    echo "   Шаблон уже есть: $TEMPLATE"
  else
    echo "   Обновляю список шаблонов (до 2 минут)…"
    timeout 120 pveam update || warn "не удалось обновить список шаблонов, пробую с текущим"
    TEMPLATE=$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)
    [ -n "$TEMPLATE" ] || die "шаблон debian-12-standard не найден. Проверьте интернет и DNS на сервере: ping download.proxmox.com"
    ok=""
    for attempt in 1 2 3 4 5; do
      echo "   Скачиваю $TEMPLATE (~120 МБ), попытка $attempt из 5…"
      if pveam download "$TPL_STORAGE" "$TEMPLATE"; then ok=1; break; fi
      warn "скачивание прервалось, повторяю через 5 секунд"
      sleep 5
    done
    [ -n "$ok" ] || die "не удалось скачать шаблон. Скачайте его вручную: $TPL_STORAGE → CT Templates → Templates → debian-12-standard → Download, затем запустите команду снова"
  fi

  say "Создаю контейнер $CTID ($CT_HOSTNAME) на хранилище $CT_STORAGE"
  pct create "$CTID" "$TPL_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$CT_HOSTNAME" \
    --cores 2 --memory "$CT_MEMORY" --swap 512 \
    --rootfs "$CT_STORAGE:$CT_DISK" \
    --net0 "name=eth0,bridge=$CT_BRIDGE,ip=dhcp" \
    --unprivileged 1 --features nesting=1,keyctl=1 \
    --onboot 1 --timezone "$TZ_NAME" \
    --description "HomeHub Calendar — домашний календарь. Репозиторий: $REPO_HTTPS"
  pct start "$CTID"
fi

say "Жду сеть в контейнере"
for _ in $(seq 1 60); do
  pct exec "$CTID" -- timeout 3 bash -c '</dev/tcp/github.com/443' >/dev/null 2>&1 && break
  sleep 2
done
pct exec "$CTID" -- timeout 5 bash -c '</dev/tcp/github.com/443' >/dev/null 2>&1 || die "в контейнере нет интернета (проверьте DHCP на $CT_BRIDGE)"

run() { pct exec "$CTID" -- bash -lc "$1"; }

# ---------- 2. Docker и git ----------
say "Ставлю Docker и git (несколько минут)"
run "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl git ca-certificates >/dev/null"
run "command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh >/dev/null"

# ---------- 3. репозиторий ----------
say "Получаю код"
if run "[ -d $APP_DIR/.git ]"; then
  run "cd $APP_DIR && git pull -q --ff-only"
  echo "Код уже скачан — обновил до последней версии."
elif run "git clone -q --branch $BRANCH $REPO_HTTPS $APP_DIR" 2>/dev/null; then
  echo "Репозиторий публичный — клонирован по HTTPS."
else
  run "mkdir -p /root/.ssh && chmod 700 /root/.ssh && [ -f /root/.ssh/homecal_deploy ] || ssh-keygen -q -t ed25519 -N '' -C 'homehub-calendar@$CT_HOSTNAME' -f /root/.ssh/homecal_deploy"
  run "cat > /root/.ssh/config <<'EOF'
Host github.com
  IdentityFile /root/.ssh/homecal_deploy
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF"
  echo
  echo "Репозиторий приватный. Добавьте этот ключ в GitHub как Deploy key (только чтение):"
  echo "  https://github.com/Undeadko21/homehubcalendar/settings/keys/new"
  echo
  run "cat /root/.ssh/homecal_deploy.pub"
  echo
  read -r -p "Добавили ключ? Нажмите Enter, чтобы продолжить… " _
  until run "git clone -q --branch $BRANCH $REPO $APP_DIR"; do
    read -r -p "Не получилось клонировать. Проверьте ключ и нажмите Enter для повтора… " _
  done
fi

# ---------- 4. настройки и секреты ----------
say "Настраиваю"
run "mkdir -p $APP_DIR/config $APP_DIR/data && cd $APP_DIR && [ -f config/config.yaml ] || cp config.example.yaml config/config.yaml"
run "cd $APP_DIR && [ -f config/.env ] || cp .env.example config/.env; chmod 600 config/.env"
run "sed -i 's|^timezone:.*|timezone: $TZ_NAME|' $APP_DIR/config/config.yaml"

echo
echo "Нужен логин Яндекса и ПАРОЛЬ ПРИЛОЖЕНИЯ для календаря (не основной пароль)."
echo "Создать: https://id.yandex.ru/security/app-passwords → «Календарь»."
echo "Пароль вводится здесь и хранится только на сервере. Можно пропустить (Enter) и заполнить позже в $APP_DIR/config/.env"
if run "grep -qE '^YANDEX_APP_PASSWORD=.+' $APP_DIR/config/.env"; then
  echo "Логин и пароль Яндекса уже сохранены. Нажмите Enter, чтобы оставить их, или введите новые."
fi
read -r -p "Логин Яндекса (например, ivanov@yandex.ru): " YA_LOGIN
read -r -s -p "Пароль приложения: " YA_PASS; echo
if [ -n "$YA_LOGIN" ]; then
  # Передаём значения через временный файл, чтобы пароль не светился в списке процессов.
  TMP=$(mktemp); chmod 600 "$TMP"
  printf 'YANDEX_LOGIN=%s\nYANDEX_APP_PASSWORD=%s\n' "$YA_LOGIN" "$YA_PASS" > "$TMP"
  pct push "$CTID" "$TMP" /tmp/homecal_secrets --perms 600
  rm -f "$TMP"
  run "cd $APP_DIR/config && grep -v -E '^(YANDEX_LOGIN|YANDEX_APP_PASSWORD)=' .env > .env.new || true; cat /tmp/homecal_secrets >> .env.new; mv .env.new .env; chmod 600 .env; rm -f /tmp/homecal_secrets"
fi
unset YA_PASS

# ---------- 5. запуск и автообновление ----------
say "Собираю и запускаю (первая сборка займёт несколько минут)"
run "cd $APP_DIR && docker compose up -d --build"

run "cat > /etc/systemd/system/homecal-update.service <<EOF
[Unit]
Description=HomeHub Calendar: обновление из git
After=network-online.target docker.service

[Service]
Type=oneshot
ExecStart=$APP_DIR/deploy/update.sh
EOF
cat > /etc/systemd/system/homecal-update.timer <<'EOF'
[Unit]
Description=HomeHub Calendar: проверка обновлений каждые 15 минут

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
EOF
chmod +x $APP_DIR/deploy/update.sh
systemctl daemon-reload && systemctl enable --now homecal-update.timer"

IP=$(pct exec "$CTID" -- hostname -I | awk '{print $1}')
PORT=$(run "grep -E '^HOMECAL_PORT=' $APP_DIR/config/.env | cut -d= -f2" || true)
say "Готово!"
echo "  Календарь:      http://$IP:${PORT:-8080}"
echo "  Экран на стене: http://$IP:${PORT:-8080}/?kiosk&view=today"
echo "  Контейнер:      $CTID ($CT_HOSTNAME)"
echo "  Настройки:      pct enter $CTID, затем $APP_DIR/config/"
echo
echo "Откройте календарь → ⚙ Настройки и укажите, чей какой календарь."
