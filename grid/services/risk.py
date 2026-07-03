"""Риск-менеджмент: глобальные лимиты, kill-switch, проверка комиссии.

Реализует раздел 10 документа Cryptobot:
    * лимит на пару и суммарная экспозиция      -> allow_buy()
    * чёрный список монет                        -> is_blacklisted()
    * дневной лимит убытка и макс. просадка       -> account_breach() -> stop_all()
    * проверка шага прибыли против комиссии       -> fee_step_warnings()
"""
from decimal import Decimal

from django.db.models import F, Sum, DecimalField
from django.utils import timezone

from grid.models import (
    RiskSettings, EquitySnapshot, GridStrategy, GridOrder, Position,
    StrategyStatus, StrategyType,
)
from grid.services import okx_client as okx

_ACTIVE = ["live", "partially_filled"]


def settings() -> RiskSettings:
    return RiskSettings.load()


# --- чёрный список -----------------------------------------------------------
def _blacklist(cfg):
    return {s.strip().upper() for s in (cfg.blacklist or "").replace(",", " ").split()
            if s.strip()}


def is_blacklisted(inst_id, cfg=None) -> bool:
    cfg = cfg or settings()
    bl = _blacklist(cfg)
    if not bl:
        return False
    inst = (inst_id or "").upper()
    base = inst.split("-")[0]
    return inst in bl or base in bl


# --- экспозиция (вложенный капитал) ------------------------------------------
def _sum_notional(order_qs, pos_qs):
    orders = order_qs.aggregate(
        v=Sum(F("price") * F("size"), output_field=DecimalField()))["v"] or Decimal("0")
    positions = pos_qs.aggregate(
        v=Sum(F("base_qty") * F("avg_price"), output_field=DecimalField()))["v"] or Decimal("0")
    return orders + positions


def pair_exposure(inst_id) -> Decimal:
    """Вложено в пару: стоимость позиции + активные buy-ордера."""
    return _sum_notional(
        GridOrder.objects.filter(strategy__inst_id=inst_id, side="buy", state__in=_ACTIVE),
        Position.objects.filter(strategy__inst_id=inst_id, base_qty__gt=0),
    )


def total_exposure() -> Decimal:
    """Суммарно вложено по всем парам."""
    return _sum_notional(
        GridOrder.objects.filter(side="buy", state__in=_ACTIVE),
        Position.objects.filter(base_qty__gt=0),
    )


def allow_buy(strategy, quote_amount) -> tuple[bool, str]:
    """Разрешена ли покупка на quote_amount USDT? (blacklist / лимиты)."""
    cfg = settings()
    if not cfg.enabled:
        return True, ""
    q = Decimal(str(quote_amount or 0))
    if is_blacklisted(strategy.inst_id, cfg):
        return False, f"{strategy.inst_id} в чёрном списке"
    if cfg.max_position_per_pair and pair_exposure(strategy.inst_id) + q > cfg.max_position_per_pair:
        return False, f"лимит на пару {cfg.max_position_per_pair} USDT превышен"
    if cfg.max_total_exposure and total_exposure() + q > cfg.max_total_exposure:
        return False, f"лимит общей экспозиции {cfg.max_total_exposure} USDT превышен"
    return True, ""


# --- эквити, дневной убыток, просадка ----------------------------------------
def record_equity(min_interval=60):
    """Снимок общей эквити аккаунта (не чаще раза в min_interval секунд)."""
    last = EquitySnapshot.objects.first()
    if last and (timezone.now() - last.ts).total_seconds() < min_interval:
        return last
    try:
        eq = Decimal(okx.unwrap(okx.account_api().get_account_balance())[0].get("totalEq") or 0)
    except Exception:  # noqa: BLE001
        return last
    return EquitySnapshot.objects.create(equity=eq)


def account_breach() -> tuple[bool, str]:
    """Проверка дневного убытка и просадки. True + причина, если пробой."""
    cfg = settings()
    if not cfg.enabled or not (cfg.daily_loss_limit or cfg.max_drawdown_pct):
        return False, ""
    snap = record_equity()
    if not snap:
        return False, ""
    cur = snap.equity

    if cfg.daily_loss_limit:
        day0 = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        base = (EquitySnapshot.objects.filter(ts__gte=day0).order_by("ts").first()
                or EquitySnapshot.objects.filter(ts__lt=day0).order_by("-ts").first())
        if base:
            loss = base.equity - cur
            if loss >= cfg.daily_loss_limit:
                return True, f"дневной убыток {loss:.2f} ≥ лимита {cfg.daily_loss_limit} USDT"

    if cfg.max_drawdown_pct:
        peak = EquitySnapshot.objects.order_by("-equity").first()
        if peak and peak.equity > 0:
            dd = (peak.equity - cur) / peak.equity * 100
            if dd >= cfg.max_drawdown_pct:
                return True, f"просадка {dd:.1f}% ≥ лимита {cfg.max_drawdown_pct}%"
    return False, ""


# --- kill-switch -------------------------------------------------------------
def stop_all(reason="") -> int:
    """Аварийно останавливает все запущенные стратегии."""
    from grid.services import runner
    from grid.models import StrategyLog
    stopped = 0
    for s in GridStrategy.objects.filter(status=StrategyStatus.RUNNING):
        try:
            runner.stop_trading(s)
            if reason:
                StrategyLog.objects.create(strategy=s, level="error",
                                           message=f"KILL-SWITCH: {reason}")
            stopped += 1
        except Exception:  # noqa: BLE001
            pass
    return stopped


# --- проверка шага прибыли против комиссии -----------------------------------
def fee_step_warnings(strategy) -> list[str]:
    """Предупреждения, если шаг прибыли меньше удвоенной комиссии (вход+выход)."""
    cfg = settings()
    double_fee = Decimal(str(cfg.fee_pct)) * 2  # % на вход и выход
    out = []
    if strategy.strategy_type == StrategyType.GRID:
        if strategy.p_max and strategy.p_min and strategy.levels:
            step = (strategy.p_max - strategy.p_min) / strategy.levels
            mid = (strategy.p_max + strategy.p_min) / 2
            step_pct = (step / mid * 100) if mid else Decimal("0")
            if step_pct < double_fee:
                out.append(f"Шаг сетки {step_pct:.3f}% меньше удвоенной комиссии "
                           f"{double_fee}% — торговля может идти в убыток.")
    else:
        tp = strategy.param("take_profit_pct")
        if tp is None:
            tp = strategy.param("target_pct")
        if tp is not None and Decimal(str(tp)) < double_fee:
            out.append(f"Take-profit {tp}% меньше удвоенной комиссии {double_fee}% — "
                       f"торговля может идти в убыток.")
    return out
