"""Ядро стратегии сеточной торговли.

Реализует логику из документа:
    * расчёт уровней (арифметика/геометрия, округление до tickSz)   — раздел 2.3
    * размещение начальной сетки (buy ниже / sell выше цены)        — раздел 2.4
    * реакция на исполнение (buy@i -> sell@i+1, sell@i -> buy@i-1)   — раздел 3.2
    * средневзвешенная цена позиции (VWAP)                          — раздел 3
    * штатная остановка (cancel-batch) и аварийный стоп-лосс         — раздел 4
"""
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from grid.models import (
    GridLevel, GridOrder, Position, StrategyLog, Trade,
    GridType, LevelStatus, OrderState, Side, StrategyStatus,
)
from grid.services import okx_client as okx


def _round_to_step(value: Decimal, step: Decimal, rounding=ROUND_DOWN) -> Decimal:
    """Округляет value до ближайшего кратного step."""
    if not step or step <= 0:
        return value
    return (value / step).quantize(Decimal("1"), rounding=rounding) * step


class GridEngine:
    """Операции над одной стратегией."""

    def __init__(self, strategy):
        self.s = strategy

    # --- логирование ---------------------------------------------------------
    def log(self, message: str, level: str = "info"):
        StrategyLog.objects.create(strategy=self.s, level=level, message=message)

    # --- округление с учётом параметров инструмента --------------------------
    def round_price(self, price: Decimal, rounding=ROUND_DOWN) -> Decimal:
        tick = self.s.tick_sz or Decimal("0.00000001")
        return _round_to_step(Decimal(price), tick, rounding)

    def round_size(self, size: Decimal) -> Decimal:
        lot = self.s.lot_sz or Decimal("0.00000001")
        return _round_to_step(Decimal(size), lot, ROUND_DOWN)

    # --- 2.2 параметры инструмента -------------------------------------------
    def sync_instrument(self) -> dict:
        """Подтягивает tickSz/lotSz/minSz с биржи и сохраняет в стратегию."""
        info = okx.get_instrument(self.s.inst_id, self.s.inst_type)
        self.s.tick_sz = Decimal(info["tickSz"])
        self.s.lot_sz = Decimal(info["lotSz"])
        self.s.min_sz = Decimal(info["minSz"])
        self.s.is_demo = okx.is_demo()
        self.s.save(update_fields=["tick_sz", "lot_sz", "min_sz", "is_demo", "updated_at"])
        self.log(f"Параметры инструмента: tickSz={self.s.tick_sz}, "
                 f"lotSz={self.s.lot_sz}, minSz={self.s.min_sz}")
        return info

    # --- 2.3 расчёт цен уровней ----------------------------------------------
    def compute_level_prices(self) -> list[Decimal]:
        """Список цен уровней i=0..N (включительно), округлённых до tickSz."""
        n = self.s.levels
        p_min, p_max = self.s.p_min, self.s.p_max
        prices = []
        if self.s.grid_type == GridType.GEOMETRIC:
            ratio = (p_max / p_min) ** (Decimal(1) / Decimal(n))
            for i in range(n + 1):
                prices.append(self.round_price(p_min * (ratio ** i)))
        else:  # арифметическая
            step = (p_max - p_min) / Decimal(n)
            for i in range(n + 1):
                prices.append(self.round_price(p_min + step * i))
        return prices

    # --- 2.4 построение и размещение сетки -----------------------------------
    @transaction.atomic
    def build_levels(self) -> int:
        """Создаёт уровни сетки. Сторона определяется относительно текущей цены."""
        if self.s.tick_sz is None:
            self.sync_instrument()
        current = Decimal(okx.get_last_price(self.s.inst_id))
        self.s.grid_levels.all().delete()

        prices = self.compute_level_prices()
        created = 0
        for i, price in enumerate(prices):
            side = Side.BUY if price < current else Side.SELL
            GridLevel.objects.create(
                strategy=self.s, index=i, price=price, side=side, status=LevelStatus.FREE,
            )
            created += 1
        Position.objects.get_or_create(strategy=self.s)
        self.s.status = StrategyStatus.READY
        self.s.save(update_fields=["status", "updated_at"])
        self.log(f"Рассчитано {created} уровней (тек. цена {current}, тип {self.s.grid_type}).")
        return created

    def _place_order_for_level(self, level: GridLevel) -> GridOrder:
        """Размещает лимитный ордер для уровня и записывает GridOrder."""
        size = self.round_size(self.s.order_size)
        cl_ord_id = f"g{self.s.id}l{level.index}{uuid.uuid4().hex[:8]}"
        order = GridOrder.objects.create(
            strategy=self.s, level=level, cl_ord_id=cl_ord_id,
            side=level.side, price=level.price, size=size, state=OrderState.PENDING,
        )
        level.status = LevelStatus.PENDING
        level.save(update_fields=["status"])

        try:
            res = okx.place_limit_order(
                inst_id=self.s.inst_id, td_mode=self.s.td_mode, side=level.side,
                price=level.price, size=size, cl_ord_id=cl_ord_id,
            )
        except okx.OkxError as e:
            order.state = OrderState.FAILED
            order.raw = e.raw
            order.save(update_fields=["state", "raw"])
            level.status = LevelStatus.FREE
            level.save(update_fields=["status"])
            self.log(f"Ошибка размещения {level.side} @ {level.price}: {e.msg}", "error")
            raise

        order.ord_id = res.get("ordId", "")
        order.raw = res
        # sCode '0' = принят биржей
        order.state = OrderState.LIVE if str(res.get("sCode")) == "0" else OrderState.FAILED
        order.save(update_fields=["ord_id", "raw", "state"])

        if order.state == OrderState.LIVE:
            level.status = LevelStatus.OPEN
            level.active_order = order
            level.save(update_fields=["status", "active_order"])
        else:
            level.status = LevelStatus.FREE
            level.save(update_fields=["status"])
            self.log(f"Биржа отклонила {level.side} @ {level.price}: "
                     f"{res.get('sMsg')}", "error")
        return order

    def place_initial_grid(self) -> int:
        """Размещает все начальные ордера (buy ниже / sell выше текущей цены)."""
        if not self.s.grid_levels.exists():
            self.build_levels()
        placed = 0
        for level in self.s.grid_levels.filter(status=LevelStatus.FREE):
            try:
                order = self._place_order_for_level(level)
                if order.state == OrderState.LIVE:
                    placed += 1
            except okx.OkxError:
                continue
        self.s.status = StrategyStatus.RUNNING
        self.s.save(update_fields=["status", "updated_at"])
        self.log(f"Начальная сетка размещена: {placed} ордеров активны.")
        return placed

    # --- 3.2 реакция на исполнение -------------------------------------------
    @transaction.atomic
    def on_fill(self, order: GridOrder, fill_price: Decimal, fill_size: Decimal,
                trade_id: str = "", ts=None, fee=Decimal("0"), fee_ccy=""):
        """Обрабатывает исполнение ордера: пишет сделку, VWAP и парный ордер."""
        fill_price, fill_size = Decimal(fill_price), Decimal(fill_size)
        Trade.objects.create(
            strategy=self.s, order=order, trade_id=trade_id, side=order.side,
            fill_price=fill_price, fill_size=fill_size, fee=Decimal(fee or 0),
            fee_ccy=fee_ccy, ts=ts or timezone.now(),
        )
        order.filled_size = (order.filled_size or Decimal("0")) + fill_size
        order.avg_px = fill_price
        order.state = (OrderState.FILLED if order.filled_size >= order.size
                       else OrderState.PARTIALLY_FILLED)
        order.save(update_fields=["filled_size", "avg_px", "state"])

        self._update_vwap(order.side, fill_price, fill_size)

        if order.state != OrderState.FILLED:
            return  # ждём полного исполнения, пара ставится один раз

        level = order.level
        if level:
            level.status = LevelStatus.FILLED
            level.active_order = None
            level.save(update_fields=["status", "active_order"])
            self._place_paired_order(level)

    def _place_paired_order(self, filled_level: GridLevel):
        """buy@i -> sell@i+1 (выше); sell@i -> buy@i-1 (ниже)."""
        if filled_level.side == Side.BUY:
            target_index, new_side = filled_level.index + 1, Side.SELL
        else:
            target_index, new_side = filled_level.index - 1, Side.BUY

        try:
            target = self.s.grid_levels.get(index=target_index)
        except GridLevel.DoesNotExist:
            self.log(f"Нет соседнего уровня {target_index} для пары — край сетки.", "warning")
            return
        if target.status in (LevelStatus.OPEN, LevelStatus.PENDING):
            self.log(f"Уровень {target_index} уже занят ордером — пропуск.", "warning")
            return

        target.side = new_side
        target.status = LevelStatus.FREE
        target.save(update_fields=["side", "status"])
        self._place_order_for_level(target)
        self.log(f"Пара: {filled_level.side}@{filled_level.index} -> "
                 f"{new_side}@{target_index} ({target.price}).")

    # --- 3 VWAP --------------------------------------------------------------
    def _update_vwap(self, side: str, price: Decimal, size: Decimal):
        pos, _ = Position.objects.get_or_create(strategy=self.s)
        if side == Side.BUY:
            new_qty = pos.base_qty + size
            if new_qty > 0:
                pos.avg_price = (pos.avg_price * pos.base_qty + price * size) / new_qty
            pos.base_qty = new_qty
        else:  # продажа: фиксируем прибыль относительно средней цены
            pos.realized_pnl += (price - pos.avg_price) * size
            pos.base_qty -= size
            if pos.base_qty <= 0:
                pos.base_qty = Decimal("0")
                pos.avg_price = Decimal("0")
        pos.save()

    # --- 4.1 штатная остановка -----------------------------------------------
    def stop(self) -> int:
        """Отменяет все активные ордера пакетно и останавливает стратегию."""
        live = list(self.s.orders.filter(state__in=[OrderState.LIVE, OrderState.PARTIALLY_FILLED]))
        canceled = self._cancel_orders(live)
        self.s.status = StrategyStatus.STOPPED
        self.s.save(update_fields=["status", "updated_at"])
        self.log(f"Штатная остановка: отменено {canceled} ордеров.")
        return canceled

    def _cancel_orders(self, orders: list) -> int:
        payload = [{"instId": self.s.inst_id, "ordId": o.ord_id}
                   for o in orders if o.ord_id]
        if payload:
            try:
                okx.cancel_batch_orders(payload)
            except okx.OkxError as e:
                self.log(f"Ошибка пакетной отмены: {e.msg}", "error")
        ids = [o.id for o in orders]
        GridOrder.objects.filter(id__in=ids).update(state=OrderState.CANCELED)
        GridLevel.objects.filter(strategy=self.s, active_order__in=ids).update(
            status=LevelStatus.FREE, active_order=None
        )
        return len(orders)

    # --- 4.2 аварийный выход (stop-loss) -------------------------------------
    def check_stop_loss(self, current_price: Decimal) -> bool:
        """Если цена пробила нижнюю границу — аварийный выход."""
        if not self.s.stop_loss_enabled:
            return False
        if Decimal(current_price) > self.s.effective_stop_loss:
            return False
        self.emergency_exit(Decimal(current_price))
        return True

    def emergency_exit(self, current_price: Decimal):
        """Отмена всех ордеров + закрытие позиции рыночным ордером (раздел 4.2)."""
        live = list(self.s.orders.filter(state__in=[OrderState.LIVE, OrderState.PARTIALLY_FILLED]))
        self._cancel_orders(live)
        pos = getattr(self.s, "position", None)
        if pos and pos.base_qty > 0:
            try:
                size = self.round_size(pos.base_qty)
                cl_ord_id = f"sl{self.s.id}{uuid.uuid4().hex[:8]}"
                okx.trade_api().place_order(
                    instId=self.s.inst_id, tdMode=self.s.td_mode, side=Side.SELL,
                    ordType="market", sz=str(size), clOrdId=cl_ord_id,
                )
                self.log(f"Стоп-лосс: рыночная продажа {size} по ~{current_price}.", "warning")
            except Exception as e:  # noqa: BLE001
                self.log(f"Ошибка стоп-лосс продажи: {e}", "error")
        self.s.status = StrategyStatus.EMERGENCY
        self.s.save(update_fields=["status", "updated_at"])
        self.log(f"АВАРИЙНЫЙ ВЫХОД: цена {current_price} <= стоп {self.s.effective_stop_loss}.",
                 "error")
