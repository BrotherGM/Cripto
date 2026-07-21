# 🐳 Docker Development & Production Guide

## ✨ Преимущества Docker

- ✅ Миграции автоматически применяются при старте
- ✅ PostgreSQL и веб-приложение в одном compose
- ✅ Воркер торговли запускается автоматически
- ✅ Nginx reverse proxy включен
- ✅ Здоровье-чеки (healthchecks) встроены
- ✅ Логирование централизовано
- ✅ Продакшен-ready конфиг

## 🚀 Быстрый старт (5 минут)

### 1. Подготовить .env

```bash
cp .env.docker.example .env
nano .env  # Отредактировать:
# - DJANGO_SECRET_KEY (сгенерировать!)
# - DB_PASSWORD (надежный пароль)
# - DJANGO_ALLOWED_HOSTS (реальный домен)
# - OKX_API_KEY и другие ключи
```

### 2. Сгенерировать SECRET_KEY

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Скопировать вывод в DJANGO_SECRET_KEY в .env

### 3. Запустить Docker Compose

```bash
# Development
docker-compose up -d

# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 4. Проверить статус

```bash
# Логи веб-приложения
docker-compose logs -f web

# Логи воркера
docker-compose logs -f worker

# Логи БД
docker-compose logs -f postgres

# Статус контейнеров
docker-compose ps
```

### 5. Открыть приложение

```
http://localhost:8000/admin/
http://localhost:8000/dashboard/trades/
```

## 📁 Структура файлов

```
Cripto/Develop/
├── Dockerfile                  ← Docker образ приложения
├── docker-compose.yml          ← Docker Compose конфиг
├── .dockerignore              ← Исключить из образа
├── .env.docker.example        ← Пример .env для Docker
│
├── requirements.txt           ← Python зависимости
├── manage.py                  ← Django CLI
├── cripto/                    ← Django приложение
└── grid/                      ← Главное приложение
```

## 🔧 Docker Compose услуги

### postgres (PostgreSQL)
- Образ: `postgres:15-alpine`
- Порт: `5432`
- БД: `cripto_prod`
- Пользователь: `cripto`
- Здоровье-чек: каждые 10 сек

### web (Django Web)
- Образ: собирается из Dockerfile
- Порт: `8000`
- Команда: `python manage.py migrate && gunicorn`
- Здоровье-чек: каждые 30 сек
- Зависит от: `postgres`

### worker (Trading Bot)
- Образ: собирается из Dockerfile
- Команда: `python manage.py run_bots`
- Зависит от: `postgres`, `web`
- Автоматически запускает торговлю

### nginx (Reverse Proxy)
- Образ: `nginx:alpine`
- Портов: `80`, `443`
- Зависит от: `web`

## 🏗️ Что происходит при старте

```
1. Docker pulls образы (postgres, nginx, python)
2. Собирается образ приложения из Dockerfile
3. Запускается PostgreSQL
4. PostgreSQL переходит в "healthy" состояние
5. Запускается веб-приложение
6. Веб-приложение запускает: python manage.py migrate
7. Собираются static файлы
8. Запускается Gunicorn на порту 8000
9. Проверяется здоровье веб-приложения
10. Запускается воркер (зависит от web healthcheck)
11. Запускается Nginx (зависит от web healthcheck)
12. Система готова!
```

⏱️ **Время до готовности: ~30 сек**

## 🔍 Полезные команды

### Логирование

```bash
# Все логи
docker-compose logs

# Логи конкретного сервиса
docker-compose logs web
docker-compose logs worker
docker-compose logs postgres

# Следить в реальном времени
docker-compose logs -f web

# Последние N строк
docker-compose logs -n 100 web
```

### Управление

```bash
# Запустить
docker-compose up -d

# Остановить
docker-compose down

# Перезагрузить
docker-compose restart web

# Пересобрать образ
docker-compose build web

# Просмотреть статус
docker-compose ps

# Проверить здоровье
docker-compose ps | grep -E "web|worker|postgres"
```

### Выполнить команды внутри контейнера

```bash
# Django shell
docker-compose exec web python manage.py shell

# Django admin создать пользователя
docker-compose exec web python manage.py createsuperuser

# Список миграций
docker-compose exec web python manage.py showmigrations

# Применить миграции вручную
docker-compose exec web python manage.py migrate

# Собрать static
docker-compose exec web python manage.py collectstatic
```

### База данных

```bash
# Подключиться к PostgreSQL
docker-compose exec postgres psql -U cripto -d cripto_prod

# Резервная копия БД
docker-compose exec postgres pg_dump -U cripto cripto_prod > backup.sql

# Восстановить из резервной копии
docker-compose exec -T postgres psql -U cripto cripto_prod < backup.sql

# Удалить и пересоздать БД
docker-compose exec postgres dropdb -U cripto cripto_prod
docker-compose exec postgres createdb -U cripto cripto_prod
docker-compose restart web
```

## 🐛 Troubleshooting

### Ошибка: "relation does not exist"

Миграции не были применены. Исправление:

```bash
docker-compose exec web python manage.py migrate --noinput
docker-compose restart web
```

### Ошибка: "Connection refused" (postgres)

PostgreSQL ещё не готов. Дождитесь:

```bash
docker-compose logs postgres | grep "ready to accept"
```

### Ошибка: "Worker keeps restarting"

Проверить логи воркера:

```bash
docker-compose logs -f worker
```

Может быть проблема с БД подключением. Убедиться:

```bash
docker-compose exec web python manage.py dbshell
```

### Ошибка: "Nginx can't connect to web"

Проверить, что веб-приложение в "healthy" состоянии:

```bash
docker-compose ps web
```

Должно быть `Up (healthy)`, а не `Up`

### Port already in use

Портов 8000, 5432, 80, 443 уже используются. Изменить в docker-compose.yml:

```yaml
web:
  ports:
    - "8001:8000"  # Изменить с 8000 на 8001

postgres:
  ports:
    - "5433:5432"  # Изменить с 5432 на 5433

nginx:
  ports:
    - "8080:80"    # Изменить с 80 на 8080
    - "8443:443"   # Изменить с 443 на 8443
```

## 📊 Мониторинг

### Использование ресурсов

```bash
# CPU и RAM в реальном времени
docker stats

# Отдельный контейнер
docker stats cripto-web
docker stats cripto-worker
docker stats cripto-db
```

### Здоровье контейнеров

```bash
# Проверить все здоровье-чеки
docker-compose ps

# Посмотреть детальный статус
docker inspect cripto-web --format='{{.State.Health}}'
```

## 🔒 Security для Production

### .env файл

```bash
# Никогда не коммитить .env в гит!
echo ".env" >> .gitignore
chmod 600 .env
```

### Переменные окружения

```bash
# Вместо .env использовать переменные системы
export DJANGO_SECRET_KEY="..."
export DB_PASSWORD="..."
docker-compose up -d
```

### SSL сертификат

```bash
# Установить Let's Encrypt сертификат
sudo certbot certonly --standalone -d example.com

# Указать в nginx.conf
ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
```

## 🚀 Production развертывание

### Создать docker-compose.prod.yml

```yaml
version: '3.9'

services:
  web:
    restart: always
    healthcheck:
      interval: 20s
      timeout: 10s
      retries: 5

  worker:
    restart: always

  postgres:
    restart: always
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}

  nginx:
    restart: always
    volumes:
      - ./nginx.conf.prod:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
```

### Запустить production

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 📋 Чек-лист перед production

- [ ] .env создан с реальными параметрами
- [ ] DJANGO_SECRET_KEY новый и надежный
- [ ] DB_PASSWORD надежный
- [ ] SSL сертификат установлен
- [ ] Nginx конфиг обновлен для SSL
- [ ] Бэкап БД перед запуском
- [ ] Docker образ протестирован локально
- [ ] docker-compose ps показывает все "healthy"
- [ ] Логирование настроено
- [ ] Мониторинг настроен

## 📞 Поддержка

Документация:
- `DEPLOYMENT_GUIDE.md` — original guide
- `PRODUCTION_CHECKLIST.md` — security checklist
- `Dockerfile` — образ приложения
- `docker-compose.yml` — all services

Логирование:
```bash
docker-compose logs -f
```

Обновление кода:
```bash
git pull origin main
docker-compose build --no-cache
docker-compose up -d
```
