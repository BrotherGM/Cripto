#!/bin/bash
# Скрипт автоматического обновления приложения на сервере

set -e  # Exit on error

echo "🔄 Обновление Cripto приложения"
echo "================================"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
APP_DIR="/app"  # Или где развернуто приложение
BACKUP_DIR="/app/backups"

# Проверить, что мы в правильной директории
if [ ! -f "$APP_DIR/manage.py" ]; then
    echo -e "${RED}❌ manage.py не найден в $APP_DIR${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Создание резервной копии БД${NC}"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql.gz"

if [ -f "$APP_DIR/.env.production" ]; then
    export $(cat "$APP_DIR/.env.production" | xargs)
fi

# Если используется Docker
if docker-compose -f "$APP_DIR/docker-compose.yml" ps 2>/dev/null | grep -q postgres; then
    echo "📦 Бэкап через Docker..."
    docker-compose -f "$APP_DIR/docker-compose.yml" exec -T postgres pg_dump -U cripto cripto_prod | gzip > "$BACKUP_FILE"
else
    echo "📦 Бэкап через локальный PostgreSQL..."
    pg_dump -U cripto cripto_prod | gzip > "$BACKUP_FILE"
fi

echo -e "${GREEN}✅ Бэкап создан: $BACKUP_FILE${NC}"

echo -e "${YELLOW}Step 2: Получение последнего кода из гит${NC}"
cd "$APP_DIR"
git fetch origin
git status

echo -e "${YELLOW}Step 3: Проверка изменений${NC}"
CHANGES=$(git diff origin/main --stat)
if [ -z "$CHANGES" ]; then
    echo -e "${GREEN}✅ Нет новых изменений${NC}"
    exit 0
fi

echo -e "${YELLOW}Новые изменения:${NC}"
echo "$CHANGES"

echo -e "${YELLOW}Step 4: Остановка сервисов${NC}"

# Если используется Docker
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    echo "🐳 Остановка Docker контейнеров..."
    docker-compose -f "$APP_DIR/docker-compose.yml" stop web worker
else
    echo "🔧 Остановка systemd сервисов..."
    sudo systemctl stop cripto-web cripto-worker
fi

echo -e "${YELLOW}Step 5: Обновление кода${NC}"
git pull origin main

echo -e "${YELLOW}Step 6: Применение миграций${NC}"

# Docker способ
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    echo "🐳 Применение миграций в Docker..."
    docker-compose -f "$APP_DIR/docker-compose.yml" exec -T web python manage.py migrate --noinput
    docker-compose -f "$APP_DIR/docker-compose.yml" exec -T web python manage.py collectstatic --noinput
else
    echo "🔧 Применение миграций локально..."
    source venv313/bin/activate
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
fi

echo -e "${YELLOW}Step 7: Запуск сервисов${NC}"

# Docker способ
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    echo "🐳 Запуск Docker контейнеров..."
    docker-compose -f "$APP_DIR/docker-compose.yml" up -d web worker
    
    echo -e "${YELLOW}Проверка здоровья контейнеров...${NC}"
    sleep 10
    docker-compose -f "$APP_DIR/docker-compose.yml" ps
else
    echo "🔧 Запуск systemd сервисов..."
    sudo systemctl start cripto-web cripto-worker
    sudo systemctl status cripto-web cripto-worker --no-pager
fi

echo -e "${YELLOW}Step 8: Проверка приложения${NC}"
sleep 5

# Проверить веб-приложение
if curl -sf http://localhost:8000/admin/ > /dev/null; then
    echo -e "${GREEN}✅ Веб-приложение работает${NC}"
else
    echo -e "${RED}❌ Веб-приложение не отвечает${NC}"
fi

# Просмотреть логи
echo -e "${YELLOW}Последние логи:${NC}"
if [ -f "$APP_DIR/docker-compose.yml" ]; then
    docker-compose -f "$APP_DIR/docker-compose.yml" logs -n 20 web
else
    sudo journalctl -u cripto-web -n 20 --no-pager
fi

echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}✅ Обновление завершено успешно!${NC}"
echo -e "${GREEN}================================${NC}"

# Очистить старые бэкапы (старше 30 дней)
echo -e "${YELLOW}Очистка старых бэкапов...${NC}"
find "$BACKUP_DIR" -name "backup_*.sql.gz" -mtime +30 -delete

echo -e "${GREEN}✅ Готово!${NC}"
