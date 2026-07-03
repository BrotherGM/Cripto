"""Управление торговлей из админки: желаемое состояние + один мгновенный тик.

Модель без «отсоединённых» процессов. Кнопки в админке лишь задают намерение
(desired_state) и один раз синхронно прогоняют тик для мгновенной реакции
(разместить/отменить ордера прямо сейчас). Далее непрерывный цикл ведёт единый
воркер `manage.py run_bots`, который постоянно приводит факт к desired_state,
реагирует на исполнения/стоп-лосс и сверяет биржу. Поэтому состояние
БД ↔ биржа не расходится даже после перезапусков.

«Запустить торговлю»  -> desired_state=run  + немедленный тик (setup+размещение).
«Остановить торговлю» -> desired_state=stop + немедленный тик (отмена ордеров).

«Запущена ли» определяется по свежести heartbeat (last_tick_at), а не по PID.
"""
from django.utils import timezone

from grid.models import GridStrategy, StrategyStatus
from grid.services import supervisor

HEARTBEAT_STALE = 60  # сек: после этого «работающая» стратегия считается зависшей (нет воркера)


def is_running(strategy) -> bool:
    """Живой рабочий цикл: статус RUNNING и свежий heartbeat от воркера."""
    if strategy.status != StrategyStatus.RUNNING:
        return False
    lt = strategy.last_tick_at
    return bool(lt and (timezone.now() - lt).total_seconds() < HEARTBEAT_STALE)


def is_stale(strategy) -> bool:
    """Статус RUNNING, но heartbeat протух — воркер не крутит стратегию."""
    if strategy.status != StrategyStatus.RUNNING:
        return False
    lt = strategy.last_tick_at
    return not lt or (timezone.now() - lt).total_seconds() >= HEARTBEAT_STALE


def start_trading(strategy, interval: float = 10.0) -> dict:
    """Задать desired=run и сразу прогнать тик (мгновенный старт)."""
    GridStrategy.objects.filter(pk=strategy.pk).update(desired_state="run")
    supervisor.tick_strategy(strategy)  # немедленно: setup + размещение, статус -> running
    strategy.refresh_from_db()
    if strategy.last_error:
        return {"ok": False, "msg": f"Запуск с ошибкой: {strategy.last_error}"}
    return {"ok": True, "msg": (
        f"Запущена (режим {strategy.get_mode_display()}). "
        f"Статус: {strategy.get_status_display()}. Цикл поддерживает воркер run_bots.")}


def stop_trading(strategy) -> dict:
    """Задать desired=stop и сразу прогнать тик (мгновенная отмена ордеров)."""
    GridStrategy.objects.filter(pk=strategy.pk).update(desired_state="stop")
    supervisor.tick_strategy(strategy)  # немедленно: отмена ордеров, статус -> stopped
    strategy.refresh_from_db()
    return {"ok": True, "msg": (
        f"Остановлена. Статус: {strategy.get_status_display()}."
        + (f" Ошибка: {strategy.last_error}" if strategy.last_error else ""))}
