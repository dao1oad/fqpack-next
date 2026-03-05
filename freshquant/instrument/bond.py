# -*- coding: utf-8 -*-

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBQuantAxis

REPO_CODE_LIST = [
    "204001.SH",
    "204002.SH",
    "204003.SH",
    "204004.SH",
    "204007.SH",
    "204014.SH",
    "204028.SH",
    "204091.SH",
    "204182.SH",
    "131810.SZ",
    "131811.SZ",
    "131800.SZ",
    "131809.SZ",
    "131801.SZ",
    "131802.SZ",
    "131803.SZ",
    "131805.SZ",
    "131806.SZ",
]


@in_memory_cache.memoize(expiration=3600)
def query_bond_map() -> dict:
    bond_list = list(DBQuantAxis.bond_list.find({}))
    bond_map = {}
    for bond in bond_list:
        k1 = f'{bond["sse"]}{bond["code"]}'.lower()
        k2 = f'{bond["sse"]}{bond["code"]}'.upper()
        k3 = f'{bond["code"]}'
        k4 = f'{bond["code"]}.{bond["sse"]}'.upper()
        bond_map[k1] = {
            "code": bond["code"],
            "name": bond["name"],
            "volunit": bond["volunit"],
            "decimal_point": bond["decimal_point"],
            "sse": bond["sse"],
            "sec": bond["sec"],
        }
        bond_map[k2] = bond_map[k1]
        bond_map[k3] = bond_map[k1]
        bond_map[k4] = bond_map[k1]
    return bond_map
