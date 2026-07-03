"""Безопасная проверка и накат миграций при старте (для нескольких сервисов).

Проблема: web и worker поднимаются из одного образа и стартуют одновременно —
если оба одновременно запустят `migrate`, миграции конфликтуют (двойное
применение падает с ошибкой). Решение: применяем миграции под Postgres
advisory-lock. Первый сервис захватывает блокировку и мигрирует, второй ждёт
на той же блокировке и затем видит, что применять уже нечего.

Идемпотентно: если незакрытых миграций нет — просто сообщает и выходит.
Запускается из docker/entrypoint.sh; можно вызывать и вручную.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

LOCK_KEY = 947103  # отдельный ключ (не пересекается с воркером run_bots — 727272)


class Command(BaseCommand):
    help = "Проверяет незакрытые миграции и применяет их под advisory-lock (без гонок)."

    def _pending(self):
        """Список незакрытых миграций как [(app_label, name), …]."""
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return [(m.app_label, m.name) for m, _ in executor.migration_plan(targets)]

    def handle(self, *args, **opts):
        # Postgres поддерживает advisory-lock; для sqlite (локальные тесты) —
        # тихо откатываемся к обычному migrate.
        if connection.vendor != "postgresql":
            self.stdout.write("СУБД не PostgreSQL — обычный migrate без блокировки.")
            call_command("migrate", "--noinput")
            return

        self.stdout.write("→ Ожидание блокировки миграций (advisory-lock)…")
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", [LOCK_KEY])
        try:
            pending = self._pending()  # считаем ПОД блокировкой — состояние точное
            if not pending:
                self.stdout.write(self.style.SUCCESS(
                    "  Все миграции уже применены — накат не требуется."))
                return
            self.stdout.write(f"  Незакрытых миграций: {len(pending)}")
            for app_label, name in pending:
                self.stdout.write(f"    • {app_label}.{name}")
            call_command("migrate", "--noinput")
            self.stdout.write(self.style.SUCCESS("  Миграции применены."))
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
