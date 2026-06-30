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


class GridType(models.TextChoices):
    ARITHMETIC = "arithmetic", "Арифметическая (равномерная)"
    GEOMETRIC = "geometric", "Геометрическая (логарифмическая)"


class StrategyStatus(models.TextChoices):
    DRAFT = "draft", "Черновик"
    READY = "ready", "Готова (уровни рассчитаны)"
    RUNNING = "running", "Запущена"
    STOPPED = "stopped", "Остановлена"
    EMERGENCY = "emergency", "Аварийный выход (stop-loss)"


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
    """Конфигурация и состояние одной сеточной стратегии."""

    name = models.CharField("Название", max_length=120, unique=True)
    inst_id = models.CharField("Инструмент (instId)", max_length=40, default="BTC-USDT")
    inst_type = models.CharField("Тип инструмента", max_length=10, default="SPOT")
    td_mode = models.CharField("Режим торговли (tdMode)", max_length=10, default="cash")

    # 2.1 Диапазон сетки
    p_max = models.DecimalField("Верхняя цена (Pmax)", **PRICE)
    p_min = models.DecimalField("Нижняя цена (Pmin)", **PRICE)
    levels = models.PositiveIntegerField("Число уровней (N)", default=10)
    grid_type = models.CharField(
        "Тип сетки", max_length=12, choices=GridType.choices, default=GridType.ARITHMETIC
    )

    # Объём одного ордера (в базовой валюте)
    order_size = models.DecimalField("Объём ордера (база)", **QTY)

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
    is_demo = models.BooleanField("Демо-режим", default=True)

    # Фоновый рабочий цикл (run_grid), запущенный из админки
    runner_pid = models.PositiveIntegerField("PID рабочего цикла", null=True, blank=True)
    runner_started_at = models.DateTimeField("Цикл запущен", null=True, blank=True)

    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Стратегия (сетка)"
        verbose_name_plural = "Стратегии (сетки)"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} [{self.inst_id}] ({self.get_status_display()})"

    def clean(self):
        if self.p_max is not None and self.p_min is not None and self.p_max <= self.p_min:
            raise ValidationError("Pmax должна быть больше Pmin.")
        if self.levels is not None and self.levels < 2:
            raise ValidationError("Число уровней N должно быть не меньше 2.")
        if self.p_min is not None and self.p_min <= 0:
            raise ValidationError("Pmin должна быть положительной.")

    @property
    def effective_stop_loss(self) -> Decimal:
        """Цена стоп-лосса: явная или граница Pmin."""
        return self.stop_loss_price if self.stop_loss_price is not None else self.p_min

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
