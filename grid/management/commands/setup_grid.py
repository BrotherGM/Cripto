"""Настройка сетки: синхронизация инструмента, расчёт уровней, (опц.) размещение.

Пример:
    python manage.py setup_grid --strategy "BTC сетка" --place
"""
from django.core.management.base import BaseCommand, CommandError

from grid.models import GridStrategy
from grid.services.grid_engine import GridEngine


class Command(BaseCommand):
    help = "Синхронизирует инструмент, рассчитывает уровни и опционально размещает сетку."

    def add_arguments(self, parser):
        parser.add_argument("--strategy", required=True, help="ID или название стратегии")
        parser.add_argument("--place", action="store_true", help="Сразу разместить ордера")

    def handle(self, *args, **opts):
        s = _resolve(opts["strategy"])
        engine = GridEngine(s)

        self.stdout.write("Синхронизация параметров инструмента…")
        engine.sync_instrument()
        self.stdout.write(self.style.SUCCESS(
            f"  tickSz={s.tick_sz}, lotSz={s.lot_sz}, minSz={s.min_sz}"
        ))

        self.stdout.write("Расчёт уровней сетки…")
        n = engine.build_levels()
        self.stdout.write(self.style.SUCCESS(f"  уровней: {n}"))

        if opts["place"]:
            self.stdout.write("Размещение начальной сетки…")
            placed = engine.place_initial_grid()
            self.stdout.write(self.style.SUCCESS(f"  размещено ордеров: {placed}"))
        else:
            self.stdout.write("Готово. Для размещения добавьте флаг --place.")


def _resolve(ref: str) -> GridStrategy:
    qs = GridStrategy.objects.all()
    s = (qs.filter(pk=ref).first() if ref.isdigit() else None) or qs.filter(name=ref).first()
    if not s:
        raise CommandError(f"Стратегия не найдена: {ref}")
    return s
