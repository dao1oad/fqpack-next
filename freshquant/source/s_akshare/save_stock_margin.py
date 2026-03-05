# -*- coding:utf-8 -*-

from datetime import timedelta
from time import sleep

import pendulum
import pymongo

from freshquant.database.redis import redis_db
from freshquant.db import DBfreshquant
from freshquant.fq_akshare.stock_feature.stock_sse_margin import (
    stock_margin_detail_sse,
    stock_margin_sse,
)
from freshquant.fq_akshare.stock_feature.stock_szse_margin import (
    stock_margin_detail_szse,
    stock_margin_szse,
)


def fq_save_stock_margin_sse():
    # 上海证券交易所融资融券汇总
    start_date = redis_db.get('fq_save_stock_margin_sse')
    if not start_date:
        start_date = pendulum.now().subtract(days=60).format("YYYYMMDD")
    end_date = pendulum.now().format("YYYYMMDD")
    if start_date >= end_date:
        return
    stock_margin_sse_df = stock_margin_sse(start_date=start_date, end_date=end_date)
    stock_margin_sse_df.rename(
        columns={
            "信用交易日期": "ri_qi",
            "融资余额": "rong_zi_yu_e",
            "融资买入额": "rong_zi_mai_ru_e",
            "融券余量": "rong_quan_yu_liang",
            "融券余量金额": "rong_quan_yu_e",
            "融券卖出量": "rong_quan_mai_chu_liang",
            "融资融券余额": "rong_zi_rong_quan_yu_e",
        },
        inplace=True,
    )
    stock_margin_sse_df["exchange"] = "sse"
    records = stock_margin_sse_df.to_dict(orient='records')
    collection = DBfreshquant['stock_margin']
    indexes = collection.index_information()
    if "idx_ri_qi_exchange" not in indexes:
        collection.create_index(
            [
                ('ri_qi', pymongo.ASCENDING),
                ('exchange', pymongo.ASCENDING),
            ],
            unique=True,
            name="idx_ri_qi_exchange",
        )
    if len(records) > 0:
        collection.insert_many(records)
    redis_db.set('fq_save_stock_margin_sse', end_date, timedelta(days=60))


def fq_save_stock_margin_detail_sse():
    # 上海证券交易所融资融券明细
    start_date = redis_db.get('fq_save_stock_margin_detail_sse')
    if not start_date:
        start_date = pendulum.now().subtract(days=60).format("YYYYMMDD")
    end_date = pendulum.now().format("YYYYMMDD")
    if start_date >= end_date:
        return
    period = pendulum.period(pendulum.parse(start_date), pendulum.parse(end_date))
    collection = DBfreshquant['stock_margin_detail']
    indexes = collection.index_information()
    if "idx_ri_qi_dai_ma_exchange" not in indexes:
        collection.create_index(
            [
                ('ri_qi', pymongo.ASCENDING),
                ('dai_ma', pymongo.ASCENDING),
                ('exchange', pymongo.ASCENDING),
            ],
            unique=True,
            name="idx_ri_qi_dai_ma_exchange",
        )
    for dt in period.range('days'):
        stock_margin_detail_sse_df = stock_margin_detail_sse(date=dt.format("YYYYMMDD"))
        stock_margin_detail_sse_df.rename(
            columns={
                "信用交易日期": "ri_qi",
                "标的证券代码": "dai_ma",
                "标的证券简称": "ming_cheng",
                "融资余额": "rong_zi_yu_e",
                "融资买入额": "rong_zi_mai_ru_e",
                "融资偿还额": "rong_zi_chang_huan_e",
                "融券余量": "rong_quan_yu_liang",
                "融券卖出量": "rong_quan_mai_chu_liang",
                "融券偿还量": "rong_quan_chang_huan_liang",
            },
            inplace=True,
        )
        stock_margin_detail_sse_df["exchange"] = "sse"
        records = stock_margin_detail_sse_df.to_dict(orient='records')
        if len(records) > 0:
            collection.insert_many(records)
        redis_db.set(
            'fq_save_stock_margin_detail_sse', dt.format("YYYYMMDD"), timedelta(days=60)
        )
        sleep(3)


def fq_save_stock_margin_szse():
    # 深圳证券交易所融资融券汇总
    start_date = redis_db.get('fq_save_stock_margin_szse')
    if not start_date:
        start_date = pendulum.now().subtract(days=60).format("YYYYMMDD")
    end_date = pendulum.now().format("YYYYMMDD")
    if start_date >= end_date:
        return
    if not start_date:
        start_date = pendulum.now().subtract(days=60).format("YYYYMMDD")
    period = pendulum.period(pendulum.parse(start_date), pendulum.parse(end_date))
    collection = DBfreshquant['stock_margin']
    indexes = collection.index_information()
    if "idx_ri_qi_exchange" not in indexes:
        collection.create_index(
            [
                ('ri_qi', pymongo.ASCENDING),
                ('exchange', pymongo.ASCENDING),
            ],
            unique=True,
            name="idx_ri_qi_exchange",
        )
    for dt in period.range('days'):
        stock_margin_szse_df = stock_margin_szse(date=dt.format("YYYYMMDD"))
        stock_margin_szse_df["ri_qi"] = dt.format("YYYYMMDD")
        stock_margin_szse_df.rename(
            columns={
                "融资余额": "rong_zi_yu_e",
                "融资买入额": "rong_zi_mai_ru_e",
                "融券余量": "rong_quan_yu_liang",
                "融券卖出量": "rong_quan_mai_chu_liang",
                "融资融券余额": "rong_zi_rong_quan_yu_e",
            },
            inplace=True,
        )
        stock_margin_szse_df["exchange"] = "szse"
        records = stock_margin_szse_df.to_dict(orient='records')
        if len(records) > 0:
            collection.insert_many(records)
        redis_db.set(
            'fq_save_stock_margin_szse', dt.format("YYYYMMDD"), timedelta(days=60)
        )
        sleep(3)


def fq_save_stock_margin_detail_szse():
    # 深圳证券交易所融资融券明细
    start_date = redis_db.get('fq_save_stock_margin_detail_szse')
    if not start_date:
        start_date = pendulum.now().subtract(days=60).format("YYYYMMDD")
    end_date = pendulum.now().format("YYYYMMDD")
    if start_date >= end_date:
        return
    period = pendulum.period(pendulum.parse(start_date), pendulum.parse(end_date))
    collection = DBfreshquant['stock_margin_detail']
    indexes = collection.index_information()
    if "idx_ri_qi_dai_ma_exchange" not in indexes:
        collection.create_index(
            [
                ('ri_qi', pymongo.ASCENDING),
                ('dai_ma', pymongo.ASCENDING),
                ('exchange', pymongo.ASCENDING),
            ],
            unique=True,
            name="idx_ri_qi_dai_ma_exchange",
        )
    for dt in period.range('days'):
        stock_margin_detail_szse_df = stock_margin_detail_szse(
            date=dt.format("YYYYMMDD")
        )
        stock_margin_detail_szse_df["ri_qi"] = dt.format("YYYYMMDD")
        stock_margin_detail_szse_df.rename(
            columns={
                "证券代码": "dai_ma",
                "证券简称": "ming_cheng",
                "融资余额": "rong_zi_yu_e",
                "融资买入额": "rong_zi_mai_ru_e",
                "融券余量": "rong_quan_yu_liang",
                "融券卖出量": "rong_quan_mai_chu_liang",
                "融券余额": "rong_quan_yu_e",
                "融资融券余额": "rong_zi_rong_quan_yu_e",
            },
            inplace=True,
        )
        stock_margin_detail_szse_df["exchange"] = "szse"
        records = stock_margin_detail_szse_df.to_dict(orient='records')
        if len(records) > 0:
            collection.insert_many(records)
        redis_db.set(
            'fq_save_stock_margin_detail_szse',
            dt.format("YYYYMMDD"),
            timedelta(days=60),
        )
        sleep(3)


def run():
    fq_save_stock_margin_sse()
    fq_save_stock_margin_detail_sse()
    fq_save_stock_margin_szse()
    fq_save_stock_margin_detail_szse()


if __name__ == "__main__":
    run()
