# -*- coding:utf-8 -*-

from pydash import get

from freshquant.database.cache import redis_cache
from freshquant.db import DBfreshquant, DBQuantAxis


@redis_cache.memoize(expiration=864000)
def fq_fetch_a_stock_basic(code):
    return DBQuantAxis["stock_list"].find_one({"code": code})


@redis_cache.memoize(expiration=864000)
def fq_fetch_a_stock_category(code):
    stock_one = DBfreshquant["stock_pools"].find_one({"code": code})
    return get(stock_one, 'category', [])
