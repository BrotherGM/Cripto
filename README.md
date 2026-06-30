# Cripto — Grid Trading (Django + PostgreSQL + OKX)

Бот сеточной торговли криптовалютой по логике из `grid_strategy.pdf`.
Архитектура: **Python / Django**, БД — **PostgreSQL** (`Cripto`), управление — через **админку Django**.
По умолчанию работает в **демо-режиме OKX** (`OKX_FLAG=1`, тестовые данные).

## Структура

```
cripto/                 # настройки Django-проекта (settings, urls)
grid/
  models.py             # GridStrategy, GridLevel, GridOrder, Trade, Position, StrategyLog
  admin.py              # админка + действия (синхронизация, расчёт, размещение, стоп)
  services/
    okx_client.py       # REST-обёртки OKX SDK (инструменты, ордера, цены)
    grid_engine.py      # ядро стратегии: уровни, размещение, реакция на fill, VWAP, стоп-лосс
  management/commands/
    setup_grid.py       # настройка сетки из CLI
    run_grid.py         # рабочий цикл (отслеживание исполнений + стоп-лосс)
.env                    # ключи OKX и параметры БД
```

## Запуск в Docker (для сервера)

Нужны только Docker и Docker Compose. PostgreSQL поднимается контейнером.

```bash
git clone git@github.com:BrotherGM/Cripto.git
cd Cripto

# настройки окружения
cp .env.example .env
nano .env        # впишите ключи OKX (демо: OKX_FLAG=1) и при желании пароль БД

# сборка и запуск (Django + PostgreSQL)
docker compose up -d --build
```

При старте контейнер автоматически: ждёт БД → применяет миграции → собирает статику →
создаёт суперпользователя (из `DJANGO_SUPERUSER_*` в `.env`).

- Админка: `http://<сервер>:8000/admin/`
- Дашборд с графиками: `http://<сервер>:8000/dashboard/`

Полезное:
```bash
docker compose logs -f web        # логи приложения
docker compose exec web python manage.py createsuperuser   # ещё один админ
docker compose down               # остановить (данные БД сохранятся в volume pgdata)
```

> Запуск/остановка торговли — кнопками в админке. Фоновый рабочий цикл стартует
> внутри web-контейнера; его логи — в `/app/logs/run_grid_<id>.log` контейнера.

## Локальный запуск (без Docker)

```bash
source venv313/bin/activate
pip install -r requirements.txt

# БД Cripto и миграции
python manage.py migrate
python manage.py createsuperuser   # уже создан: admin / admin12345

python manage.py runserver 0.0.0.0:8030
```

Админка: http://127.0.0.1:8030/admin/  (логин `admin`, пароль `admin12345`)

## Как пользоваться (соответствие документу)

1. **Создать стратегию** в админке: инструмент, `Pmax`/`Pmin`, число уровней `N`, тип сетки, объём ордера.
2. Действия над стратегией (выпадающий список «Action»):
   - 🔌 **Проверить подключение к OKX**
   - 📐 **Синхронизировать параметры инструмента** — tickSz / lotSz / minSz (раздел 2.2)
   - 🧮 **Рассчитать уровни сетки** — арифметика/геометрия, округление до tickSz (раздел 2.3)
   - 🚀 **Разместить начальную сетку** — buy ниже / sell выше цены (раздел 2.4)
   - 🛑 **Остановить** — пакетная отмена всех ордеров (раздел 4.1)
3. **Рабочий цикл** (раздел 3) — отдельным процессом:
   ```bash
   python manage.py run_grid --strategy "Название стратегии" --interval 5
   ```
   На исполнение `buy@i` ставит `sell@i+1`, на `sell@i` — `buy@i-1`, считает VWAP,
   контролирует стоп-лосс при пробое `Pmin` (раздел 4.2).

   Быстрая настройка из CLI:
   ```bash
   python manage.py setup_grid --strategy "Название" --place
   ```

## Графики торговли (дашборд)

После `runserver` доступен дашборд (вход — под учёткой админки):

- `http://127.0.0.1:8030/dashboard/` — список стратегий
- `http://127.0.0.1:8030/dashboard/<id>/` — графики по стратегии:
  - свечи инструмента + уровни сетки (зелёные buy / красные sell) + метки исполненных сделок + линия стоп-лосса;
  - кумулятивный реализованный PnL;
  - карточки: цена, PnL, позиция/VWAP, активные ордера, число сделок.
- `http://127.0.0.1:8030/dashboard/<id>/data.json` — данные для графиков (свечи/уровни/сделки/PnL), авто-обновление каждые 10 с.

Графики на Plotly (CDN), переключатель таймфрейма (1m…1D).

## Заметки

- Демо OKX использует тот же REST-хост; SDK сам выставляет заголовок `x-simulated-trading` по `OKX_FLAG`.
- `run_grid` сейчас опрашивает состояния ордеров по REST. Для минимальной задержки
  в проде тот же `GridEngine.on_fill()` можно вызывать из WebSocket-консьюмера
  приватного канала `orders` — логика реакции идентична.
