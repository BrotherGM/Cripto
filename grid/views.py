"""Дашборд с торговыми графиками.

Страницы:
    /dashboard/                 — список стратегий
    /dashboard/<id>/            — графики по стратегии (свечи+сетка, PnL)
    /dashboard/<id>/data.json   — данные для графиков (для авто-обновления)
"""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404

from grid.models import GridStrategy, Side
from grid.services import okx_client as okx


def _f(value) -> float:
    return float(value) if value is not None else None


def _candles(inst_id: str, bar: str = "1H", limit: int = 200) -> list[dict]:
    """Свечи с биржи (от старых к новым). При ошибке — пустой список."""
    try:
        rows = okx.unwrap(okx.market_api().get_candlesticks(inst_id, bar=bar, limit=str(limit)))
    except Exception:  # noqa: BLE001 — график должен рендериться и без биржи
        return []
    out = []
    for r in reversed(rows):  # OKX отдаёт новейшие первыми
        ts = datetime.fromtimestamp(int(r[0]) / 1000, tz=dt_timezone.utc)
        out.append({
            "t": ts.isoformat(),
            "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]),
        })
    return out


def _pnl_series(strategy: GridStrategy) -> list[dict]:
    """Кумулятивный реализованный PnL по сделкам (та же логика, что в движке)."""
    base = Decimal("0")
    avg = Decimal("0")
    pnl = Decimal("0")
    series = []
    for t in strategy.trades.order_by("ts"):
        if t.side == Side.BUY:
            new_base = base + t.fill_size
            if new_base > 0:
                avg = (avg * base + t.fill_price * t.fill_size) / new_base
            base = new_base
        else:
            pnl += (t.fill_price - avg) * t.fill_size
            base -= t.fill_size
            if base <= 0:
                base = Decimal("0")
                avg = Decimal("0")
        series.append({"t": t.ts.isoformat(), "pnl": float(pnl)})
    return series


def build_chart_data(strategy: GridStrategy, bar: str = "1H") -> dict:
    """Полный набор данных для графиков по стратегии."""
    levels = [
        {"index": lv.index, "price": _f(lv.price), "side": lv.side, "status": lv.status}
        for lv in strategy.grid_levels.order_by("index")
    ]
    trades = [
        {"t": t.ts.isoformat(), "side": t.side, "price": _f(t.fill_price), "size": _f(t.fill_size)}
        for t in strategy.trades.order_by("ts")
    ]
    orders = [
        {
            "index": o.level.index if o.level else None,
            "side": o.side,
            "side_display": o.get_side_display(),
            "price": _f(o.price),
            "size": _f(o.size),
            "filled": _f(o.filled_size),
            "state": o.state,
            "state_display": o.get_state_display(),
            "ord_id": o.ord_id,
            "created": o.created_at.isoformat(),
        }
        for o in strategy.orders.select_related("level").order_by("-created_at")
    ]
    try:
        current = float(okx.get_last_price(strategy.inst_id))
    except Exception:  # noqa: BLE001
        current = None

    pos = getattr(strategy, "position", None)
    return {
        "strategy": {
            "id": strategy.id,
            "name": strategy.name,
            "inst_id": strategy.inst_id,
            "status": strategy.get_status_display(),
            "p_min": _f(strategy.p_min),
            "p_max": _f(strategy.p_max),
            "stop_loss": _f(strategy.effective_stop_loss),
            "current_price": current,
        },
        "candles": _candles(strategy.inst_id, bar=bar),
        "levels": levels,
        "trades": trades,
        "orders": orders,
        "pnl": _pnl_series(strategy),
        "stats": {
            "orders_live": strategy.orders.filter(state="live").count(),
            "orders_filled": strategy.orders.filter(state="filled").count(),
            "trades_buy": strategy.trades.filter(side=Side.BUY).count(),
            "trades_sell": strategy.trades.filter(side=Side.SELL).count(),
            "position_qty": _f(pos.base_qty) if pos else 0,
            "position_avg": _f(pos.avg_price) if pos else 0,
            "realized_pnl": _f(pos.realized_pnl) if pos else 0,
        },
    }


@staff_member_required
def dashboard_index(request):
    strategies = GridStrategy.objects.all()
    return render(request, "grid/dashboard.html", {"strategies": strategies})


@staff_member_required
def strategy_chart(request, pk: int):
    strategy = get_object_or_404(GridStrategy, pk=pk)
    bar = request.GET.get("bar", "1H")
    return render(request, "grid/strategy_chart.html", {"strategy": strategy, "bar": bar})


@staff_member_required
def strategy_chart_data(request, pk: int):
    strategy = get_object_or_404(GridStrategy, pk=pk)
    bar = request.GET.get("bar", "1H")
    return JsonResponse(build_chart_data(strategy, bar=bar))
