# 🔄 Инструкция по обновлению приложения на сервере

## ✨ Варианты обновления

### 1️⃣ Вручную на сервере (рекомендуется)

**Самый простой и безопасный способ**

```bash
# SSH на сервер
ssh user@your-server.com

# Перейти в папку приложения
cd /app

# Запустить скрипт обновления
./update.sh
```

**Что происходит:**
1. ✅ Создаётся резервная копия БД
2. ✅ Получается свежий код из гит
3. ✅ Проверяются изменения
4. ✅ Останавливаются сервисы
5. ✅ Применяются миграции
6. ✅ Собираются static файлы
7. ✅ Запускаются сервисы
8. ✅ Проверяется здоровье приложения

**Время:** ~2-3 минуты

---

### 2️⃣ Автоматически через GitHub Actions (CI/CD)

**При каждом коммите в main автоматически развертывается на сервер**

#### Настройка (одноразово)

1. **Сгенерировать SSH ключ на сервере**

```bash
# На сервере
ssh-keygen -t ed25519 -f ~/.ssh/deploy_key -N ""
cat ~/.ssh/deploy_key
# Копировать ПРИВАТНЫЙ ключ
```

2. **Добавить secrets в GitHub**

Перейти на GitHub → Settings → Secrets and variables → Actions → New repository secret

Добавить следующие secrets:

| Секрет | Значение | Пример |
|--------|----------|--------|
| `SERVER_HOST` | IP или домен сервера | `91.210.191.80` |
| `SERVER_USER` | Пользователь на сервере | `deploy` |
| `SERVER_PORT` | SSH порт | `22` |
| `SERVER_SSH_KEY` | Приватный SSH ключ | `-----BEGIN PRIVATE KEY...` |
| `SLACK_WEBHOOK` | (опционально) Slack webhook | `https://hooks.slack.com/...` |

3. **На сервере разрешить публичный ключ**

```bash
# На сервере, от пользователя deploy
mkdir -p ~/.ssh
cat ~/.ssh/deploy_key.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

4. **Сделать скрипт executable**

```bash
cd /app
chmod +x update.sh
git add update.sh
git commit -m "Make update script executable"
git push origin main
```

**После этого:**
- Каждый коммит в `main` автоматически обновляет сервер
- Slack/Email уведомления при успехе или ошибке

---

## 🚀 Как использовать

### Вариант 1: Ручное обновление

```bash
# На сервере
cd /app
./update.sh
```

### Вариант 2: Через гит (автоматическое через GitHub Actions)

```bash
# На своём компьютере
git pull origin main
git add .
git commit -m "Обновление"
git push origin main

# Приложение обновится автоматически на сервере!
# Посмотреть статус: GitHub Actions tab
```

---

## 📋 Что делает update.sh

```
1. Создаёт резервную копию БД
   backup/backup_20260721_143025.sql.gz

2. Получает свежий код
   git fetch origin
   git pull origin main

3. Проверяет изменения
   Показывает что изменилось

4. Если используется Docker
   docker-compose stop web worker
   docker-compose exec web python manage.py migrate
   docker-compose exec web python manage.py collectstatic
   docker-compose up -d web worker

5. Если используется systemd
   sudo systemctl stop cripto-web cripto-worker
   python manage.py migrate
   python manage.py collectstatic
   sudo systemctl start cripto-web cripto-worker

6. Проверяет здоровье
   curl http://localhost:8000/admin/

7. Показывает логи
   docker-compose logs -n 20 web
   или
   journalctl -u cripto-web -n 20

8. Очищает старые бэкапы
   Удаляет бэкапы старше 30 дней
```

---

## ⚠️ Если что-то сломалось

### Откатиться на предыдущую версию

```bash
# На сервере
cd /app

# Посмотреть доступные бэкапы
ls -lh backups/

# Остановить сервисы
docker-compose stop web  # или: sudo systemctl stop cripto-web

# Восстановить БД
docker-compose exec -T postgres psql -U cripto cripto_prod < backups/backup_YYYYMMDD_HHMMSS.sql.gz
# или для systemd:
# psql -U cripto cripto_prod < backups/backup_YYYYMMDD_HHMMSS.sql.gz

# Откатить код
git reset --hard HEAD~1  # Откатиться на 1 коммит назад
# или выберите нужный коммит:
# git log --oneline
# git reset --hard <commit-hash>

# Запустить сервисы
docker-compose up -d web  # или: sudo systemctl start cripto-web

# Проверить логи
docker-compose logs -f web
```

---

## 🔍 Полезные команды

### Проверить статус

```bash
# Docker
docker-compose ps

# systemd
sudo systemctl status cripto-web cripto-worker

# Логи
docker-compose logs -f web
sudo journalctl -u cripto-web -f -n 50
```

### Вручную применить миграции

```bash
# Docker
docker-compose exec web python manage.py migrate --noinput

# systemd
cd /app
source venv313/bin/activate
python manage.py migrate --noinput
```

### Вручную собрать static файлы

```bash
# Docker
docker-compose exec web python manage.py collectstatic --noinput

# systemd
cd /app
source venv313/bin/activate
python manage.py collectstatic --noinput
```

---

## 🔐 Безопасность

✅ Бэкапы БД создаются ДО обновления
✅ Скрипт останавливает сервисы перед обновлением
✅ Если что-то сломается, есть откат
✅ GitHub Actions использует SSH ключи (не пароли)
✅ Логирование всех операций

---

## 📞 Поддержка

Скрипт in реакции:
```bash
./update.sh
```

Логи:
```bash
docker-compose logs -f web
journalctl -u cripto-web -f -n 100
```

Бэкапы:
```bash
ls -lh backups/
```

Откат:
```bash
git reset --hard <commit-hash>
psql -U cripto cripto_prod < backup.sql.gz
```
