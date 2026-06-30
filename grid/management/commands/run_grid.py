"""Рабочий цикл стратегии (раздел 3 документа).

Отслеживает исполнение ордеров и реагирует:
    buy@i  исполнен -> sell@i+1 (выше)
    sell@i исполнен -> buy@i-1  (ниже)
а также контролирует аварийный стоп-лосс (раздел 4.2).

Здесь используется REST-опрос состояний ордеров (надёжно и просто для
демо/теста). В проде тот же GridEngine.on_fill() можно вызывать из
WebSocket-консьюмера приватного канала `orders` — логика реакции идентична.

Пример:
    python manage.py run_grid --strategy "BTC сетка" --interval 5
    python manage.py run_grid --strategy 1 --once
"""
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from grid.models import GridStrategy, GridOrder, OrderState, StrategyStatus
from grid.services import okx_client as okx
from grid.services.grid_engine import GridEngine


def _to_dt(ms: str):
    if not ms:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=dt_timezone.utc)


class Command(BaseCommand):
    help = "Запускает рабочий цикл сеточной стратегии (отслеживание исполнений + стоп-лосс)."

    def add_arguments(self, parser):
        parser.add_argument("--strategy", required=True, help="ID или название стратегии")
        parser.add_argument("--interval", type=float, default=5.0, help="Период опроса, сек")
        parser.add_argument("--once", action="store_true", help="Один проход и выход")

    def handle(self, *args, **opts):
        s = _resolve(opts["strategy"])
        engine = GridEngine(s)
        interval = opts["interval"]

        self.stdout.write(self.style.SUCCESS(
            f"Рабочий цикл [{s.name} / {s.inst_id}] запущен. "
            f"Опрос каждые {interval}s. Ctrl+C — выход."
        ))
        try:
            while True:
                stop = self._tick(s, engine)
                if opts["once"] or stop:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nОстановлено пользователем (ордера не отменены)."))

    def _tick(self, s: GridStrategy, engine: GridEngine) -> bool:
        """Один проход цикла. Возвращает True, если нужно завершить."""
        s.refresh_from_db()
        if s.status != StrategyStatus.RUNNING:
            self.stdout.write(f"Статус стратегии: {s.get_status_display()} — цикл завершён.")
            return True

        # 4.2 контроль стоп-лосса
        try:
            current = Decimal(okx.get_last_price(s.inst_id))
        except okx.OkxError as e:
            self.stderr.write(f"Не удалось получить цену: {e}")
            return False
        if engine.check_stop_loss(current):
            self.stdout.write(self.style.ERROR(f"СТОП-ЛОСС сработал при цене {current}."))
            return True

        # 3.1 отслеживание исполнения активных ордеров
        live = s.orders.filter(state__in=[OrderState.LIVE, OrderState.PARTIALLY_FILLED])
        for order in live:
            self._sync_order(engine, s, order)
        return False

    def _sync_order(self, engine: GridEngine, s: GridStrategy, order: GridOrder):
        if not order.ord_id:
            return
        try:
            data = okx.get_order(s.inst_id, ord_id=order.ord_id)
        except okx.OkxError as e:
            self.stderr.write(f"  ордер {order.ord_id}: ошибка запроса — {e}")
            return
        if not data:
            return

        state = data.get("state")
        acc_fill = Decimal(data.get("accFillSz") or "0")
        delta = acc_fill - (order.filled_size or Decimal("0"))

        if delta > 0:
            price = data.get("avgPx") or data.get("fillPx") or order.price
            engine.on_fill(
                order, fill_price=price, fill_size=delta,
                trade_id=data.get("tradeId", ""), ts=_to_dt(data.get("uTime")),
                fee=Decimal(data.get("fee") or "0"), fee_ccy=data.get("feeCcy", ""),
            )
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {order.side} @ {order.price}: исполнено +{delta} (состояние {state})."
            ))
        elif state == "canceled":
            order.state = OrderState.CANCELED
            order.save(update_fields=["state"])


def _resolve(ref: str) -> GridStrategy:
    qs = GridStrategy.objects.all()
    s = (qs.filter(pk=ref).first() if ref.isdigit() else None) or qs.filter(name=ref).first()
    if not s:
        raise CommandError(f"Стратегия не найдена: {ref}")
    return s
