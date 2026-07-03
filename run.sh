#!/usr/bin/env bash
#
# run.sh — одношаговый запуск Cripto на сервере.
#
# Что делает:
#   1) проверяет Docker + docker compose (при необходимости через sudo);
#   2) проверяет .env (создаёт из .env.example, если нет);
#   3) при наличии psql — создаёт базу, если её ещё нет (best-effort);
#   4) собирает образ и поднимает контейнеры web + worker;
#      (миграции накатываются автоматически в entrypoint — migrate_safe);
#   5) ждёт ответа web и печатает адреса и полезные команды.
#
# Идемпотентно: повторный запуск = пересборка и перезапуск.
# Требования: Linux-сервер, внешний PostgreSQL, заполненный .env.
#
set -euo pipefail
cd "$(dirname "$0")"

c_blue='\033[1;34m'; c_green='\033[1;32m'; c_red='\033[1;31m'; c_yellow='\033[1;33m'; c_off='\033[0m'
log()  { printf "${c_blue}→ %s${c_off}\n" "$*"; }
ok()   { printf "${c_green}✓ %s${c_off}\n" "$*"; }
warn() { printf "${c_yellow}! %s${c_off}\n" "$*"; }
die()  { printf "${c_red}✗ %s${c_off}\n" "$*" >&2; exit 1; }

# Значение переменной из .env (без сорсинга — безопасно к спецсимволам).
getenv() { grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '\r'; }

WEB_PORT=8077

# ── 1. Docker + compose ──────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Docker не установлен. Установите Docker Engine и повторите."

SUDO=""
if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    SUDO="sudo"; warn "Docker требует прав — использую sudo."
  else
    die "Нет доступа к Docker. Добавьте пользователя в группу docker (usermod -aG docker \$USER) или запустите через sudo."
  fi
fi

if $SUDO docker compose version >/dev/null 2>&1; then
  DC="$SUDO docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="$SUDO docker-compose"
else
  die "Не найден docker compose (нужен Compose v2 «docker compose» или v1 «docker-compose»)."
fi
ok "Docker готов ($DC)"

# ── 2. .env ──────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  warn ".env не найден — создан из .env.example."
  die "Заполните .env (ключи OKX, DB_PASSWORD, DJANGO_SECRET_KEY) и запустите ./run.sh снова."
fi

DB_NAME="$(getenv DB_NAME)"; DB_USER="$(getenv DB_USER)"
DB_HOST="$(getenv DB_HOST)"; DB_PORT="$(getenv DB_PORT)"; DB_PASS="$(getenv DB_PASSWORD)"
: "${DB_NAME:=Cripto}"; : "${DB_USER:=postgres}"; : "${DB_HOST:=localhost}"; : "${DB_PORT:=5432}"

[ -z "$DB_PASS" ] && warn "DB_PASSWORD в .env пуст — если у Postgres есть пароль, укажите его."
grep -q '^DJANGO_SECRET_KEY=change-me' .env && warn "DJANGO_SECRET_KEY дефолтный — задайте случайную строку для продакшена."
ok ".env на месте (БД $DB_NAME@$DB_HOST:$DB_PORT, пользователь $DB_USER)"

# ── 3. База данных (best-effort) ─────────────────────────────
if command -v psql >/dev/null 2>&1; then
  export PGPASSWORD="$DB_PASS"
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -tAc \
       "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null | grep -q 1; then
    ok "База $DB_NAME существует"
  else
    log "Базы $DB_NAME нет — пытаюсь создать…"
    if createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" 2>/dev/null; then
      ok "База $DB_NAME создана"
    elif command -v sudo >/dev/null 2>&1 && sudo -u postgres createdb "$DB_NAME" 2>/dev/null; then
      ok "База $DB_NAME создана (через пользователя postgres)"
    else
      warn "Не удалось создать базу автоматически. Создайте вручную:  sudo -u postgres createdb $DB_NAME"
    fi
  fi
  unset PGPASSWORD
else
  warn "psql не найден — пропускаю проверку БД. Убедитесь, что база $DB_NAME существует."
fi

# ── 4. Сборка и запуск ───────────────────────────────────────
log "Сборка образа и запуск контейнеров (web + worker)…"
$DC up -d --build
ok "Контейнеры запущены. Миграции применяются автоматически при старте (migrate_safe)."

# ── 5. Ожидание готовности web ───────────────────────────────
if command -v curl >/dev/null 2>&1; then
  log "Ожидание ответа web на порту $WEB_PORT…"
  reachable=""
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:$WEB_PORT/admin/login/" >/dev/null 2>&1; then reachable=1; break; fi
    sleep 2
  done
  if [ -n "$reachable" ]; then ok "web отвечает на http://localhost:$WEB_PORT/"
  else warn "web пока не ответил — смотрите логи: $DC logs -f web"; fi
else
  warn "curl не найден — пропускаю health-check."
fi

# ── 6. Итог ──────────────────────────────────────────────────
echo
$DC ps || true
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; : "${IP:=<IP-сервера>}"
ADMIN_USER="$(getenv DJANGO_SUPERUSER_USERNAME)"; : "${ADMIN_USER:=admin}"
echo
ok "Готово."
cat <<EOF

  Админка:   http://$IP:$WEB_PORT/admin/
  Дашборд:   http://$IP:$WEB_PORT/dashboard/
  Логин:     $ADMIN_USER  (пароль из .env: DJANGO_SUPERUSER_PASSWORD)

  Полезное:
    $DC logs -f web       # логи приложения
    $DC logs -f worker    # логи торгового воркера (run_bots)
    $DC ps                # статус контейнеров
    $DC down              # остановить (внешний Postgres не трогается)
    ./run.sh              # пересобрать и перезапустить (идемпотентно)
EOF
