# 📖 Инструкция по развертыванию на production

## 🎯 Быстрый старт

### Предусловия
- Ubuntu 20.04+ или аналогичная Linux
- PostgreSQL 12+
- Python 3.13
- Nginx
- Systemd

### 1. Подготовка сервера

```bash
# Обновить систему
sudo apt update && sudo apt upgrade -y

# Установить зависимости
sudo apt install -y python3.13 python3.13-venv postgresql postgresql-contrib nginx git curl

# Создать пользователя для приложения
sudo useradd -m -s /bin/bash cripto
sudo usermod -aG sudo cripto
```

### 2. Клонировать и настроить приложение

```bash
sudo su - cripto

# Клонировать репо
git clone <your-repo-url> ~/Cripto
cd ~/Cripto/Develop

# Создать venv
python3.13 -m venv venv313
source venv313/bin/activate

# Установить зависимости
pip install -r requirements.txt
pip install gunicorn
```

### 3. Создать .env.production

```bash
# Скопировать и отредактировать
cp .env.production.example .env.production
nano .env.production

# Обязательно установить:
# - DJANGO_SECRET_KEY (сгенерировать!)
# - DJANGO_DEBUG = "False"
# - DB_PASSWORD (надежный пароль)
# - DJANGO_ALLOWED_HOSTS
# - SECURE_* настройки
```

**Сгенерировать новый SECRET_KEY:**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 4. Настроить PostgreSQL

```bash
sudo su - postgres
psql

-- Создать БД и пользователя
CREATE DATABASE cripto_prod;
CREATE USER cripto WITH ENCRYPTED PASSWORD 'your-strong-password';
ALTER ROLE cripto SET client_encoding TO 'utf8';
ALTER ROLE cripto SET default_transaction_isolation TO 'read committed';
ALTER ROLE cripto SET default_transaction_deferrable TO on;
ALTER ROLE cripto SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE cripto_prod TO cripto;
\q

exit
```

### 5. Применить миграции

```bash
cd ~/Cripto/Develop
source venv313/bin/activate
export $(cat .env.production | xargs)

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
```

### 6. Создать systemd сервисы

**Файл: `/etc/systemd/system/cripto-web.service`**
```ini
[Unit]
Description=Cripto Web Application
After=network.target postgresql.service

[Service]
Type=notify
User=cripto
WorkingDirectory=/home/cripto/Cripto/Develop
EnvironmentFile=/home/cripto/Cripto/Develop/.env.production
ExecStart=/home/cripto/Cripto/Develop/venv313/bin/gunicorn \
    --bind 127.0.0.1:8000 \
    --workers 4 \
    --worker-class sync \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    cripto.wsgi:application
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Файл: `/etc/systemd/system/cripto-worker.service`**
```ini
[Unit]
Description=Cripto Trading Worker
After=network.target postgresql.service

[Service]
Type=simple
User=cripto
WorkingDirectory=/home/cripto/Cripto/Develop
EnvironmentFile=/home/cripto/Cripto/Develop/.env.production
ExecStart=/home/cripto/Cripto/Develop/venv313/bin/python \
    manage.py run_bots \
    --interval 5 \
    --reconcile-every 12
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Запустить сервисы:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable cripto-web cripto-worker
sudo systemctl start cripto-web cripto-worker
sudo systemctl status cripto-web cripto-worker
```

### 7. Настроить Nginx

**Файл: `/etc/nginx/sites-available/cripto`**
```
# Скопировать содержимое из nginx.conf.example
```

**Активировать конфиг:**
```bash
sudo ln -s /etc/nginx/sites-available/cripto /etc/nginx/sites-enabled/
sudo nginx -t  # Проверить синтаксис
sudo systemctl restart nginx
```

### 8. SSL сертификат (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx

# Получить сертификат
sudo certbot certonly --nginx -d example.com -d www.example.com

# Обновлять сертификат автоматически
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

### 9. Настроить логирование

```bash
# Создать папку для логов
sudo mkdir -p /var/log/cripto
sudo chown cripto:cripto /var/log/cripto
sudo chmod 755 /var/log/cripto

# Rotate logs
sudo tee /etc/logrotate.d/cripto > /dev/null <<EOF
/var/log/cripto/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 cripto cripto
    sharedscripts
}
EOF
```

### 10. Настроить бэкапы

**Файл: `/home/cripto/backup.sh`**
```bash
#!/bin/bash
BACKUP_DIR="/home/cripto/backups"
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M%S)
pg_dump -U cripto cripto_prod | gzip > $BACKUP_DIR/cripto_$DATE.sql.gz
# Удалить старые бэкапы (старше 30 дней)
find $BACKUP_DIR -name "cripto_*.sql.gz" -mtime +30 -delete
```

**Crontab для автобэкапа:**
```bash
crontab -e

# Добавить:
0 2 * * * /home/cripto/backup.sh
```

---

## ✅ Проверка работы

### Статус сервисов
```bash
sudo systemctl status cripto-web cripto-worker
```

### Логи
```bash
# Web приложение
sudo journalctl -u cripto-web -f -n 50

# Воркер торговли
sudo journalctl -u cripto-worker -f -n 50

# Nginx
sudo tail -f /var/log/nginx/cripto_error.log
```

### Тестирование
```bash
# Проверить веб
curl -I https://example.com/admin/

# Проверить API
curl https://example.com/dashboard/closed-trades.json | head -20

# Проверить БД
psql -U cripto -d cripto_prod -c "SELECT COUNT(*) FROM grid_gridstrategy;"
```

---

## 🔄 Обновление кода

```bash
# Использовать скрипт развертывания
cd /home/cripto/Cripto/Develop
./deploy.sh
```

---

## 🚨 Emergency commands

### Остановить все
```bash
sudo systemctl stop cripto-web cripto-worker
```

### Перезагрузить web
```bash
sudo systemctl restart cripto-web
```

### Перезагрузить воркер
```bash
sudo systemctl restart cripto-worker
```

### Проверить портов
```bash
sudo lsof -i :8000
sudo lsof -i :80
sudo lsof -i :443
```

### Очистить кэш static
```bash
rm -rf /home/cripto/Cripto/Develop/staticfiles/*
python manage.py collectstatic --noinput
sudo systemctl restart cripto-web
```

---

## 📊 Мониторинг

### Использование ресурсов
```bash
# CPU и RAM
top -u cripto

# Диск
df -h

# Сеть
nethogs cripto
```

### Уведомления об ошибках
Настроить в cripto/settings.py:
```python
ADMINS = [('Admin', 'admin@example.com')]
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'app-password'
```

---

## ✨ Оптимизация

### Gunicorn workers
Количество workers = (2 × CPU cores) + 1
```bash
# 4-ядерный сервер = 9 workers
```

### PostgreSQL buffers
```bash
# /etc/postgresql/*/main/postgresql.conf
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
```

### Nginx caching
```nginx
# В nginx.conf
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=cripto:10m max_size=100m;
proxy_cache cripto;
proxy_cache_valid 200 10m;
proxy_cache_key "$scheme$request_method$host$request_uri";
```

---

## 🆘 Troubleshooting

### Проблема: "502 Bad Gateway"
```bash
# Проверить gunicorn
sudo systemctl status cripto-web
sudo journalctl -u cripto-web -n 50

# Проверить БД подключение
psql -U cripto -d cripto_prod -c "\dt"
```

### Проблема: "Worker not running"
```bash
# Проверить статус
sudo systemctl status cripto-worker

# Проверить логи
sudo journalctl -u cripto-worker -n 100

# Перезагрузить
sudo systemctl restart cripto-worker
```

### Проблема: "Static files not loading"
```bash
# Пересобрать
python manage.py collectstatic --clear --noinput

# Проверить права
ls -la /home/cripto/Cripto/Develop/staticfiles/

# Перезагрузить nginx
sudo systemctl restart nginx
```

---

**Дата развертывания:** ___________

**Версия приложения:** ___________

**Ответственный:** ___________
