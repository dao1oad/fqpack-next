# -*- coding: utf-8 -*-

from typing import Dict

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.database.cache import in_memory_cache
from freshquant.instrument.bond import query_bond_map
from freshquant.instrument.etf import query_etf_map
from freshquant.instrument.future import query_future_map
from freshquant.instrument.index import query_index_map
from freshquant.instrument.stock import query_stock_map


@in_memory_cache.memoize(expiration=900)
def query_instrument_type(code: str) -> InstrumentType:
    code = code.lower()
    if query_stock_map().get(code):
        return InstrumentType.STOCK_CN
    elif query_etf_map().get(code):
        return InstrumentType.ETF_CN
    elif query_bond_map().get(code):
        return InstrumentType.BOND_CN
    elif query_index_map().get(code):
        return InstrumentType.INDEX_CN
    else:
        return None


@in_memory_cache.memoize(expiration=900)
def query_instrument_info(code: str) -> Dict:
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
        decimal_point = inst_info.get('decimal_point', 2)
    return decimal_point


if __name__ == "__main__":
    print(query_instrument_type("sz002796"))
    print(query_instrument_info("sh510050"))
    print(query_instrument_info("510050"))
