FROM python:3.13-slim

# Не пишем .pyc, вывод сразу в лог
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# procps -> pgrep (нужен runner'у для управления фоновым циклом торговли)
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Точка входа: миграции + сбор статики, затем команда из CMD
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "cripto.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
