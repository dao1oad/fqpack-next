# coding=utf-8

import json
from datetime import datetime

import pendulum
from dagster import op
from loguru import logger

import freshquant.carnation.xtconstant as xtconstant
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.database.redis import redis_db
from freshquant.db import DBfreshquant
from freshquant.pool.general import queryMustPoolCodes
from freshquant.strategy import ORDER_QUEUE
from freshquant.trade.trade import do_reverse_repo
from freshquant.trading.dt import fq_trading_fetch_trade_dates, query_prev_trade_date


@op
def op_reverse_repo(context):
    context.log.info("执行国债逆回购")
    do_reverse_repo()


@op
def op_backfill_order(context):
    """补单的意思：
    1. 如果昨天有卖出信号，但是没有成交，那么今天就按昨天的信号价格补单。
    """
    context.log.info("补单")
    prev_trade_date = query_prev_trade_date()
    xt_orders = list(
        DBfreshquant["xt_orders"].find(
            {
                "order_time": {
                    "$gte": datetime.combine(
                        prev_trade_date, datetime.min.time()
                    ).timestamp()
                },
                "order_status": xtconstant.ORDER_REPORTED,
                "order_type": {"$in": [xtconstant.STOCK_BUY, xtconstant.STOCK_SELL]},
            },
        )
    )
    if len(xt_orders) == 0:
        return
    holdingCodes = get_stock_holding_codes()
    mustPoolCodes = queryMustPoolCodes()
    # 预先计算三个连续交易日的时间戳
    trade_dates = fq_trading_fetch_trade_dates()
    last_three_trade_dates = trade_dates[
        trade_dates['trade_date'] < datetime.now().date()
    ].tail(3)
    three_trade_days_ago = last_three_trade_dates.iloc[0]['trade_date']
    three_trade_days_ago_ts = pendulum.datetime(
        three_trade_days_ago.year, three_trade_days_ago.month, three_trade_days_ago.day
    ).timestamp()

    for xt_order in xt_orders:
        stock_code = xt_order["stock_code"]
        # 检查最近三个连续交易日是否有订单

        recent_orders = list(
            DBfreshquant["xt_orders"]
            .find(
                {
                    "stock_code": stock_code,
                    "order_time": {"$gte": three_trade_days_ago_ts},
                    "order_status": xtconstant.ORDER_REPORTED,
                    "order_type": {
                        "$in": [xtconstant.STOCK_BUY, xtconstant.STOCK_SELL]
                    },
                }
            )
            .sort("order_time", -1)
            .limit(3)
        )

        if len(recent_orders) >= 3:
            context.log.info(f"股票{stock_code}存在最近三次未成交订单，跳过补单")
            continue

        strategy_name = xt_order["strategy_name"]
        price = xt_order["price"]
        orderType = xt_order["order_type"]
        orderVolume = xt_order["order_volume"]
        if stock_code[:6] in holdingCodes or stock_code[:6] in mustPoolCodes:
            message = {
                "action": "buy" if orderType == xtconstant.STOCK_BUY else "sell",
                "symbol": stock_code[:6],
                "price": price,
                "quantity": orderVolume,
                "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                "strategy_name": strategy_name,
            }
            logger.info(message)
            redis_db.lpush(ORDER_QUEUE, json.dumps(message))
