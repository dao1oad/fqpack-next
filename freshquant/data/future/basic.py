# -*- coding:utf-8 -*-

from freshquant.database.cache import redis_cache
from freshquant.db import DBQuantAxis


@redis_cache.memoize(expiration=864000)
def fq_fetch_future_basic(code):
    return DBQuantAxis["future_list"].find_one({"code": code})
