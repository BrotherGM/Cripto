"""Обновление справочника торговых пар с биржи (для CLI/cron).

    python manage.py refresh_pairs
    python manage.py refresh_pairs --type SWAP
"""
from django.core.management.base import BaseCommand

from grid.services.instruments import refresh_instruments


class Command(BaseCommand):
    help = "Тянет список инструментов с OKX в локальный справочник пар."

    def add_arguments(self, parser):
        parser.add_argument("--type", default="SPOT", help="Тип инструмента (SPOT/SWAP/…)")

    def handle(self, *args, **opts):
        res = refresh_instruments(opts["type"])
        self.stdout.write(self.style.SUCCESS(res["msg"]))
