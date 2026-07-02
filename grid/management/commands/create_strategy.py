"""Создание стратегий по парам из командной строки (авто-заполнение полей).

Примеры:
    python manage.py create_strategy XRP-USDT
    python manage.py create_strategy ETH-USDT SOL-USDT --range 8 --levels 12 --notional 20
    python manage.py create_strategy DOGE-USDT --geometric
"""
from django.core.management.base import BaseCommand

from grid.models import GridType
from grid.services.builder import create_strategy_for_pair


class Command(BaseCommand):
    help = "Создаёт стратегии по указанным парам, автоматически заполняя все поля."

    def add_arguments(self, parser):
        parser.add_argument("pairs", nargs="+", help="Пары, напр. XRP-USDT ETH-USDT")
        parser.add_argument("--range", type=float, default=10, help="Диапазон ±%% от цены")
        parser.add_argument("--levels", type=int, default=10, help="Число уровней N")
        parser.add_argument("--notional", type=float, default=15, help="Объём ордера, ~USDT")
        parser.add_argument("--geometric", action="store_true", help="Геометрическая сетка")

    def handle(self, *args, **o):
        gt = GridType.GEOMETRIC if o["geometric"] else GridType.ARITHMETIC
        for pair in o["pairs"]:
            try:
                res = create_strategy_for_pair(
                    pair, range_pct=o["range"], levels=o["levels"],
                    order_notional=o["notional"], grid_type=gt,
                )
                style = self.style.SUCCESS if res["ok"] else self.style.WARNING
                self.stdout.write(style(res["msg"]))
            except Exception as e:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"{pair}: ошибка — {e}"))
