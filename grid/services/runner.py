"""Управление торговлей из админки: запуск/остановка стратегии.

«Запустить торговлю»:
    1) синхронизировать инструмент и рассчитать уровни (если ещё нет);
    2) разместить начальную сетку ордеров;
    3) поднять фоновый процесс рабочего цикла (manage.py run_grid),
       который отслеживает исполнения и контролирует стоп-лосс.

«Остановить торговлю»:
    1) погасить фоновый процесс цикла;
    2) отменить все активные ордера (cancel-batch) и перевести в «Остановлена».

Фоновый цикл запускается как отдельный detached-процесс (подходит для
локального запуска/демо). PID хранится в стратегии — по нему процесс
останавливается. Для продакшена цикл лучше вынести в системную службу
(systemd/supervisor) или очередь задач.
"""
import os
import signal
import subprocess
import sys

from django.conf import settings
from django.utils import timezone

from grid.models import StrategyStatus
from grid.services.engines import get_engine


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # сигнал 0 — только проверка существования процесса
        return True
    except (OSError, ProcessLookupError):
        return False


def cycle_pids(strategy) -> list[int]:
    """Все живые процессы рабочего цикла этой стратегии (по командной строке).

    Защита от дублей: ловим даже процессы, не записанные в runner_pid
    (например, поднятые при гонке двойного запуска).
    """
    pids = set()
    if strategy.runner_pid and _pid_alive(strategy.runner_pid):
        pids.add(strategy.runner_pid)
    try:
        # ловим и старый (run_grid), и единый (run_strategy) циклы
        out = subprocess.check_output(
            ["pgrep", "-f", f"--strategy {strategy.id} "], text=True
        )
        pids.update(int(p) for p in out.split())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    return sorted(pids)


def _kill(pid: int):
    """Завершает процесс вместе с его группой."""
    for fn in (lambda: os.killpg(os.getpgid(pid), signal.SIGTERM),
               lambda: os.kill(pid, signal.SIGTERM)):
        try:
            fn()
            return
        except (OSError, ProcessLookupError):
            continue


def is_running(strategy) -> bool:
    """Запущен ли хотя бы один процесс рабочего цикла стратегии."""
    return bool(cycle_pids(strategy))


def _spawn_cycle(strategy, interval: float = 10.0) -> int:
    """Запускает единый рабочий цикл manage.py run_strategy отдельным процессом."""
    manage_py = str(settings.BASE_DIR / "manage.py")
    logfile = settings.BASE_DIR / "logs"
    logfile.mkdir(exist_ok=True)
    out = open(logfile / f"run_strategy_{strategy.id}.log", "ab")  # noqa: SIM115
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, manage_py, "run_strategy",
         "--strategy", str(strategy.id), "--interval", str(interval)],
        stdout=out, stderr=out, cwd=str(settings.BASE_DIR),
        start_new_session=True, env=env,
    )
    return proc.pid


def start_trading(strategy, interval: float = 10.0) -> dict:
    """Полный запуск торговли. Возвращает сводку для сообщения в админке."""
    # Защита от дублей: если цикл уже работает — не запускаем второй,
    # а лишние процессы (если есть) схлопываем до одного.
    existing = cycle_pids(strategy)
    if existing and strategy.status == StrategyStatus.RUNNING:
        keep, *extra = existing
        for pid in extra:
            _kill(pid)
        if strategy.runner_pid != keep:
            strategy.runner_pid = keep
            strategy.save(update_fields=["runner_pid", "updated_at"])
        msg = f"Торговля уже запущена (цикл PID {keep})."
        if extra:
            msg += f" Удалены дубликаты циклов: {extra}."
        return {"ok": False, "msg": msg}

    # на всякий случай гасим возможные «осиротевшие» циклы перед стартом
    for pid in existing:
        _kill(pid)

    # 1) стартовые действия под тип стратегии (для сетки — расчёт и размещение)
    engine = get_engine(strategy)
    res = engine.start()

    # 2) поднимаем единый фоновый цикл
    pid = _spawn_cycle(strategy, interval)
    strategy.runner_pid = pid
    strategy.runner_started_at = timezone.now()
    strategy.status = StrategyStatus.RUNNING
    strategy.save(update_fields=["runner_pid", "runner_started_at", "status", "updated_at"])
    engine.log(f"Запущена из админки. {res.get('msg', '')} Цикл PID {pid}.")
    return {"ok": True, "msg": f"{res.get('msg', 'Запущена.')} Рабочий цикл PID {pid}."}


def stop_trading(strategy) -> dict:
    """Останавливает все циклы стратегии и отменяет все ордера."""
    pids = cycle_pids(strategy)
    for pid in pids:
        _kill(pid)

    canceled = get_engine(strategy).stop()  # отмена ордеров + статус STOPPED
    strategy.runner_pid = None
    strategy.runner_started_at = None
    strategy.save(update_fields=["runner_pid", "runner_started_at", "updated_at"])
    msg = f"Торговля остановлена: отменено активных ордеров {canceled}."
    if pids:
        msg += f" Рабочих циклов завершено: {len(pids)}."
    return {"ok": True, "msg": msg}
