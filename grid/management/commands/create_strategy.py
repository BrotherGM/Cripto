"""Создание стратегий по парам из командной строки (авто-заполнение полей).

Сетка (тип по умолчанию) — параметры считаются автоматически по рынку:
    python manage.py create_strategy XRP-USDT
    python manage.py create_strategy ETH-USDT SOL-USDT --range 8 --levels 12 --notional 20
    python manage.py create_strategy DOGE-USDT --geometric

Другие типы — с параметрами (недостающее дополняется дефолтами по типу):
    python manage.py create_strategy BTC-USDT --type dca
    python manage.py create_strategy ETH-USDT --type trend --params '{"fast":7,"slow":25}'
    python manage.py create_strategy BTC-USDT --type arbitrage --params '{"mid":"BTC","cross":"ETH"}'
"""
import json

from django.core.management.base import BaseCommand, CommandError

from grid.models import GridType, StrategyType
from grid.services.builder import create_strategy_for_pair, create_typed_strategy


class Command(BaseCommand):
    help = "Создаёт стратегии по парам, автоматически заполняя поля (все типы)."

    def add_arguments(self, parser):
        parser.add_argument("pairs", nargs="+", help="Пары, напр. XRP-USDT ETH-USDT")
        parser.add_argument("--type", default="grid", choices=[t.value for t in StrategyType],
                            help="Тип стратегии (grid/dca/trend/scalping/arbitrage)")
        parser.add_argument("--params", default="", help="JSON параметров для не-grid типов")
        parser.add_argument("--range", type=float, default=10, help="Grid: диапазон ±%%")
        parser.add_argument("--levels", type=int, default=10, help="Grid: число уровней N")
        parser.add_argument("--notional", type=float, default=15, help="Grid: объём ордера ~USDT")
        parser.add_argument("--geometric", action="store_true", help="Grid: геометрическая сетка")

    def handle(self, *args, **o):
        params = {}
        if o["params"]:
            try:
                params = json.loads(o["params"])
            except json.JSONDecodeError as e:
                raise CommandError(f"--params: невалидный JSON — {e}")

        for pair in o["pairs"]:
            try:
                if o["type"] == StrategyType.GRID:
                    gt = GridType.GEOMETRIC if o["geometric"] else GridType.ARITHMETIC
                    res = create_strategy_for_pair(
                        pair, range_pct=o["range"], levels=o["levels"],
                        order_notional=o["notional"], grid_type=gt)
                else:
                    res = create_typed_strategy(pair, o["type"], params)
                style = self.style.SUCCESS if res["ok"] else self.style.WARNING
                self.stdout.write(style(res["msg"]))
            except Exception as e:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"{pair}: ошибка — {e}"))
