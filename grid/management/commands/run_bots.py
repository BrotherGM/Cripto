"""Единый воркер-супервизор всех стратегий.

Крутится постоянно: приводит фактическое состояние стратегий к желаемому
(desired_state), реагирует на исполнения/стоп-лосс, держит heartbeat и
периодически сверяет БД с биржей (отмена осиротевших ордеров). После падения/
перезапуска сам возобновляет работу из БД — состояние всегда синхронно.

Запуск (один экземпляр на всю систему):
    python manage.py run_bots
    python manage.py run_bots --interval 5 --reconcile-every 12
Держать живым: systemd/supervisor (bare-metal) или сервис worker в docker-compose.
"""
import time

from django.core.management.base import BaseCommand
from django.db import connection

from grid.services import supervisor

_LOCK_KEY = 727272  # ключ advisory-lock: гарантирует единственный воркер


class Command(BaseCommand):
    help = "Единый воркер: приводит стратегии к desired_state и сверяет биржу."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=5.0, help="Период тика, сек")
        parser.add_argument("--reconcile-every", type=int, default=12,
                            help="Сверять биржу каждые N тиков (0 — выкл.)")

    def _acquire_lock(self) -> bool:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", [_LOCK_KEY])
            return bool(cur.fetchone()[0])

    def handle(self, *args, **opts):
        if not self._acquire_lock():
            self.stderr.write(self.style.ERROR(
                "Другой воркер уже запущен (advisory-lock занят) — выход."))
            return
        interval = opts["interval"]
        rec_every = opts["reconcile_every"]
        self.stdout.write(self.style.SUCCESS(
            f"Воркер-супервизор запущен. Тик {interval}s, сверка биржи каждые "
            f"{rec_every} тиков. Ctrl+C — выход."))
        i = 0
        try:
            while True:
                i += 1
                do_reconcile = rec_every and (i % rec_every == 0)
                try:
                    supervisor.run_once(reconcile=do_reconcile)
                except Exception as e:  # noqa: BLE001 — воркер не должен падать
                    self.stderr.write(f"Ошибка итерации: {e}")
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nВоркер остановлен пользователем."))
