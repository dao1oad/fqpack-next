# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.database.cache import in_memory_cache
from freshquant.instrument.bond import query_bond_map
from freshquant.instrument.etf import query_etf_map
from freshquant.instrument.future import query_future_map
from freshquant.instrument.index import query_index_map
from freshquant.instrument.stock import query_stock_map

CN_TRADING_ETF_CODE_PREFIXES = (
    "15",
    "16",
    "18",
    "50",
    "51",
    "52",
    "53",
    "56",
    "58",
)
CN_INDEX_SYMBOL_PREFIXES = ("sh000", "sz399")


def _normalized_cn_symbol(code: str) -> tuple[str, str] | None:
    raw = str(code or "").strip().lower()
    if not raw:
        return None
    if len(raw) == 9 and raw[:6].isdigit() and raw[6:] in {".sh", ".sz", ".bj"}:
        raw = raw[7:] + raw[:6]
    if len(raw) == 8 and raw[:2] in {"sh", "sz", "bj"} and raw[2:].isdigit():
        return raw, raw[2:]
    if len(raw) == 6 and raw.isdigit():
        return raw, raw
    return None


def is_trading_etf_code(code: str) -> bool:
    """Classify an exchange-traded ETF code without consulting runtime maps."""

    normalized = _normalized_cn_symbol(code)
    return bool(normalized and normalized[1].startswith(CN_TRADING_ETF_CODE_PREFIXES))


def infer_cn_instrument_type(code: str) -> InstrumentType | None:
    """Infer Stock/ETF/Index for a normalized Chinese security code.

    Explicit market-qualified index symbols take precedence over numeric
    prefixes. Bare codes remain Stock unless they are unambiguous ETF or
    Shenzhen index codes; runtime instrument maps resolve other ambiguities.
    """

    normalized = _normalized_cn_symbol(code)
    if normalized is None:
        return None
    symbol, base_code = normalized
    if symbol.startswith(CN_INDEX_SYMBOL_PREFIXES) or (
        len(symbol) == 6 and base_code.startswith("399")
    ):
        return InstrumentType.INDEX_CN
    if is_trading_etf_code(symbol):
        return InstrumentType.ETF_CN
    return InstrumentType.STOCK_CN


@in_memory_cache.memoize(expiration=900)
def query_instrument_type(code: str) -> InstrumentType | None:
    code = str(code or "").lower()
    if query_stock_map().get(code):
        return InstrumentType.STOCK_CN
    elif query_etf_map().get(code):
        return InstrumentType.ETF_CN
    elif query_bond_map().get(code):
        return InstrumentType.BOND_CN
    elif query_index_map().get(code):
        return InstrumentType.INDEX_CN
    else:
        return infer_cn_instrument_type(code)


@in_memory_cache.memoize(expiration=900)
def query_instrument_info(code: str) -> dict[str, Any] | None:
    if query_stock_map().get(code):
        return query_stock_map().get(code)
    elif query_etf_map().get(code):
        return query_etf_map().get(code)
    elif query_bond_map().get(code):
        return query_bond_map().get(code)
    elif query_index_map().get(code):
        return query_index_map().get(code)
    elif query_future_map().get(code):
        return query_future_map().get(code)
    else:
        return None


def query_decimal_point(code: str) -> int:
    decimal_point = 2
    inst_info = query_instrument_info(code)
    if inst_info is not None:
        decimal_point = inst_info.get("decimal_point", 2)
    return decimal_point


if __name__ == "__main__":
    print(query_instrument_type("sz002796"))
    print(query_instrument_info("sh510050"))
    print(query_instrument_info("510050"))
