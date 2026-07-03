"""Супервизор: приведение факта к желаемому состоянию + сверка с биржей.

Модель: пользователь задаёт desired_state (run/stop) у стратегии, а единый
воркер (manage.py run_bots) на каждом тике приводит фактическое состояние к
желаемому и обновляет heartbeat (last_tick_at). Плюс периодически сверяет БД с
биржей: отменяет осиротевшие ордера и помечает пропавшие. Так состояние
БД ↔ процесс ↔ биржа всегда сходится, даже после падений/перезапусков.
"""
from decimal import Decimal
from datetime import datetime, timezone as dt_tz

from django.utils import timezone

from grid.models import GridStrategy, GridOrder, OrderState, StrategyStatus
from grid.services import okx_client as okx
from grid.services import risk
from grid.services.engines import get_engine

_ACTIVE = [OrderState.LIVE, OrderState.PARTIALLY_FILLED]
_RESUMABLE = [StrategyStatus.DRAFT, StrategyStatus.READY, StrategyStatus.STOPPED]


def _touch(pk, **fields):
    GridStrategy.objects.filter(pk=pk).update(**fields)


def tick_strategy(s: GridStrategy):
    """Один шаг: привести факт к desired_state и обновить heartbeat."""
    s.refresh_from_db()
    okx.set_mode(s.mode)
    err = ""
    try:
        if s.desired_state == "run":
            if s.status == StrategyStatus.RUNNING:
                stopped = get_engine(s).tick()          # реакция на исполнения/стоп-лосс
                if stopped:
                    s.refresh_from_db()
                    if s.status != StrategyStatus.RUNNING:  # стратегия сама завершилась
                        _touch(s.pk, desired_state="stop")
            elif s.status in _RESUMABLE:
                get_engine(s).start()                    # setup + размещение, статус -> running
            elif s.status == StrategyStatus.EMERGENCY:
                _touch(s.pk, desired_state="stop")       # после аварии не перезапускаем
        elif s.desired_state == "stop" and s.status == StrategyStatus.RUNNING:
            get_engine(s).stop()                         # отмена ордеров, статус -> stopped
    except Exception as e:  # noqa: BLE001
        err = str(e)[:300]
    _touch(s.pk, last_tick_at=timezone.now(), last_error=err)


def reconcile_exchange() -> dict:
    """Сверка с биржей: отмена осиротевших ордеров, фиксация пропавших DB-ордеров."""
    canceled_orphans = 0
    fixed = 0
    modes = set(GridStrategy.objects.values_list("mode", flat=True)) or {"demo"}
    seen_accounts = set()
    for m in modes:
        okx.set_mode(m)
        cfg_key = okx._cfg()["API_KEY"]  # dedupe одинаковых аккаунтов (demo==live сейчас)
        if cfg_key in seen_accounts:
            continue
        seen_accounts.add(cfg_key)
        try:
            ex = okx.unwrap(okx.trade_api().get_order_list())
        except okx.OkxError:
            continue
        db_live = set(GridOrder.objects.filter(state__in=_ACTIVE)
                      .exclude(ord_id="").values_list("ord_id", flat=True))
        ex_ids = {o["ordId"] for o in ex}

        # 1) осиротевшие на бирже (не отслеживаются как live в БД) -> отменяем (кроме market)
        orphans = [{"instId": o["instId"], "ordId": o["ordId"]} for o in ex
                   if o["ordId"] not in db_live and o.get("ordType") != "market"]
        if orphans:
            try:
                res = okx.cancel_batch_orders(orphans)
                canceled_orphans += sum(1 for r in res if str(r.get("sCode")) == "0")
            except okx.OkxError:
                pass

        # 2) DB live-ордера, которых уже нет на бирже -> исполнены/отменены
        for o in GridOrder.objects.filter(state__in=_ACTIVE).exclude(ord_id="").select_related("strategy"):
            if o.ord_id in ex_ids:
                continue
            try:
                data = okx.get_order(o.strategy.inst_id, ord_id=o.ord_id)
            except okx.OkxError:
                data = None
            state = (data or {}).get("state")
            o.state = OrderState.FILLED if state == "filled" else OrderState.CANCELED
            o.save(update_fields=["state"])
            fixed += 1
    return {"canceled_orphans": canceled_orphans, "fixed_orders": fixed}


def reconcile_now() -> dict:
    """Одноразовая полная сверка: привести все стратегии к desired + сверить биржу."""
    for s in GridStrategy.objects.all():
        tick_strategy(s)
    ex = reconcile_exchange()
    return ex


def run_once(reconcile: bool = False) -> None:
    """Одна итерация воркера: kill-switch, тик всех стратегий, опц. сверка биржи."""
    okx.set_mode("demo")  # риск-эквити считаем по аккаунту (demo==live сейчас)
    breached, reason = risk.account_breach()
    if breached:
        for pk in GridStrategy.objects.filter(desired_state="run").values_list("pk", flat=True):
            _touch(pk, desired_state="stop", last_error=f"KILL-SWITCH: {reason}")

    for s in GridStrategy.objects.all():
        tick_strategy(s)

    if reconcile:
        reconcile_exchange()
