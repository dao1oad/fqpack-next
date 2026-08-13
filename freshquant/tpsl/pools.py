# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.db import DBfreshquant, DBOrderManagement
from freshquant.market_data.xtdata.schema import normalize_prefixed_code


def load_active_tpsl_codes() -> list[str]:
    holding_codes = _load_holding_codes()
    if not holding_codes:
        return []

    configured_codes = _load_configured_codes()
    return sorted(holding_codes & configured_codes)


def load_active_buy_line_codes() -> list[str]:
    """买入线 universe（#549）：当前持仓 ∩ 有 buy grid 配置。

    与止盈集合（``load_active_tpsl_codes``）双集合隔离，不得混入。
    """

    holding_codes = _load_holding_codes()
    if not holding_codes:
        return []
    configured_codes = _load_buy_grid_configured_codes()
    return sorted(holding_codes & configured_codes)


def _load_holding_codes() -> set[str]:
    codes: set[str] = set()
    for doc in DBfreshquant["xt_positions"].find(
        {},
        {"stock_code": 1, "code": 1, "symbol": 1, "volume": 1},
    ):
        raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
        volume = _parse_non_negative_int(
            doc.get("volume"),
            field_name="xt_positions volume",
            symbol=raw,
            default=0,
        )
        if volume <= 0:
            continue
        code = normalize_prefixed_code(str(raw)).lower()
        if code:
            codes.add(code)
    return codes


def _load_buy_grid_configured_codes() -> set[str]:
    codes: set[str] = set()
    for doc in DBfreshquant["guardian_buy_grid_configs"].find(
        {"enabled": True},
        {"code": 1, "buy_enabled": 1},
    ):
        code = normalize_prefixed_code(str(doc.get("code") or "")).lower()
        if not code:
            continue
        buy_enabled = doc.get("buy_enabled")
        if isinstance(buy_enabled, list) and len(buy_enabled) == 3:
            if not any(bool(item) for item in buy_enabled):
                continue
        codes.add(code)
    return codes


def _load_configured_codes() -> set[str]:
    codes: set[str] = set()

    for doc in DBOrderManagement["om_takeprofit_profiles"].find({}, {"symbol": 1}):
        code = normalize_prefixed_code(str(doc.get("symbol") or "")).lower()
        if code:
            codes.add(code)

    return codes


def _parse_non_negative_int(value, *, field_name, symbol, default) -> int:
    if value in (None, ""):
        return int(default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} invalid for {symbol or '-'}: {value!r}"
        ) from exc
    if parsed < 0:
        raise ValueError(f"{field_name} invalid for {symbol or '-'}: {value!r}")
    return parsed
