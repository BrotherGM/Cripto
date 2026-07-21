"""Модели предметной области сеточной торговли (Grid Trading).

Соответствие документу:
    GridStrategy — настройка (раздел 2): диапазон Pmax/Pmin, число уровней N,
                   тип сетки, параметры инструмента (tickSz/lotSz/minSz), стоп-лосс.
    GridLevel    — уровни сетки (занятые/свободные) из рабочего цикла (раздел 3).
    GridOrder    — лимитные ордера, размещённые на бирже.
    Trade        — исполнения (fill events) для расчёта средневзвешенной цены.
    Position     — агрегированное состояние позиции (VWAP, раздел 3).
    StrategyLog  — журнал действий бота (для наблюдения через админку).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


# Денежные/объёмные поля: большой запас точности под крипту.
PRICE = dict(max_digits=30, decimal_places=12)
QTY = dict(max_digits=30, decimal_places=12)


class StrategyType(models.TextChoices):
    GRID = "grid", "Сетка (Grid)"
    DCA = "dca", "Усреднение (DCA)"
    TREND = "trend", "Следование за трендом (Trend)"
    ARBITRAGE = "arbitrage", "Арбитраж (Arbitrage)"
    SCALPING = "scalping", "Скальпинг (Scalping)"


class TradingMode(models.TextChoices):
    DEMO = "demo", "Демо"
    LIVE = "live", "Реал"


class MarginMode(models.TextChoices):
    CASH = "cash", "Наличный / спот (cash)"
    ISOLATED = "isolated", "Изолированная маржа (isolated)"
    CROSS = "cross", "Кросс-маржа (cross)"


class GridType(models.TextChoices):
    ARITHMETIC = "arithmetic", "Арифметическая (равномерная)"
    GEOMETRIC = "geometric", "Геометрическая (логарифмическая)"


class StrategyStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    READY = "ready", "Готова"
    RUNNING = "running", "Запущена"
    STOPPED = "stopped", "Остановлена"
    EMERGENCY = "emergency", "Аварийный выход (stop-loss)"
    ARCHIVED = "archived", "Архив"


class Side(models.TextChoices):
    BUY = "buy", "Покупка"
    SELL = "sell", "Продажа"


class LevelStatus(models.TextChoices):
    FREE = "free", "Свободен"
    PENDING = "pending", "Размещается"
    OPEN = "open", "Открыт ордер"
    FILLED = "filled", "Исполнен"


class OrderState(models.TextChoices):
    PENDING = "pending", "Отправляется"
    LIVE = "live", "Активен"
    PARTIALLY_FILLED = "partially_filled", "Частично исполнен"
    FILLED = "filled", "Исполнен"
    CANCELED = "canceled", "Отменён"
    FAILED = "failed", "Ошибка"


class GridStrategy(models.Model):
    """Конфигурация и состояние торговой стратегии.

    Изначально модель описывала только сетку (Grid); теперь это универсальная
    модель для всех типов стратегий (см. strategy_type). Общие поля — вверху,
    специфичные для сетки — в блоке ниже, а параметры остальных типов (DCA,
    Trend, Arbitrage, Scalping) хранятся в JSON-поле params.
    """

    name = models.CharField("Название", max_length=120, unique=True)
    strategy_type = models.CharField(
        "Тип стратегии", max_length=12, choices=StrategyType.choices,
        default=StrategyType.GRID,
    )
    mode = models.CharField(
        "Режим", max_length=5, choices=TradingMode.choices, default=TradingMode.DEMO,
        help_text="demo — тестовая торговля; live — реальная (боевые ключи).")
    inst_id = models.CharField("Инструмент (instId)", max_length=40, default="BTC-USDT")
    inst_type = models.CharField("Тип инструмента", max_length=10, default="SPOT")
    td_mode = models.CharField(
        "Режим маржи (tdMode)", max_length=10, choices=MarginMode.choices,
        default=MarginMode.CASH,
        help_text="cash — спот без плеча; isolated/cross — маржа с плечом (для деривативов).")
    leverage = models.PositiveIntegerField(
        "Плечо", default=1,
        help_text="1 = без плеча (спот). Действует только с маржой (isolated/cross). "
                  "С плечом ×N риск и экспозиция в N раз больше маржи, появляется ликвидация.")

    # Параметры стратегий, кроме сетки (DCA/Trend/Arbitrage/Scalping) — в JSON.
    params = models.JSONField("Параметры стратегии", default=dict, blank=True)

    # 2.1 Диапазон сетки (только для strategy_type=grid)
    p_max = models.DecimalField("Верхняя цена (Pmax)", null=True, blank=True, **PRICE)
    p_min = models.DecimalField("Нижняя цена (Pmin)", null=True, blank=True, **PRICE)
    levels = models.PositiveIntegerField("Число уровней (N)", default=10, null=True, blank=True)
    grid_type = models.CharField(
        "Тип сетки", max_length=12, choices=GridType.choices, default=GridType.ARITHMETIC
    )

    # Объём одного ордера сетки (в базовой валюте)
    order_size = models.DecimalField("Объём ордера (база)", null=True, blank=True, **QTY)

    # 2.2 Параметры инструмента (подтягиваются с биржи)
    tick_sz = models.DecimalField("Шаг цены (tickSz)", null=True, blank=True, **PRICE)
    lot_sz = models.DecimalField("Шаг объёма (lotSz)", null=True, blank=True, **QTY)
    min_sz = models.DecimalField("Мин. объём (minSz)", null=True, blank=True, **QTY)

    # 4.2 Аварийный выход
    stop_loss_enabled = models.BooleanField("Стоп-лосс включён", default=True)
    stop_loss_price = models.DecimalField(
        "Цена стоп-лосса", null=True, blank=True,
        help_text="Если пусто — используется Pmin.", **PRICE,
    )

    status = models.CharField(
        "Статус", max_length=12, choices=StrategyStatus.choices, default=StrategyStatus.DRAFT
    )
    # Желаемое состояние (управляет пользователь) — воркер приводит факт к нему.
    desired_state = models.CharField(
        "Желаемое состояние", max_length=4,
        choices=[("run", "Запустить"), ("stop", "Остановить")], default="stop")
    is_demo = models.BooleanField("Демо-режим", default=True)

    # Heartbeat единого воркера (заполняется на каждом тике)
    last_tick_at = models.DateTimeField("Последний тик", null=True, blank=True)
    last_error = models.CharField("Последняя ошибка", max_length=300, blank=True)

    # Фоновый рабочий цикл (устаревшее, от прежней модели «процесс на стратегию»)
    runner_pid = models.PositiveIntegerField("PID рабочего цикла", null=True, blank=True)
    runner_started_at = models.DateTimeField("Цикл запущен", null=True, blank=True)

    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Стратегия"
        verbose_name_plural = "Стратегии"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} [{self.get_strategy_type_display()} · {self.inst_id}]"

    def clean(self):
        # Валидация полей сетки — только для стратегии типа «grid».
        if self.strategy_type == StrategyType.GRID:
            if self.p_max is None or self.p_min is None:
                raise ValidationError("Для сетки нужны Pmax и Pmin.")
            if self.p_max <= self.p_min:
                raise ValidationError("Pmax должна быть больше Pmin.")
            if self.levels is None or self.levels < 2:
                raise ValidationError("Число уровней N должно быть не меньше 2.")
            if self.p_min <= 0:
                raise ValidationError("Pmin должна быть положительной.")
            if self.order_size is None or self.order_size <= 0:
                raise ValidationError("Объём ордера сетки должен быть положительным.")

    @property
    def effective_stop_loss(self) -> Decimal:
        """Цена стоп-лосса: явная или граница Pmin (для сетки)."""
        return self.stop_loss_price if self.stop_loss_price is not None else self.p_min

    def param(self, key, default=None):
        """Удобный доступ к params с дефолтом."""
        return (self.params or {}).get(key, default)

    @property
    def is_active(self) -> bool:
        return self.status == StrategyStatus.RUNNING


class GridLevel(models.Model):
    """Уровень сетки. Хранит, занят ли уровень ордером (раздел 3, п.3)."""

    strategy = models.ForeignKey(
        GridStrategy, related_name="grid_levels", on_delete=models.CASCADE,
        verbose_name="Стратегия",
    )
    index = models.IntegerField("Индекс уровня (i)")
    price = models.DecimalField("Цена уровня", **PRICE)
    side = models.CharField("Сторона", max_length=4, choices=Side.choices)
    status = models.CharField(
        "Состояние", max_length=8, choices=LevelStatus.choices, default=LevelStatus.FREE
    )
    active_order = models.ForeignKey(
        "GridOrder", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", verbose_name="Активный ордер",
    )

    class Meta:
        verbose_name = "Уровень сетки"
        verbose_name_plural = "Уровни сетки"
        ordering = ["strategy", "index"]
        constraints = [
            models.UniqueConstraint(
                fields=["strategy", "index"], name="uniq_strategy_level_index"
            )
        ]

    def __str__(self):
        return f"#{self.index} @ {self.price} ({self.get_side_display()})"


class GridOrder(models.Model):
    """Лимитный ордер сетки, размещённый на бирже OKX."""

    strategy = models.ForeignKey(
        GridStrategy, related_name="orders", on_delete=models.CASCADE,
        verbose_name="Стратегия",
    )
    level = models.ForeignKey(
        GridLevel, null=True, blank=True, related_name="orders",
        on_delete=models.SET_NULL, verbose_name="Уровень",
    )
    cl_ord_id = models.CharField("Клиентский ID (clOrdId)", max_length=64, db_index=True)
    ord_id = models.CharField("ID ордера OKX (ordId)", max_length=64, blank=True, db_index=True)

    side = models.CharField("Сторона", max_length=4, choices=Side.choices)
    price = models.DecimalField("Цена", **PRICE)
    size = models.DecimalField("Объём", **QTY)

    state = models.CharField(
        "Состояние", max_length=16, choices=OrderState.choices, default=OrderState.PENDING
    )
    filled_size = models.DecimalField("Исполнено", default=Decimal("0"), **QTY)
    avg_px = models.DecimalField("Средняя цена исполн.", null=True, blank=True, **PRICE)
    raw = models.JSONField("Сырой ответ OKX", default=dict, blank=True)

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Ордер сетки"
        verbose_name_plural = "Ордера сетки"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["strategy", "cl_ord_id"], name="uniq_strategy_clordid"
            )
        ]

    def __str__(self):
        return f"{self.get_side_display()} {self.size} @ {self.price} [{self.get_state_display()}]"


class Trade(models.Model):
    """Исполнение (fill). Используется для расчёта VWAP (раздел 3)."""

    strategy = models.ForeignKey(
        GridStrategy, related_name="trades", on_delete=models.CASCADE,
        verbose_name="Стратегия",
    )
    order = models.ForeignKey(
        GridOrder, null=True, blank=True, related_name="trades",
        on_delete=models.SET_NULL, verbose_name="Ордер",
    )
    trade_id = models.CharField("ID сделки (tradeId)", max_length=64, blank=True, db_index=True)
    side = models.CharField("Сторона", max_length=4, choices=Side.choices)
    fill_price = models.DecimalField("Цена исполнения", **PRICE)
    fill_size = models.DecimalField("Объём исполнения", **QTY)
    fee = models.DecimalField("Комиссия", default=Decimal("0"), **QTY)
    fee_ccy = models.CharField("Валюта комиссии", max_length=20, blank=True)
    ts = models.DateTimeField("Время сделки")
    created_at = models.DateTimeField("Записана", auto_now_add=True)

    class Meta:
        verbose_name = "Сделка (исполнение)"
        verbose_name_plural = "Сделки (исполнения)"
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.get_side_display()} {self.fill_size} @ {self.fill_price}"


class Position(models.Model):
    """Агрегированное состояние позиции: VWAP и реализованная прибыль."""

    strategy = models.OneToOneField(
        GridStrategy, related_name="position", on_delete=models.CASCADE,
        verbose_name="Стратегия",
    )
    base_qty = models.DecimalField("Объём позиции (база)", default=Decimal("0"), **QTY)
    avg_price = models.DecimalField("Средневзвешенная цена (VWAP)", default=Decimal("0"), **PRICE)
    realized_pnl = models.DecimalField("Реализованная прибыль", default=Decimal("0"), **PRICE)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Позиция (VWAP)"
        verbose_name_plural = "Позиции (VWAP)"

    def __str__(self):
        return f"{self.strategy.name}: {self.base_qty} @ {self.avg_price}"


class StrategyLog(models.Model):
    """Журнал действий бота для наблюдения через админку."""

    LEVELS = [("info", "INFO"), ("warning", "WARNING"), ("error", "ERROR")]

    strategy = models.ForeignKey(
        GridStrategy, related_name="logs", on_delete=models.CASCADE,
        verbose_name="Стратегия",
    )
    level = models.CharField("Уровень", max_length=10, choices=LEVELS, default="info")
    message = models.TextField("Сообщение")
    created_at = models.DateTimeField("Время", auto_now_add=True)

    class Meta:
        verbose_name = "Лог стратегии"
        verbose_name_plural = "Логи стратегии"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.level}] {self.message[:60]}"


class Instrument(models.Model):
    """Справочник торговых пар биржи (кэш public/instruments).

    Обновляется кнопкой «Обновить пары с биржи»; используется как источник
    выбора пар в мастере создания стратегии.
    """

    inst_id = models.CharField("Инструмент (instId)", max_length=40, unique=True)
    inst_type = models.CharField("Тип", max_length=10, default="SPOT")
    base_ccy = models.CharField("Базовая валюта", max_length=20, blank=True)
    quote_ccy = models.CharField("Котируемая валюта", max_length=20, blank=True)
    tick_sz = models.DecimalField("Шаг цены", null=True, blank=True, **PRICE)
    lot_sz = models.DecimalField("Шаг объёма", null=True, blank=True, **QTY)
    min_sz = models.DecimalField("Мин. объём", null=True, blank=True, **QTY)
    state = models.CharField("Состояние (биржа)", max_length=20, blank=True)
    active = models.BooleanField(
        "Active", default=True,
        help_text="Показывать пару в мастере создания стратегии.")
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Инструмент (пара)"
        verbose_name_plural = "Инструменты (пары)"
        ordering = ["inst_id"]

    def __str__(self):
        return self.inst_id


class Document(models.Model):
    """Фиктивная модель (без таблицы) — пункт «Документы» в группе Grid.

    Реальных данных не хранит: страница читает PDF-файлы из папки docs/ на диске,
    поэтому новые файлы появляются автоматически.
    """

    class Meta:
        managed = False          # таблицы в БД нет
        default_permissions = ()  # без add/change/delete
        verbose_name = "Документ"
        verbose_name_plural = "Документы"


class Service(models.Model):
    """Фиктивная модель (без таблицы) — раздел «Сервис (API)».

    Данных не хранит: страницы «Демо»/«Реал» выполняют read-only запросы к
    соответствующему API OKX (баланс, конфигурация, ордера, инструменты, тикеры…).
    """

    class Meta:
        managed = False
        default_permissions = ()
        verbose_name = "Сервис (API)"
        verbose_name_plural = "Сервис (API)"


class RiskSettings(models.Model):
    """Глобальные риск-лимиты (синглтон, pk=1). Раздел 10 документа Cryptobot."""

    enabled = models.BooleanField("Риск-контроль включён", default=True)
    max_position_per_pair = models.DecimalField(
        "Макс. позиция на пару, USDT", null=True, blank=True, **PRICE,
        help_text="Потолок вложенного в одну пару (позиция + активные buy-ордера).")
    max_total_exposure = models.DecimalField(
        "Макс. общая экспозиция, USDT", null=True, blank=True, **PRICE,
        help_text="Суммарный потолок вложенного по всем стратегиям.")
    daily_loss_limit = models.DecimalField(
        "Дневной лимит убытка, USDT", null=True, blank=True, **PRICE,
        help_text="При падении эквити за день на эту сумму — аварийная остановка всех.")
    max_drawdown_pct = models.DecimalField(
        "Макс. просадка, %", null=True, blank=True, max_digits=6, decimal_places=2,
        help_text="При просадке эквити от пика на этот % — аварийная остановка всех.")
    blacklist = models.TextField(
        "Чёрный список", blank=True,
        help_text="Монеты или пары через запятую/пробел (напр. DOGE, SHIB-USDT) — торговля запрещена.")
    fee_pct = models.DecimalField(
        "Комиссия (для проверки шага), %", default=Decimal("0.1"),
        max_digits=6, decimal_places=4)
    updated_at = models.DateTimeField("Обновлены", auto_now=True)

    class Meta:
        verbose_name = "Риск-настройки"
        verbose_name_plural = "Риск-настройки"

    def __str__(self):
        return "Риск-настройки"

    def save(self, *args, **kwargs):
        self.pk = 1  # синглтон
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        # Удаляем дубли (синглтон должен быть только один)
        try:
            cls.objects.exclude(pk=1).delete()
        except Exception:
            pass  # Таблица может ещё не существовать или быть в состоянии восстановления
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EquitySnapshot(models.Model):
    """Снимок общей эквити аккаунта (для дневного убытка и просадки)."""

    ts = models.DateTimeField("Время", auto_now_add=True, db_index=True)
    equity = models.DecimalField("Эквити, USDT", **PRICE)

    class Meta:
        verbose_name = "Снимок эквити"
        verbose_name_plural = "Снимки эквити"
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M} — {self.equity}"


class WorkerStatus(models.Model):
    """Статус воркера (heartbeat и статистика)."""

    last_heartbeat = models.DateTimeField("Последний heartbeat", auto_now=True)
    strategies_count = models.IntegerField("Количество стратегий", default=0)
    running_count = models.IntegerField("Запущено стратегий", default=0)
    stopped_count = models.IntegerField("Остановлено стратегий", default=0)
    orders_processed = models.IntegerField("Ордеров обработано", default=0)
    cycles_completed = models.BigIntegerField("Циклов завершено", default=0)
    last_error = models.TextField("Последняя ошибка", blank=True, default="")
    is_running = models.BooleanField("Воркер работает", default=False)

    class Meta:
        verbose_name = "Статус воркера"
        verbose_name_plural = "Статус воркера"

    def __str__(self):
        status = "🟢 Работает" if self.is_running else "🔴 Остановлен"
        return f"{status} — {self.strategies_count} стратегий ({self.running_count} работает)"
