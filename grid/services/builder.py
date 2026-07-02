"""Автоматическое создание стратегии по паре.

Указывается только торговая пара (напр. XRP-USDT) и, при желании, несколько
общих настроек. Остальное заполняется автоматически:
    * tickSz/lotSz/minSz    — тянутся с биржи;
    * Pmax/Pmin             — рассчитываются от текущей цены (± range_pct %);
    * объём ордера          — из целевого размера в USDT, с учётом lotSz/minSz;
    * уровни сетки          — рассчитываются сразу (статус «Готова»).
"""
from decimal import Decimal, ROUND_DOWN

from grid.models import GridStrategy, GridType, StrategyStatus
from grid.services import okx_client as okx
from grid.services.grid_engine import GridEngine, _round_to_step


def suggest_params(inst_id, inst_type="SPOT", range_pct=10, order_notional=15) -> dict:
    """Считает параметры стратегии по текущему рынку и характеристикам инструмента."""
    info = okx.get_instrument(inst_id, inst_type)
    tick = Decimal(str(info["tickSz"]))
    lot = Decimal(str(info["lotSz"]))
    min_sz = Decimal(str(info["minSz"]))
    price = Decimal(okx.get_last_price(inst_id))

    r = Decimal(str(range_pct)) / Decimal("100")
    p_min = _round_to_step(price * (Decimal("1") - r), tick)
    p_max = _round_to_step(price * (Decimal("1") + r), tick)

    size = _round_to_step(Decimal(str(order_notional)) / price, lot, ROUND_DOWN)
    if size < min_sz:
        size = min_sz

    return {
        "price": price, "tick": tick, "lot": lot, "min_sz": min_sz,
        "p_min": p_min, "p_max": p_max, "order_size": size,
    }


def create_strategy_for_pair(inst_id, *, inst_type="SPOT", range_pct=10, levels=10,
                             order_notional=15, grid_type=GridType.ARITHMETIC,
                             name=None, build=True) -> dict:
    """Создаёт полностью заполненную стратегию для пары.

    Возвращает {ok, inst_id, strategy?, msg}. Если стратегия для пары уже есть —
    пропускает (чтобы не затирать ваши настройки).
    """
    inst_id = (inst_id or "").strip().upper()
    if not inst_id:
        return {"ok": False, "inst_id": inst_id, "msg": "Пустая пара — пропущено."}

    name = name or f"{inst_id} сетка"
    if GridStrategy.objects.filter(name=name).exists() or \
       GridStrategy.objects.filter(inst_id=inst_id).exists():
        return {"ok": False, "inst_id": inst_id,
                "msg": f"{inst_id}: стратегия уже существует — пропущено."}

    try:
        p = suggest_params(inst_id, inst_type, range_pct, order_notional)
    except okx.OkxError as e:
        return {"ok": False, "inst_id": inst_id, "msg": f"{inst_id}: биржа — {e.msg}"}

    s = GridStrategy.objects.create(
        name=name, inst_id=inst_id, inst_type=inst_type, td_mode="cash",
        p_min=p["p_min"], p_max=p["p_max"], levels=levels, grid_type=grid_type,
        order_size=p["order_size"], stop_loss_enabled=True,
        tick_sz=p["tick"], lot_sz=p["lot"], min_sz=p["min_sz"], is_demo=okx.is_demo(),
    )
    if build:
        GridEngine(s).build_levels()  # рассчитывает уровни, статус -> «Готова»
        s.refresh_from_db()

    return {
        "ok": True, "inst_id": inst_id, "strategy": s,
        "msg": (f"{inst_id}: создана (цена {p['price']}, диапазон {p['p_min']}–{p['p_max']}, "
                f"N={levels}, объём {p['order_size']})."),
    }
