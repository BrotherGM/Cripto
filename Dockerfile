FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

# Установить системные зависимости
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копировать requirements
COPY requirements.txt .

# Установить Python зависимости
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Копировать код приложения
COPY . .

# Создать пользователя для приложения
RUN useradd -m -u 1000 cripto && chown -R cripto:cripto /app

# Переключиться на пользователя
USER cripto

# Собрать статические файлы
RUN python manage.py collectstatic --noinput --settings=cripto.settings || true

# Точка входа: применить миграции и запустить gunicorn
ENTRYPOINT ["sh", "-c"]
CMD ["python manage.py migrate --noinput && gunicorn --bind 0.0.0.0:8077 --workers 4 --timeout 120 cripto.wsgi:application"]
