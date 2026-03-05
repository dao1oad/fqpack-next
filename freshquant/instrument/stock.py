# -*- coding: utf-8 -*-

from typing import Optional

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBQuantAxis


@in_memory_cache.memoize(expiration=3600)
def query_stock_map() -> dict:
    stock_list = list(DBQuantAxis.stock_list.find({}))
    stock_map = {}
    for stock in stock_list:
        k1 = f'{stock["sse"]}{stock["code"]}'.lower()
        k2 = f'{stock["sse"]}{stock["code"]}'.upper()
        k3 = f'{stock["code"]}'
        k4 = f'{stock["code"]}.{stock["sse"]}'.upper()
        stock_map[k1] = {
            "code": stock["code"],
            "name": stock["name"],
            "volunit": stock["volunit"],
            "decimal_point": stock["decimal_point"],
            "sse": stock["sse"],
            "sec": stock["sec"],
        }
        stock_map[k2] = stock_map[k1]
        stock_map[k3] = stock_map[k1]
        stock_map[k4] = stock_map[k1]
    return stock_map


@in_memory_cache.memoize(expiration=3600)
def fq_inst_fetch_stock_list(code: Optional[str] = None) -> list:
    if code is None:
        stock_list = list(DBQuantAxis.stock_list.find({}))
    else:
        stock_list = list(DBQuantAxis.stock_list.find({"code": code}))
    return stock_list


if __name__ == "__main__":
    pass
