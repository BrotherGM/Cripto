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

from grid.models import GridStrategy, WorkerStatus
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

    def _update_worker_status(self, error_msg=""):
        """Обновляет статус воркера в БД."""
        try:
            from django.utils import timezone
            strategies = list(GridStrategy.objects.values_list('id', 'status'))
            total = len(strategies)
            running = sum(1 for _, status in strategies if status == "running")
            stopped = total - running

            ws, created = WorkerStatus.objects.get_or_create(pk=1)
            ws.is_running = True
            ws.strategies_count = total
            ws.running_count = running
            ws.stopped_count = stopped
            ws.cycles_completed = ws.cycles_completed + 1
            ws.last_heartbeat = timezone.now()
            if error_msg:
                ws.last_error = error_msg[:500]
            else:
                ws.last_error = ""
            ws.save(update_fields=["is_running", "strategies_count", "running_count",
                                   "stopped_count", "cycles_completed", "last_error", "last_heartbeat"])
        except Exception:
            pass  # Не падаем если не получилось обновить статус

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

        # Инициализируем WorkerStatus
        self._update_worker_status()

        i = 0
        try:
            while True:
                i += 1
                do_reconcile = rec_every and (i % rec_every == 0)
                try:
                    supervisor.run_once(reconcile=do_reconcile)
                    self._update_worker_status()
                except Exception as e:  # noqa: BLE001 — воркер не должен падать
                    error_text = str(e)[:200]
                    self.stderr.write(f"Ошибка итерации: {e}")
                    self._update_worker_status(error_text)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nВоркер остановлен пользователем."))
