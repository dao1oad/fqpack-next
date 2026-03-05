# -*- coding: utf-8 -*-

import pydash

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant
from typing import Optional


@in_memory_cache.memoize(expiration=900)
def queryParam(key: Optional[str] = None, default = None):
    if key is not None and key != "":
        path = key.split(".")
        param = findParam(path[0])
        if param is not None and param["value"] is not None:
            if len(path) == 1:
                return param["value"]
            else:
                return pydash.get(param["value"], ".".join(path[1:]), default)

@in_memory_cache.memoize(expiration=900)
def findParam(code: Optional[str] = None, default = None):
    return DBfreshquant["params"].find_one({"code": code})
        

if __name__ == "__main__":
    position_pct = float(queryParam("guardian.stock.position_pct", 40.0))
    print(position_pct)
