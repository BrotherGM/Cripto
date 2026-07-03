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
    grid_engine.py      # ядро сетки: уровни, размещение, реакция на fill, VWAP, стоп-лосс
    engines.py          # движки DCA/Trend/Scalping/Arbitrage + get_engine()
    supervisor.py       # приведение факта к desired_state + сверка БД⇔биржа
    runner.py           # кнопки админки -> desired_state + мгновенный тик
    risk.py             # глобальные лимиты, kill-switch, проверка комиссии
  management/commands/
    setup_grid.py       # настройка сетки из CLI
    run_bots.py         # ЕДИНЫЙ воркер-супервизор всех стратегий (advisory-lock)
.env                    # ключи OKX и параметры БД
```

## Запуск в Docker (для сервера)

В Docker поднимается **только приложение** (Django/gunicorn) на порту **8077**.
**PostgreSQL уже установлен на сервере.** Контейнер работает в сети хоста
(`network_mode: host`), поэтому подключается к Postgres по `localhost` — так же,
как обычное приложение на сервере. Перенастраивать Postgres не нужно.

**Подготовка БД на сервере** (один раз):
```bash
sudo -u postgres createdb Cripto      # создать пустую БД (таблицы создаст миграция)
```

**Запуск приложения:**
```bash
git clone git@github.com:BrotherGM/Cripto.git
cd Cripto

cp .env.example .env
nano .env        # ключи OKX (демо: OKX_FLAG=1) + DB_USER/DB_PASSWORD вашего Postgres
                 # DB_HOST=localhost, DB_NAME=Cripto

docker compose up -d --build
```

> `network_mode: host` работает на Linux-сервере. На macOS (Docker Desktop) сеть
> хоста не поддерживается — для локального теста используйте Postgres в контейнере.

При старте контейнер автоматически: ждёт БД → **проверяет и накатывает нужные
миграции** (`manage.py migrate_safe`) → собирает статику → создаёт суперпользователя
(из `DJANGO_SUPERUSER_*` в `.env`).

> **Миграции без гонок.** `web` и `worker` поднимаются из одного образа
> одновременно, поэтому оба вызывают `migrate_safe`, который берёт Postgres
> advisory-lock: первый сервис применяет незакрытые миграции, второй ждёт и затем
> видит, что применять нечего. Статику и суперпользователя создаёт только `web`
> (у `worker` задан `APP_ROLE=worker`). Команду можно запускать и вручную:
> `python manage.py migrate_safe`.

- Админка: `http://<сервер>:8077/admin/`
- Дашборд с графиками: `http://<сервер>:8077/dashboard/`

Полезное:
```bash
docker compose logs -f web        # логи приложения
docker compose exec web python manage.py createsuperuser   # ещё один админ
docker compose down               # остановить приложение (БД на сервере не трогается)
```

> Если `host.docker.internal` не резолвится (старый Docker на Linux) — альтернатива:
> добавить в сервис `web` строку `network_mode: "host"` (тогда `DB_HOST=localhost`,
> а порт публикуется самим gunicorn). Для большинства серверов достаточно варианта
> с `host.docker.internal` выше.

> Запуск/остановка торговли — кнопками в админке (они лишь задают желаемое
> состояние и делают один мгновенный тик). Непрерывный цикл ведёт отдельный
> сервис **`worker`** (`manage.py run_bots`) — он поднимается вместе с `web`
> в `docker compose up`. Логи воркера: `docker compose logs -f worker`.

## Воркер-супервизор (почему нет рассинхрона)

Раньше на каждую стратегию поднимался свой «отсоединённый» процесс — при падении/
перезапуске веб такие процессы могли осиротеть, а статус в БД разъезжался с реальным
состоянием на бирже. Теперь модель другая — **желаемое состояние + единый воркер**:

- у стратегии есть поле **`desired_state`** (`run`/`stop`) — им управляют кнопки в админке;
- единый сервис **`run_bots`** в цикле приводит факт к желаемому: `run` и не запущена →
  `start()`; `run` и запущена → `tick()` (реакция на исполнения/стоп-лосс) + heartbeat
  `last_tick_at`; `stop` и запущена → `stop()` (отмена ордеров);
- периодически идёт **сверка с биржей** (`reconcile`): осиротевшие ордера на бирже
  отменяются, пропавшие DB-ордера помечаются исполненными/отменёнными;
- **advisory-lock** в Postgres гарантирует единственный экземпляр воркера;
- «живость» стратегии в админке определяется по свежести heartbeat, а не по PID:
  `● работает` / `⚠ завис (нет воркера)` / `◍ ожидает` / `○ остановлен`;
- kill-switch (просадка/дневной убыток) переводит все стратегии в `desired=stop`.

Кнопка **«🔄 Синхронизировать»** (на стратегии) и действие **«🔄 Синхронизировать с
биржей»** (в списке) в любой момент вручную сводят БД ↔ биржу к согласованному виду.

**Bare-metal (systemd)** — держать воркер живым как службу:
```ini
# /etc/systemd/system/cripto-worker.service
[Unit]
Description=Cripto trading supervisor (run_bots)
After=network.target postgresql.service

[Service]
WorkingDirectory=/opt/Cripto
ExecStart=/opt/Cripto/venv313/bin/python manage.py run_bots --interval 5 --reconcile-every 12
Restart=always
RestartSec=5
EnvironmentFile=/opt/Cripto/.env

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now cripto-worker
sudo systemctl status cripto-worker
journalctl -u cripto-worker -f
```
В Docker воркер уже описан сервисом `worker` в `docker-compose.yml` — отдельная
настройка не нужна.

## Локальный запуск (без Docker)

```bash
source venv313/bin/activate
pip install -r requirements.txt

# БД Cripto и миграции
python manage.py migrate
python manage.py createsuperuser   # уже создан: admin / admin12345

python manage.py runserver 0.0.0.0:8030

# в отдельном терминале — единый воркер-супервизор (ведёт все торговые циклы):
python manage.py run_bots --interval 5 --reconcile-every 12
```

Админка: http://127.0.0.1:8030/admin/  (логин `admin`, пароль `admin12345`)

> Без запущенного `run_bots` кнопки в админке разместят/отменят ордера один раз, но
> непрерывной реакции на исполнения не будет — в списке стратегия покажет `⚠ завис`.

## Как пользоваться (соответствие документу)

1. **Создать стратегию** в админке: инструмент, `Pmax`/`Pmin`, число уровней `N`, тип сетки, объём ордера.
2. Действия над стратегией (выпадающий список «Action»):
   - 🔌 **Проверить подключение к OKX**
   - 📐 **Синхронизировать параметры инструмента** — tickSz / lotSz / minSz (раздел 2.2)
   - 🧮 **Рассчитать уровни сетки** — арифметика/геометрия, округление до tickSz (раздел 2.3)
   - 🚀 **Разместить начальную сетку** — buy ниже / sell выше цены (раздел 2.4)
   - 🛑 **Остановить** — пакетная отмена всех ордеров (раздел 4.1)
3. **Рабочий цикл** (раздел 3) ведёт единый воркер-супервизор — запускать один на систему:
   ```bash
   python manage.py run_bots --interval 5 --reconcile-every 12
   ```
   На исполнение `buy@i` ставит `sell@i+1`, на `sell@i` — `buy@i-1`, считает VWAP,
   контролирует стоп-лосс при пробое `Pmin` (раздел 4.2), сверяет БД с биржей.
   Управление торговлей отдельной стратегии — кнопками в админке (задают `desired_state`).

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
- `run_bots` опрашивает состояния ордеров по REST. Для минимальной задержки в проде
  тот же `GridEngine.on_fill()` можно вызывать из WebSocket-консьюмера приватного
  канала `orders` — логика реакции идентична.
- Единственность воркера гарантирует `pg_try_advisory_lock` — второй `run_bots`
  просто выйдет с сообщением, не мешая первому.
