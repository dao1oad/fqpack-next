# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.db import DBOrderManagement, DBfreshquant
from freshquant.market_data.xtdata.schema import normalize_prefixed_code


def load_active_tpsl_codes() -> list[str]:
    holding_codes = _load_holding_codes()
    if not holding_codes:
        return []

    configured_codes = _load_configured_codes()
    return sorted(holding_codes & configured_codes)


def _load_holding_codes() -> set[str]:
    codes: set[str] = set()
    for doc in DBfreshquant["xt_positions"].find(
        {},
        {"stock_code": 1, "code": 1, "symbol": 1, "volume": 1},
    ):
        if _coerce_positive_int(doc.get("volume")) <= 0:
            continue
        raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
        code = normalize_prefixed_code(str(raw)).lower()
        if code:
            codes.add(code)
    return codes


def _load_configured_codes() -> set[str]:
    codes: set[str] = set()

    for doc in DBOrderManagement["om_stoploss_bindings"].find(
        {"enabled": True},
        {"symbol": 1},
    ):
        code = normalize_prefixed_code(str(doc.get("symbol") or "")).lower()
        if code:
            codes.add(code)

    for doc in DBOrderManagement["om_takeprofit_profiles"].find({}, {"symbol": 1}):
        code = normalize_prefixed_code(str(doc.get("symbol") or "")).lower()
        if code:
            codes.add(code)

    return codes


def _coerce_positive_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0

