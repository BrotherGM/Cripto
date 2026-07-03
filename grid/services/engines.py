"""Движки торговых стратегий (кроме сетки).

Каркас: BaseEngine — общая механика (рыночные ордера, учёт позиции/VWAP,
состояние, стоп), плюс движки по стратегиям из документа Cryptobot:

    DcaEngine       — усреднение стоимости (по расписанию или на падении)
    TrendEngine     — следование за трендом (пересечение скользящих средних + RSI)
    ScalpingEngine  — быстрые сделки на малом take-profit
    ArbitrageEngine — треугольный арбитраж (детектор + опциональное исполнение)

Все движки реализуют единый интерфейс: start() / tick() / stop().
Диспетчер get_engine(strategy) возвращает нужный движок по strategy.strategy_type
(для «grid» — GridEngine из grid_engine.py).

Демо-оговорка: реальные исполнения возможны только на ликвидных парах (BTC/ETH).
На «тонких» демо-инструментах рыночные ордера могут не исполниться.
"""
import time
import uuid
from decimal import Decimal, ROUND_DOWN

from django.utils import timezone

from grid.models import (
    GridOrder, Trade, Position, StrategyLog,
    Side, OrderState, StrategyStatus,
)
from grid.services import okx_client as okx
from grid.services import risk
from grid.services.grid_engine import _round_to_step


def _d(x) -> Decimal:
    return Decimal(str(x))


# =========================================================================
#  Индикаторы (чистый Python, без внешних зависимостей)
# =========================================================================
def sma(values, period):
    """Простая скользящая средняя последних period значений."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    """Индекс относительной силы (RSI) по последним значениям."""
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(-period, 0):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# =========================================================================
#  Базовый движок
# =========================================================================
class BaseEngine:
    """Общая механика для рыночных стратегий."""

    def __init__(self, strategy):
        self.s = strategy
        self._specs = {}

    # --- логирование и параметры --------------------------------------------
    def log(self, message, level="info"):
        StrategyLog.objects.create(strategy=self.s, level=level, message=message)

    def p(self, key, default=None):
        return (self.s.params or {}).get(key, default)

    # --- runtime-состояние (в params["_state"]) ------------------------------
    def state(self, key, default=None):
        return (self.s.params or {}).get("_state", {}).get(key, default)

    def save_state(self, **kwargs):
        params = dict(self.s.params or {})
        st = dict(params.get("_state", {}))
        st.update(kwargs)
        params["_state"] = st
        self.s.params = params
        self.s.save(update_fields=["params", "updated_at"])

    # --- рыночные данные и характеристики инструмента ------------------------
    def specs(self, inst_id=None):
        inst = inst_id or self.s.inst_id
        if inst not in self._specs:
            self._specs[inst] = okx.get_instrument(inst, self.s.inst_type)
        return self._specs[inst]

    def price(self, inst_id=None):
        return _d(okx.get_last_price(inst_id or self.s.inst_id))

    def ticker(self, inst_id=None):
        return okx.unwrap(okx.market_api().get_ticker(inst_id or self.s.inst_id))[0]

    def closes(self, inst_id=None, bar="1H", limit=200):
        """Список цен закрытия свечей (от старых к новым)."""
        rows = okx.unwrap(okx.market_api().get_candlesticks(
            inst_id or self.s.inst_id, bar=bar, limit=str(limit)))
        return [float(r[4]) for r in reversed(rows)]

    def round_lot(self, size, inst_id=None):
        lot = _d(self.specs(inst_id)["lotSz"])
        return _round_to_step(_d(size), lot, ROUND_DOWN)

    def min_sz(self, inst_id=None):
        return _d(self.specs(inst_id)["minSz"])

    # --- позиция и VWAP ------------------------------------------------------
    def position(self):
        pos, _ = Position.objects.get_or_create(strategy=self.s)
        return pos

    def _update_position(self, side, price, size):
        pos = self.position()
        if side == Side.BUY:
            new_qty = pos.base_qty + size
            if new_qty > 0:
                pos.avg_price = (pos.avg_price * pos.base_qty + price * size) / new_qty
            pos.base_qty = new_qty
        else:
            closing = min(size, pos.base_qty) if pos.base_qty > 0 else Decimal("0")
            if closing > 0 and pos.avg_price > 0:
                pos.realized_pnl += (price - pos.avg_price) * closing
            pos.base_qty -= size
            if pos.base_qty <= 0:
                pos.base_qty = Decimal("0")
                pos.avg_price = Decimal("0")
        pos.save()

    # --- рыночный ордер ------------------------------------------------------
    def place_market(self, side, *, quote_amount=None, base_amount=None, inst_id=None):
        """Рыночный ордер. Для покупки — quote_amount (USDT), для продажи —
        base_amount (базовая валюта). Возвращает {'size','price'} или None."""
        inst = inst_id or self.s.inst_id
        # Риск-контроль: ограничиваем только покупки (продажа снижает экспозицию)
        if side == Side.BUY:
            q = quote_amount
            if q is None and base_amount is not None:
                try:
                    q = base_amount * self.price(inst)
                except okx.OkxError:
                    q = 0
            allowed, reason = risk.allow_buy(self.s, q)
            if not allowed:
                self.log(f"Риск: покупка {inst} отклонена — {reason}", "warning")
                return None
        cl = f"{self.s.strategy_type[:3]}{self.s.id}{uuid.uuid4().hex[:8]}"
        kwargs = dict(instId=inst, tdMode=self.s.td_mode, side=side,
                      ordType="market", clOrdId=cl)
        if base_amount is not None:
            base_amount = self.round_lot(base_amount, inst)
            kwargs["sz"] = str(base_amount)
            kwargs["tgtCcy"] = "base_ccy"
        else:
            kwargs["sz"] = str(quote_amount)  # market buy: sz в котируемой (USDT)

        order = GridOrder.objects.create(
            strategy=self.s, cl_ord_id=cl, side=side, price=Decimal("0"),
            size=_d(base_amount or quote_amount or 0), state=OrderState.PENDING)
        try:
            res = okx.unwrap(okx.trade_api().place_order(**kwargs))[0]
        except okx.OkxError as e:
            order.state = OrderState.FAILED
            order.raw = e.raw
            order.save(update_fields=["state", "raw"])
            self.log(f"Ошибка {side} {inst}: {e.msg}", "error")
            return None
        if str(res.get("sCode")) != "0":
            order.state = OrderState.FAILED
            order.raw = res
            order.save(update_fields=["state", "raw"])
            self.log(f"Биржа отклонила {side} {inst}: {res.get('sMsg')}", "error")
            return None
        order.ord_id = res.get("ordId", "")
        order.raw = res
        order.save(update_fields=["ord_id", "raw"])
        return self._finalize_fill(order, inst)

    def _finalize_fill(self, order, inst):
        """Дожидается исполнения рыночного ордера и записывает сделку/позицию."""
        data = {}
        for _ in range(6):
            try:
                data = okx.get_order(inst, ord_id=order.ord_id)
            except okx.OkxError:
                data = {}
            if data and _d(data.get("accFillSz") or 0) > 0:
                break
            time.sleep(0.5)
        acc = _d(data.get("accFillSz") or 0)
        if acc <= 0:
            order.state = OrderState.LIVE
            order.save(update_fields=["state"])
            self.log(f"{order.get_side_display()} {inst}: не исполнено "
                     f"(нет ликвидности?)", "warning")
            return None
        avg = _d(data.get("avgPx") or data.get("fillPx") or 0)
        order.price = avg
        order.size = acc
        order.filled_size = acc
        order.avg_px = avg
        order.state = OrderState.FILLED
        order.save(update_fields=["price", "size", "filled_size", "avg_px", "state"])
        Trade.objects.create(
            strategy=self.s, order=order, side=order.side, fill_price=avg,
            fill_size=acc, fee=_d(data.get("fee") or 0),
            fee_ccy=data.get("feeCcy", ""), ts=timezone.now())
        self._update_position(order.side, avg, acc)
        self.log(f"{order.get_side_display()} {acc} {inst} @ {avg}")
        return {"size": acc, "price": avg}

    # --- остановка -----------------------------------------------------------
    def cancel_all(self):
        live = list(self.s.orders.filter(
            state__in=[OrderState.LIVE, OrderState.PARTIALLY_FILLED]))
        payload = [{"instId": o.raw.get("instId", self.s.inst_id), "ordId": o.ord_id}
                   for o in live if o.ord_id]
        if payload:
            try:
                okx.cancel_batch_orders(payload)
            except okx.OkxError as e:
                self.log(f"Ошибка отмены: {e.msg}", "error")
        ids = [o.id for o in live]
        GridOrder.objects.filter(id__in=ids).update(state=OrderState.CANCELED)
        return len(live)

    def stop(self):
        n = self.cancel_all()
        self.s.status = StrategyStatus.STOPPED
        self.s.save(update_fields=["status", "updated_at"])
        self.log(f"Остановлена. Отменено активных ордеров: {n}.")
        return n

    # --- интерфейс (переопределяется) ----------------------------------------
    def start(self) -> dict:
        self.s.status = StrategyStatus.RUNNING
        self.s.save(update_fields=["status", "updated_at"])
        return {"ok": True, "msg": "Запущена."}

    def tick(self) -> bool:
        raise NotImplementedError


# =========================================================================
#  DCA — усреднение стоимости
# =========================================================================
class DcaEngine(BaseEngine):
    """DCA: по расписанию или докупка на падении, с фиксацией прибыли.

    params: mode ('schedule'|'dip'), base_amount, safety_amount, interval_hours,
            price_deviation_pct, safety_count, volume_scale, take_profit_pct.
    """

    def start(self):
        self.s.status = StrategyStatus.RUNNING
        self.s.save(update_fields=["status", "updated_at"])
        self.save_state(safety_used=0, last_buy_price=None, last_buy_ts=None)
        # Первый (базовый) ордер сразу
        res = self.place_market(Side.BUY, quote_amount=self.p("base_amount", 50))
        if res:
            self.save_state(last_buy_price=float(res["price"]),
                            last_buy_ts=time.time())
        self.log("DCA запущена: размещён базовый ордер.")
        return {"ok": True, "msg": "DCA запущена, базовый ордер размещён."}

    def tick(self):
        self.s.refresh_from_db()
        if self.s.status != StrategyStatus.RUNNING:
            return True
        pos = self.position()
        try:
            price = self.price()
        except okx.OkxError:
            return False

        # 1) Фиксация прибыли: цена выше средней на take_profit_pct
        tp = _d(self.p("take_profit_pct", 3)) / 100
        if pos.base_qty > 0 and pos.avg_price > 0 and price >= pos.avg_price * (1 + tp):
            self.place_market(Side.SELL, base_amount=pos.base_qty)
            self.save_state(safety_used=0, last_buy_price=None)
            self.log(f"DCA: тейк-профит по {price} (средняя {pos.avg_price}).")
            return False

        # 2) Усреднение
        mode = self.p("mode", "dip")
        if mode == "schedule":
            interval = _d(self.p("interval_hours", 24)) * 3600
            last_ts = self.state("last_buy_ts") or 0
            if time.time() - last_ts >= float(interval):
                res = self.place_market(Side.BUY, quote_amount=self.p("base_amount", 50))
                if res:
                    self.save_state(last_buy_ts=time.time(),
                                    last_buy_price=float(res["price"]))
        else:  # dip — докупка на падении
            used = int(self.state("safety_used", 0) or 0)
            last = self.state("last_buy_price")
            dev = _d(self.p("price_deviation_pct", 2)) / 100
            max_safety = int(self.p("safety_count", 5))
            if pos.base_qty == 0:
                res = self.place_market(Side.BUY, quote_amount=self.p("base_amount", 100))
                if res:
                    self.save_state(last_buy_price=float(res["price"]),
                                    safety_used=0, last_buy_ts=time.time())
            elif last and used < max_safety and price <= _d(last) * (1 - dev):
                scale = _d(self.p("volume_scale", 1.5)) ** used
                amount = _d(self.p("safety_amount", 50)) * scale
                res = self.place_market(Side.BUY, quote_amount=amount)
                if res:
                    self.save_state(last_buy_price=float(res["price"]),
                                    safety_used=used + 1, last_buy_ts=time.time())
                    self.log(f"DCA: докупка #{used + 1} на падении до {price}.")
        return False


# =========================================================================
#  Trend Following — следование за трендом
# =========================================================================
class TrendEngine(BaseEngine):
    """Тренд: пересечение быстрой и медленной скользящих средних + фильтр RSI.

    params: bar, fast, slow, order_amount, use_rsi, rsi_period,
            rsi_overbought, rsi_oversold.
    """

    def tick(self):
        self.s.refresh_from_db()
        if self.s.status != StrategyStatus.RUNNING:
            return True
        bar = self.p("bar", "1H")
        fast_n = int(self.p("fast", 9))
        slow_n = int(self.p("slow", 21))
        try:
            closes = self.closes(bar=bar, limit=max(slow_n * 3, 100))
        except okx.OkxError:
            return False
        fast = sma(closes, fast_n)
        slow = sma(closes, slow_n)
        if fast is None or slow is None:
            return False

        pos = self.position()
        long_signal = fast > slow  # хотим быть в позиции, если быстрая выше медленной

        # Фильтр RSI (опционально): не покупать на перекупленности
        if self.p("use_rsi") and long_signal and pos.base_qty == 0:
            r = rsi(closes, int(self.p("rsi_period", 14)))
            if r is not None and r >= float(self.p("rsi_overbought", 70)):
                return False  # перекуплено — ждём

        if long_signal and pos.base_qty == 0:
            self.place_market(Side.BUY, quote_amount=self.p("order_amount", 100))
            self.log(f"Тренд: вход в лонг (MA{fast_n}={fast:.4f} > MA{slow_n}={slow:.4f}).")
        elif not long_signal and pos.base_qty > 0:
            self.place_market(Side.SELL, base_amount=pos.base_qty)
            self.log(f"Тренд: выход (MA{fast_n}={fast:.4f} < MA{slow_n}={slow:.4f}).")
        return False


# =========================================================================
#  Scalping — быстрые сделки на малом take-profit
# =========================================================================
class ScalpingEngine(BaseEngine):
    """Скальпинг: вход по рынку, выход по малому take-profit/stop.

    params: order_amount, target_pct, stop_pct (опц.).
    ВНИМАНИЕ: на REST-опросе это упрощённый быстрый тейк-профит, а не HFT —
    для настоящего скальпинга нужен WebSocket и минимальная задержка (см. документ).
    """

    def tick(self):
        self.s.refresh_from_db()
        if self.s.status != StrategyStatus.RUNNING:
            return True
        pos = self.position()
        try:
            price = self.price()
        except okx.OkxError:
            return False

        if pos.base_qty == 0:
            res = self.place_market(Side.BUY, quote_amount=self.p("order_amount", 50))
            if res:
                self.save_state(entry_price=float(res["price"]))
                self.log(f"Скальп: вход @ {res['price']}.")
            return False

        entry = _d(self.state("entry_price") or pos.avg_price)
        target = _d(self.p("target_pct", 0.3)) / 100
        stop = self.p("stop_pct")
        if entry > 0 and price >= entry * (1 + target):
            self.place_market(Side.SELL, base_amount=pos.base_qty)
            self.log(f"Скальп: take-profit @ {price} (вход {entry}).")
        elif stop and entry > 0 and price <= entry * (1 - _d(stop) / 100):
            self.place_market(Side.SELL, base_amount=pos.base_qty)
            self.log(f"Скальп: stop-loss @ {price} (вход {entry}).", "warning")
        return False


# =========================================================================
#  Arbitrage — треугольный арбитраж (детектор + опц. исполнение)
# =========================================================================
class ArbitrageEngine(BaseEngine):
    """Треугольный арбитраж по трём парам: base→mid→cross→base.

    params: base ('USDT'), mid ('BTC'), cross ('ETH'), amount, min_profit_pct,
            fee_pct, execute (bool — реально исполнять сделки).

    По умолчанию execute=False: движок только ищет и логирует возможности
    (детектор). Исполнение трёх рыночных ног на демо часто невозможно из-за
    ликвидности и требует минимальной задержки (см. документ).
    """

    def _pairs(self):
        base = self.p("base", "USDT")
        mid = self.p("mid", "BTC")
        cross = self.p("cross", "ETH")
        return f"{mid}-{base}", f"{cross}-{mid}", f"{cross}-{base}"

    def tick(self):
        self.s.refresh_from_db()
        if self.s.status != StrategyStatus.RUNNING:
            return True
        p1, p2, p3 = self._pairs()
        try:
            t1, t2, t3 = self.ticker(p1), self.ticker(p2), self.ticker(p3)
        except okx.OkxError as e:
            self.log(f"Арбитраж: нет данных — {e.msg}", "warning")
            return False

        ask1, bid1 = _d(t1["askPx"]), _d(t1["bidPx"])
        ask2, bid2 = _d(t2["askPx"]), _d(t2["bidPx"])
        ask3, bid3 = _d(t3["askPx"]), _d(t3["bidPx"])
        fee = _d(self.p("fee_pct", 0.1)) / 100
        keep = (1 - fee)

        # Направление A: base->mid->cross->base (покупаем mid, покупаем cross, продаём cross)
        if ask1 > 0 and ask2 > 0:
            mult_a = (Decimal("1") / ask1) * keep * (Decimal("1") / ask2) * keep * bid3 * keep
        else:
            mult_a = Decimal("0")
        # Направление B: base->cross->mid->base (покупаем cross, продаём в mid, продаём mid)
        if ask3 > 0 and bid1 > 0:
            mult_b = (Decimal("1") / ask3) * keep * bid2 * keep * bid1 * keep
        else:
            mult_b = Decimal("0")

        best_dir = "A" if mult_a >= mult_b else "B"
        best = max(mult_a, mult_b)
        profit_pct = (best - 1) * 100
        threshold = _d(self.p("min_profit_pct", 0.3))

        if profit_pct >= threshold:
            self.log(f"Арбитраж {best_dir}: возможность +{profit_pct:.3f}% "
                     f"({p1},{p2},{p3}).")
            if self.p("execute"):
                self._execute(best_dir)
        return False

    def _execute(self, direction):
        """Исполнить три ноги цикла рыночными ордерами (только на ликвидных парах)."""
        p1, p2, p3 = self._pairs()
        amount = self.p("amount", 50)
        self.log(f"Арбитраж: исполнение цикла {direction} на {amount} USDT.", "warning")
        if direction == "A":
            r1 = self.place_market(Side.BUY, quote_amount=amount, inst_id=p1)
            if not r1:
                return
            r2 = self.place_market(Side.BUY, base_amount=None, quote_amount=r1["size"], inst_id=p2)
            if not r2:
                return
            self.place_market(Side.SELL, base_amount=r2["size"], inst_id=p3)
        else:
            r1 = self.place_market(Side.BUY, quote_amount=amount, inst_id=p3)
            if not r1:
                return
            r2 = self.place_market(Side.SELL, base_amount=r1["size"], inst_id=p2)
            if not r2:
                return
            self.place_market(Side.SELL, base_amount=r2["size"], inst_id=p1)


# =========================================================================
#  Диспетчер
# =========================================================================
def get_engine(strategy):
    """Возвращает движок под тип стратегии."""
    from grid.services.grid_engine import GridEngine
    mapping = {
        "grid": GridEngine,
        "dca": DcaEngine,
        "trend": TrendEngine,
        "scalping": ScalpingEngine,
        "arbitrage": ArbitrageEngine,
    }
    cls = mapping.get(strategy.strategy_type)
    if cls is None:
        raise ValueError(f"Неизвестный тип стратегии: {strategy.strategy_type}")
    return cls(strategy)
