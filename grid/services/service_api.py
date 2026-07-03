"""Каталог сервисных (read-only) запросов к OKX для страниц «Демо» и «Реал».

Каждый пункт вызывает соответствующий метод SDK и возвращает данные в виде
таблицы + сырого JSON. Только чтение — ордера здесь не выставляются.
Режим (demo/live) выбирается снаружи через okx.set_mode(); в demo-режиме
используются тестовые ключи (x-simulated-trading), в live — боевые.
"""
import json

from grid.services import okx_client as okx

DEFAULT_INST = "BTC-USDT"

# --- каталог: группы -> пункты ------------------------------------------------
# Каждый пункт: key, title, needs_inst, call(inst_id) -> сырой ответ OKX.
CATALOG = [
    ("Аккаунт (приватный)", [
        {"key": "balance", "title": "💰 Баланс счёта", "needs_inst": False,
         "call": lambda i: okx.account_api().get_account_balance()},
        {"key": "config", "title": "⚙️ Конфигурация аккаунта", "needs_inst": False,
         "call": lambda i: okx.account_api().get_account_config()},
        {"key": "positions", "title": "📊 Позиции", "needs_inst": False,
         "call": lambda i: okx.account_api().get_positions()},
        {"key": "bills", "title": "🧾 Движения по счёту (bills)", "needs_inst": False,
         "call": lambda i: okx.account_api().get_account_bills(limit="30")},
        {"key": "fee_rates", "title": "% Ставки комиссии (SPOT)", "needs_inst": False,
         "call": lambda i: okx.account_api().get_fee_rates(instType="SPOT")},
        {"key": "max_size", "title": "📐 Макс. размер ордера (по паре)", "needs_inst": True,
         "call": lambda i: okx.account_api().get_max_order_size(instId=i, tdMode="cash")},
        {"key": "max_avail", "title": "📦 Макс. доступно к покупке/продаже", "needs_inst": True,
         "call": lambda i: okx.account_api().get_max_avail_size(instId=i, tdMode="cash")},
    ]),
    ("Торговля (приватный)", [
        {"key": "open_orders", "title": "📋 Открытые ордера", "needs_inst": False,
         "call": lambda i: okx.trade_api().get_order_list(instType="SPOT")},
        {"key": "orders_history", "title": "🗂 История ордеров (7 дней)", "needs_inst": False,
         "call": lambda i: okx.trade_api().get_orders_history(instType="SPOT", limit="30")},
        {"key": "fills", "title": "🧩 История исполнений (fills)", "needs_inst": False,
         "call": lambda i: okx.trade_api().get_fills(instType="SPOT", limit="30")},
    ]),
    ("Рынок (публичный)", [
        {"key": "tickers", "title": "📈 Все тикеры SPOT", "needs_inst": False,
         "call": lambda i: okx.market_api().get_tickers(instType="SPOT")},
        {"key": "ticker", "title": "🎯 Тикер по паре", "needs_inst": True,
         "call": lambda i: okx.market_api().get_ticker(instId=i)},
        {"key": "orderbook", "title": "📚 Стакан (order book)", "needs_inst": True,
         "call": lambda i: okx.market_api().get_orderbook(instId=i, sz="20")},
        {"key": "candles", "title": "🕯 Свечи (1H, 50)", "needs_inst": True,
         "call": lambda i: okx.market_api().get_candlesticks(instId=i, bar="1H", limit="50")},
        {"key": "trades", "title": "💱 Последние сделки рынка", "needs_inst": True,
         "call": lambda i: okx.market_api().get_trades(instId=i, limit="30")},
    ]),
    ("Справочники и система (публичный)", [
        {"key": "instruments", "title": "📖 Инструменты SPOT (все пары)", "needs_inst": False,
         "call": lambda i: okx.public_api().get_instruments(instType="SPOT")},
        {"key": "index_tickers", "title": "🧭 Индексные цены (USDT)", "needs_inst": False,
         "call": lambda i: okx.market_api().get_index_tickers(quoteCcy="USDT")},
        {"key": "price_limit", "title": "⛔️ Ценовые лимиты по паре", "needs_inst": True,
         "call": lambda i: okx.public_api().get_price_limit(instId=i)},
        {"key": "system_time", "title": "⏱ Время сервера", "needs_inst": False,
         "call": lambda i: okx.public_api().get_system_time()},
    ]),
]

_INDEX = {item["key"]: item for _, items in CATALOG for item in items}

# Явные наборы колонок для «плоских» таблиц (иначе берём ключи первой строки).
_COLUMNS = {
    "balance": ["ccy", "eq", "availBal", "frozenBal", "ordFrozen", "eqUsd"],
    "candles": ["ts", "open", "high", "low", "close", "vol", "volCcy"],
}


def _tabulate(key, data):
    """Приводит ответ OKX к (columns, rows) для табличного вывода."""
    if not isinstance(data, list) or not data:
        return [], []

    if key == "balance":
        details = data[0].get("details", []) if isinstance(data[0], dict) else []
        cols = _COLUMNS["balance"]
        return cols, [[d.get(c, "") for c in cols] for d in details]

    if key == "candles":
        cols = _COLUMNS["candles"]
        return cols, [((row + [""] * 7)[:7]) for row in data]

    if isinstance(data[0], dict):
        cols = list(data[0].keys())[:14]
        rows = []
        for d in data[:200]:
            row = []
            for c in cols:
                v = d.get(c, "")
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)[:60]
                row.append(v)
            rows.append(row)
        return cols, rows

    return [], []  # нестандартная структура — покажем только JSON


def run(mode: str, key: str, inst_id: str = "") -> dict:
    """Выполняет сервисный запрос в заданном режиме. Возвращает результат для шаблона."""
    spec = _INDEX.get(key)
    if not spec:
        return {"ok": False, "error": f"Неизвестный запрос: {key}"}

    inst_id = (inst_id or "").strip().upper() or DEFAULT_INST
    if spec["needs_inst"] and not inst_id:
        return {"ok": False, "title": spec["title"], "error": "Укажите пару (instId)."}

    okx.set_mode(mode)
    try:
        resp = spec["call"](inst_id)
        data = okx.unwrap(resp)
    except okx.OkxError as e:
        return {"ok": False, "title": spec["title"], "error": f"OKX {e.code}: {e.msg}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "title": spec["title"], "error": str(e)}

    columns, rows = _tabulate(key, data)
    count = len(data) if isinstance(data, list) else 1
    return {
        "ok": True, "title": spec["title"], "key": key,
        "needs_inst": spec["needs_inst"], "count": count,
        "columns": columns, "rows": rows,
        "raw": json.dumps(data, ensure_ascii=False, indent=2),
    }
