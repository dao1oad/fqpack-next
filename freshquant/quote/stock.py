# -*- coding: utf-8 -*-

from QUANTAXIS import QA_fetch_stock_day_adv
from freshquant.database.cache import redis_cache

@redis_cache.memoize(expiration=900)
def fq_quote_QA_fetch_stock_day_adv(code, start, end):
    data = QA_fetch_stock_day_adv(code, start, end)
    if data is not None:
        return data.to_qfq().data
    return