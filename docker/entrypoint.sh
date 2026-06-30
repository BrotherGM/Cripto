#!/bin/sh
set -e

echo "→ Ожидание базы данных ${DB_HOST}:${DB_PORT}…"
python <<'PY'
import os, time, socket
host, port = os.getenv("DB_HOST", "db"), int(os.getenv("DB_PORT", "5432"))
for _ in range(60):
    try:
        with socket.create_connection((host, port), timeout=2):
            print("  база доступна"); break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("База данных недоступна — выход")
PY

echo "→ Применение миграций…"
python manage.py migrate --noinput

echo "→ Сбор статики…"
python manage.py collectstatic --noinput

# Автосоздание суперпользователя (если заданы переменные окружения)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "→ Создание суперпользователя ${DJANGO_SUPERUSER_USERNAME} (если не существует)…"
  python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null \
    && echo "  создан" || echo "  уже существует"
fi

echo "→ Запуск: $*"
exec "$@"
