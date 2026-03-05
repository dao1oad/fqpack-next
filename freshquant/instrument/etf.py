# -*- coding: utf-8 -*-

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBQuantAxis


@in_memory_cache.memoize(expiration=3600)
def query_etf_map() -> dict:
    etf_list = list(DBQuantAxis.etf_list.find({}))
    etf_map = {}
    for etf in etf_list:
        k1 = f'{etf["sse"]}{etf["code"]}'.lower()
        k2 = f'{etf["sse"]}{etf["code"]}'.upper()
        k3 = f'{etf["code"]}'
        k4 = f'{etf["code"]}.{etf["sse"]}'.upper()
        etf_map[k1] = {
            "code": etf["code"],
            "name": etf["name"],
            "volunit": etf["volunit"],
            "decimal_point": etf["decimal_point"],
            "sse": etf["sse"],
            "sec": etf["sec"],
        }
        etf_map[k2] = etf_map[k1]
        etf_map[k3] = etf_map[k1]
        etf_map[k4] = etf_map[k1]
    return etf_map
