# -*- encoding:utf-8 -*-

import pandas as pd
import pendulum
import pymongo

from freshquant.db import DBfreshquant


def fq_fetch_stock_margin_detail(start=None, end=None):
    if not start:
        start = pendulum.now().subtract(days=60).format("YYYYMMDD")
    if not end:
        end = pendulum.now().format("YYYYMMDD")
    collection = DBfreshquant["stock_margin_detail"]
    list = collection.find({"ri_qi": {"$gte": start, "$lte": end}}, {"_id": 0}).sort(
        [("dai_ma", pymongo.ASCENDING), ("ri_qi", pymongo.ASCENDING)]
    )
    return pd.DataFrame(list)
