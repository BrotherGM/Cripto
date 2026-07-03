"""Единый рабочий цикл для стратегии любого типа.

Диспетчеризует по strategy_type к нужному движку (grid/dca/trend/scalping/
arbitrage) и в цикле вызывает engine.tick(). Тот сам решает, что делать на
каждом проходе и когда завершиться (True — остановиться).

    python manage.py run_strategy --strategy "BTC DCA" --interval 30
    python manage.py run_strategy --strategy 8 --once
"""
import time

from django.core.management.base import BaseCommand, CommandError

from grid.models import GridStrategy
from grid.services import okx_client as okx
from grid.services import risk
from grid.services.engines import get_engine


class Command(BaseCommand):
    help = "Запускает рабочий цикл стратегии (любого типа) через её движок."

    def add_arguments(self, parser):
        parser.add_argument("--strategy", required=True, help="ID или название стратегии")
        parser.add_argument("--interval", type=float, default=10.0, help="Период, сек")
        parser.add_argument("--once", action="store_true", help="Один проход и выход")

    def handle(self, *args, **opts):
        s = _resolve(opts["strategy"])
        okx.set_mode(s.mode)  # весь цикл работает в режиме стратегии (demo/live)
        engine = get_engine(s)
        interval = opts["interval"]
        self.stdout.write(self.style.SUCCESS(
            f"Цикл [{s.get_strategy_type_display()} · {s.name} · {s.get_mode_display()}] "
            f"запущен. Период {interval}s. Ctrl+C — выход."
        ))
        try:
            while True:
                # Килл-свитч: дневной убыток / просадка -> стоп всех стратегий
                breached, reason = risk.account_breach()
                if breached:
                    self.stdout.write(self.style.ERROR(
                        f"KILL-SWITCH: {reason} — аварийная остановка всех стратегий."))
                    risk.stop_all(reason)
                    break
                stop = engine.tick()
                if opts["once"] or stop:
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nОстановлено пользователем."))


def _resolve(ref: str) -> GridStrategy:
    qs = GridStrategy.objects.all()
    s = (qs.filter(pk=ref).first() if ref.isdigit() else None) or qs.filter(name=ref).first()
    if not s:
        raise CommandError(f"Стратегия не найдена: {ref}")
    return s
