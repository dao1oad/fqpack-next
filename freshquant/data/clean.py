# -*- coding: utf-8 -*-

import pendulum
from loguru import logger

from freshquant.assets.opening_amounts import clean_old_opening_amounts
from freshquant.carnation.config import STOCK_ORDER_QUEUE
from freshquant.data.astock.holding import clean_stock_fills, compact_stock_fills
from freshquant.database.redis import redis_db
from freshquant.db import DBfreshquant
from freshquant.pool.general import cleanMustPool
from freshquant.position.cn_future import cleanCnFutureXtTrades
from freshquant.trade.trade import cleanInstrumentStrategy


def clean_db():
    DBfreshquant["stock_pre_pools"].delete_many({"expire_at": {"$lt": pendulum.now()}})
    DBfreshquant["stock_pools"].delete_many({"expire_at": {"$lt": pendulum.now()}})
    DBfreshquant["stock_factors"].delete_many(
        {"datetime": {"$lt": pendulum.now().add(days=-365)}}
    )
    DBfreshquant["stock_signals"].delete_many(
        {"fire_time": {"$lt": pendulum.now().add(days=-365)}}
    )
    DBfreshquant["index_score"].delete_many(
        {"date": {"$lt": pendulum.now().add(days=-365).format("YYYY-MM-DD")}}
    )
    DBfreshquant["stock_score"].delete_many(
        {"date": {"$lt": pendulum.now().add(days=-365).format("YYYY-MM-DD")}}
    )
    DBfreshquant["stock_realtime"].delete_many({})
    DBfreshquant["future_realtime"].delete_many({})
    clean_stock_fills()
    compact_stock_fills()
    DBfreshquant["stock_orders"].delete_many(
        {"date": {"$lt": int(pendulum.now().add(days=-7).format("YYYYMMDD"))}}
    )
    DBfreshquant["xt_orders"].delete_many(
        {"ordered_time": {"$lt": int(pendulum.now().add(years=-3).timestamp())}}
    )
    DBfreshquant["xt_trades"].delete_many(
        {"traded_time": {"$lt": int(pendulum.now().add(years=-3).timestamp())}}
    )
    cleanInstrumentStrategy()
    # 清理期货交易记录
    positions = cleanCnFutureXtTrades()
    logger.info(positions)
    cleanMustPool()
    # 清空下单队列
    redis_db.delete(STOCK_ORDER_QUEUE)

    # 清理开盘金额历史数据
    deleted_count = clean_old_opening_amounts()
    logger.info(f"清理开盘金额历史数据，删除 {deleted_count} 条记录")
