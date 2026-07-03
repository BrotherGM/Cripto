"""Обновление справочника торговых пар из OKX (public/instruments)."""
from decimal import Decimal

from django.utils import timezone

from grid.models import Instrument
from grid.services import okx_client as okx


def _dec(v):
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except Exception:  # noqa: BLE001
        return None


def refresh_instruments(inst_type: str = "SPOT") -> dict:
    """Тянет все инструменты указанного типа с биржи и обновляет справочник.

    Возвращает {'ok', 'count', 'live', 'msg'}.
    """
    data = okx.unwrap(okx.public_api().get_instruments(instType=inst_type))
    now = timezone.now()
    objs = []
    for d in data:
        objs.append(Instrument(
            inst_id=d["instId"], inst_type=inst_type,
            base_ccy=d.get("baseCcy", ""), quote_ccy=d.get("quoteCcy", ""),
            tick_sz=_dec(d.get("tickSz")), lot_sz=_dec(d.get("lotSz")),
            min_sz=_dec(d.get("minSz")), state=d.get("state", ""), updated_at=now,
            active=(d.get("state") == "live"),  # значение только для НОВЫХ пар
        ))
    # active НЕ входит в update_fields — ручные переключения существующих пар
    # сохраняются; для новых пар active берётся из объекта (по состоянию биржи).
    Instrument.objects.bulk_create(
        objs, update_conflicts=True, unique_fields=["inst_id"],
        update_fields=["inst_type", "base_ccy", "quote_ccy", "tick_sz",
                       "lot_sz", "min_sz", "state", "updated_at"],
    )
    live = sum(1 for d in data if d.get("state") == "live")
    active = Instrument.objects.filter(inst_type=inst_type, active=True).count()
    return {"ok": True, "count": len(objs), "live": live, "active": active,
            "msg": f"Обновлено пар {inst_type}: {len(objs)} "
                   f"(на бирже live: {live}, active в справочнике: {active})."}
