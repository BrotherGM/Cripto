# 🚀 Чек-лист подготовки к production

## ⚠️ КРИТИЧНО - Security

### 1. Django SECRET_KEY
```bash
# Сгенерировать новый безопасный ключ:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
- [ ] Обновить в `.env`: `DJANGO_SECRET_KEY="<новый-ключ>"`
- [ ] Ключ должен быть >50 символов и содержать спецсимволы

### 2. DEBUG режим
```bash
# В .env установить:
DJANGO_DEBUG = "False"
```
- [ ] DEBUG = False в production

### 3. ALLOWED_HOSTS
```bash
# В .env установить:
DJANGO_ALLOWED_HOSTS = "example.com,www.example.com"
```
- [ ] Указать реальные домены/IP сервера

### 4. HTTPS/SSL
- [ ] Установить SSL сертификат на сервере
- [ ] Настроить reverse proxy (nginx/Apache) с SSL
- [ ] В settings.py включить:
  ```python
  SECURE_SSL_REDIRECT = True
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  SECURE_HSTS_SECONDS = 31536000  # 1 год
  ```

### 5. Database пароль
```bash
# В PostgreSQL установить пароль:
ALTER ROLE postgres WITH PASSWORD 'secure_password_here';

# В .env:
DB_PASSWORD = "secure_password_here"
```
- [ ] Установить надежный пароль БД

### 6. OKX API ключи
⚠️ **КРИТИЧНО**: Никогда не хранить live ключи в .env на сервере!
- [ ] Использовать переменные окружения системы или vault
- [ ] Или использовать demo ключи (OKX_LIVE_FLAG = "1")

---

## 📦 Зависимости и сборка

### 7. requirements.txt
- [ ] Проверить, все ли зависимости в requirements.txt
```bash
pip freeze > requirements.txt
```

### 8. Миграции БД
```bash
python manage.py migrate --noinput
```
- [ ] Все миграции должны примениться без ошибок

### 9. Статические файлы
```bash
python manage.py collectstatic --noinput
```
- [ ] Собрать статические файлы в STATIC_ROOT

---

## 🔄 Воркер и Supervisor

### 10. Создать systemd сервис для воркера
**Файл:** `/etc/systemd/system/cripto-worker.service`
```ini
[Unit]
Description=Cripto Grid Trading Worker
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=cripto
WorkingDirectory=/home/cripto/Cripto/Develop
Environment="PATH=/home/cripto/Cripto/Develop/venv313/bin"
ExecStart=/home/cripto/Cripto/Develop/venv313/bin/python manage.py run_bots --interval 5 --reconcile-every 12
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] Создать файл сервиса
- [ ] `sudo systemctl daemon-reload`
- [ ] `sudo systemctl enable cripto-worker`
- [ ] `sudo systemctl start cripto-worker`

### 11. Создать systemd сервис для Django
**Файл:** `/etc/systemd/system/cripto-web.service`
```ini
[Unit]
Description=Cripto Web Application
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User=cripto
WorkingDirectory=/home/cripto/Cripto/Develop
Environment="PATH=/home/cripto/Cripto/Develop/venv313/bin"
ExecStart=/home/cripto/Cripto/Develop/venv313/bin/gunicorn cripto.wsgi:application --bind 127.0.0.1:8000 --workers 4 --timeout 120
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] Установить gunicorn: `pip install gunicorn`
- [ ] Создать файл сервиса
- [ ] Настроить nginx reverse proxy

---

## 🗄️ PostgreSQL

### 12. Backup настройки
```bash
# Создать скрипт автобэкапа в crontab:
0 2 * * * pg_dump -U postgres Cripto | gzip > /backups/cripto_$(date +\%Y\%m\%d).sql.gz
```

- [ ] Настроить регулярные бэкапы
- [ ] Проверить, что бэкапы создаются

### 13. Параметры PostgreSQL
```bash
# /etc/postgresql/*/main/postgresql.conf
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
```

- [ ] Оптимизировать параметры под нагрузку

---

## 📊 Мониторинг и логирование

### 14. Логирование
```python
# settings.py
LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'level': 'ERROR',
            'class': 'logging.FileHandler',
            'filename': '/var/log/cripto/error.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'ERROR',
        },
    },
}
```

- [ ] Настроить логирование ошибок
- [ ] Создать папку `/var/log/cripto/`

### 15. Мониторинг процессов
- [ ] Установить Supervisor или SystemD для авторестарта
- [ ] Настроить alerts на критические ошибки
- [ ] Мониторить использование ресурсов (CPU, RAM, Disk)

---

## 🧪 Финальные проверки

### 16. Тестирование
```bash
# Запустить тесты
python manage.py test grid

# Проверить миграции
python manage.py showmigrations

# Проверить security
python manage.py check --deploy
```

- [ ] Все тесты проходят
- [ ] Все миграции применены
- [ ] Security check clean

### 17. Backup и восстановление
- [ ] Протестировать восстановление из бэкапа
- [ ] Убедиться, что бэкапы создаются автоматически

### 18. Документация
- [ ] Создать инструкцию по развертыванию
- [ ] Документировать параметры конфигурации
- [ ] Создать runbook для экстренной остановки

---

## 📋 Перед запуском на production

- [ ] Все чек-листы пройдены
- [ ] Бэкап БД создан
- [ ] SSL сертификат установлен
- [ ] Воркер настроен и работает
- [ ] Логирование настроено
- [ ] Мониторинг настроен
- [ ] Команда готова реагировать на проблемы

**Дата готовности к production: ___________**

**Ответственный: ___________**

---

## 🚨 Emergency procedures

### Остановить торговлю
```bash
sudo systemctl stop cripto-worker
```

### Перезагрузить web приложение
```bash
sudo systemctl restart cripto-web
```

### Проверить статус
```bash
sudo systemctl status cripto-worker cripto-web
sudo journalctl -u cripto-worker -n 100 -f
```

### Восстановить из бэкапа
```bash
psql -U postgres -d Cripto < backup_file.sql
```
