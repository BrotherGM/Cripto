"""Сервисный слой OKX: REST-обёртки поверх python-okx SDK.

Конфигурация берётся из django.conf.settings.OKX (которое читает .env).
flag = "1" -> демо/тест (по умолчанию), "0" -> реальная торговля.
Демо использует тот же REST-хост; SDK сам выставляет заголовок
`x-simulated-trading` по значению flag.
"""
from functools import lru_cache

from django.conf import settings
from okx import Account, MarketData, PublicData, Trade


class OkxError(Exception):
    """OKX вернул код, отличный от '0'."""

    def __init__(self, code: str, msg: str, raw: dict):
        self.code = code
        self.msg = msg
        self.raw = raw
        super().__init__(f"OKX error {code}: {msg}")


def _cfg():
    return settings.OKX


def is_demo() -> bool:
    return _cfg()["FLAG"] == "1"


# --- SDK-клиенты (кэшируются) -------------------------------------------------
@lru_cache(maxsize=1)
def account_api() -> Account.AccountAPI:
    c = _cfg()
    return Account.AccountAPI(
        api_key=c["API_KEY"], api_secret_key=c["API_SECRET"],
        passphrase=c["PASSPHRASE"], flag=c["FLAG"], debug=c["DEBUG"],
    )


@lru_cache(maxsize=1)
def trade_api() -> Trade.TradeAPI:
    c = _cfg()
    return Trade.TradeAPI(
        api_key=c["API_KEY"], api_secret_key=c["API_SECRET"],
        passphrase=c["PASSPHRASE"], flag=c["FLAG"], debug=c["DEBUG"],
    )


@lru_cache(maxsize=1)
def market_api() -> MarketData.MarketAPI:
    c = _cfg()
    return MarketData.MarketAPI(flag=c["FLAG"], debug=c["DEBUG"])


@lru_cache(maxsize=1)
def public_api() -> PublicData.PublicAPI:
    c = _cfg()
    return PublicData.PublicAPI(flag=c["FLAG"], debug=c["DEBUG"])


# --- Разбор ответов -----------------------------------------------------------
def unwrap(resp: dict):
    """Достаёт data из ответа OKX или бросает OkxError."""
    if not isinstance(resp, dict):
        raise OkxError("unknown", "Неожиданный формат ответа OKX", {"raw": resp})
    code = str(resp.get("code", ""))
    if code != "0":
        raise OkxError(code or "unknown", resp.get("msg", ""), resp)
    return resp.get("data", [])


# --- Высокоуровневые операции -------------------------------------------------
def check_connection() -> dict:
    """Лёгкая проверка связи (серверное время, без ключей)."""
    data = unwrap(public_api().get_system_time())
    return {"connected": True, "demo": is_demo(), "server_time_ms": data[0]["ts"] if data else None}


def get_instrument(inst_id: str, inst_type: str = "SPOT") -> dict:
    """Параметры инструмента: tickSz, lotSz, minSz (раздел 2.2 документа)."""
    data = unwrap(public_api().get_instruments(instType=inst_type, instId=inst_id))
    if not data:
        raise OkxError("not_found", f"Инструмент {inst_id} не найден", {})
    return data[0]


def get_last_price(inst_id: str) -> str:
    """Текущая цена (last) инструмента."""
    data = unwrap(market_api().get_ticker(inst_id))
    if not data:
        raise OkxError("not_found", f"Тикер {inst_id} недоступен", {})
    return data[0]["last"]


def place_limit_order(*, inst_id: str, td_mode: str, side: str, price, size, cl_ord_id: str) -> dict:
    """Размещает лимитный ордер. Возвращает первый элемент data (ordId, sCode, sMsg)."""
    resp = trade_api().place_order(
        instId=inst_id, tdMode=td_mode, side=side, ordType="limit",
        px=str(price), sz=str(size), clOrdId=cl_ord_id,
    )
    data = unwrap(resp)
    return data[0] if data else {}


def cancel_order(inst_id: str, ord_id: str = "", cl_ord_id: str = "") -> dict:
    resp = trade_api().cancel_order(instId=inst_id, ordId=ord_id, clOrdId=cl_ord_id)
    data = unwrap(resp)
    return data[0] if data else {}


def cancel_batch_orders(orders: list[dict]) -> list:
    """Пакетная отмена (раздел 4.1). orders: [{'instId':..., 'ordId':...}, ...].

    OKX принимает максимум 20 ордеров за запрос — разбиваем на части.
    """
    results = []
    for i in range(0, len(orders), 20):
        chunk = orders[i:i + 20]
        resp = trade_api().cancel_multiple_orders(orders_data=chunk)
        results.extend(unwrap(resp))
    return results


def get_order(inst_id: str, ord_id: str = "", cl_ord_id: str = "") -> dict:
    data = unwrap(trade_api().get_order(instId=inst_id, ordId=ord_id, clOrdId=cl_ord_id))
    return data[0] if data else {}
