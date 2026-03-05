# -*- coding: utf-8 -*-

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBQuantAxis


@in_memory_cache.memoize(expiration=3600)
def query_index_map() -> dict:
    index_list = list(DBQuantAxis.index_list.find({}))
    index_map = {}
    for index in index_list:
        k1 = f'{index["sse"]}{index["code"]}'.lower()
        k2 = f'{index["sse"]}{index["code"]}'.upper()
        k3 = f'{index["code"]}'
        k4 = f'{index["code"]}.{index["sse"]}'.upper()
        index_map[k1] = {
            "code": index["code"],
            "name": index["name"],
            "volunit": index["volunit"],
            "decimal_point": index["decimal_point"],
            "sse": index["sse"],
            "sec": index["sec"],
        }
        index_map[k2] = index_map[k1]
        index_map[k3] = index_map[k1]
        index_map[k4] = index_map[k1]
    return index_map
