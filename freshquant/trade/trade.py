# coding=utf-8

import json
import pendulum
import pydash
from datetime import datetime
from loguru import logger

from freshquant.carnation import xtconstant
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.database.cache import in_memory_cache
from freshquant.database.redis import redis_db
from freshquant.db import DBfreshquant
from freshquant.ordering.general import query_strategy_id
from freshquant.strategy import ORDER_QUEUE
from freshquant.strategy.common import get_trade_amount
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from freshquant.util.code import fq_util_code_append_market_code_suffix


def calculateTradeFee(
    price: float, quantity: int, feeRate: float = 0.001, startingFee: float = 5.0
) -> float:
    """
    Calculate the fee for a trade.
    :param price: Price of the trade.
    :param quantity: Quantity of the trade.
    :param feeRate: Fee rate of the trade.
    :return: Fee for the trade.
    """
    return float(price) * float(quantity) * float(feeRate) + float(startingFee)


@in_memory_cache.memoize(expiration=864000)
def checkManualStrategyInstument(instumentCode: str) -> bool:
    one = DBfreshquant["instrument_strategy"].find_one(
        {
            "instrument_code": instumentCode,
            "strategy_name": query_strategy_id("Manual"),
        }
    )
    if one is not None:
        return True
    return False


def saveInstrumentStrategy(instrumentCode: str, instrumentType: str, strategyName: str):
    now = pendulum.now()
    lotAmount = get_trade_amount(instrumentCode)
    DBfreshquant["instrument_strategy"].update_one(
        {
            "instrument_code": instrumentCode,
        },
        {
            "$set": {
                "update_time": int(now.timestamp()),
                "update_time_str": now.to_datetime_string(),
            },
            "$setOnInsert": {
                "instrument_code": instrumentCode,
                "instrument_type": instrumentType,
                "strategy_name": strategyName,
                "lot_amount": lotAmount,
            },
        },
        upsert=True,
    )


def do_reverse_repo():
    """执行国债逆回购操作
    根据距离下一个交易日的天数选择合适的逆回购品种并发送订单
    """
    # 选择逆回购代码
    codes = [
        {"days": 1, "code": "204001.SH"},
        {"days": 2, "code": "204002.SH"},
        {"days": 3, "code": "204003.SH"},
        {"days": 4, "code": "204004.SH"},
        {"days": 7, "code": "204007.SH"},
        {"days": 14, "code": "204014.SH"},
        {"days": 1, "code": "131810.SZ"},
        {"days": 2, "code": "131811.SZ"},
        {"days": 3, "code": "131800.SZ"},
        {"days": 4, "code": "131809.SZ"},
        {"days": 7, "code": "131801.SZ"},
        {"days": 14, "code": "131802.SZ"},
    ]
    
    trade_dates = fq_trading_fetch_trade_dates()
    future_trade_dates = trade_dates[trade_dates['trade_date'] > datetime.now().date()]
    future_trade_date = future_trade_dates["trade_date"].head(1)  
    future_trade_date_str = future_trade_date.iloc[0].strftime("%Y-%m-%d")
    future_trade_date_datetime = datetime.strptime(future_trade_date_str, "%Y-%m-%d")
    days_until_future_trade_date = (future_trade_date_datetime.date() - datetime.now().date()).days

    code = "204001.SH"
    for item in codes:
        if days_until_future_trade_date < item["days"]:
            break
        code = item["code"]

    # 发送订单
    asset = DBfreshquant["xt_assets"].find_one({})
    if not asset:
        logger.warning("未找到资产信息，无法进行逆回购操作")
        return
        
    cash = asset["cash"] - 20000
    quantity = int(cash / 1000) * 10
    if quantity > 0:
        redis_db.lpush(
            ORDER_QUEUE,
            json.dumps(
                {
                    "action": "sell",
                    "symbol": code,
                    "price": 0,
                    "quantity": quantity,
                    "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                    "price_type": xtconstant.LATEST_PRICE,
                    "strategy_name": query_strategy_id("Guardian"),
                }
            ),
        )
    else:
        logger.warning("可用资金不足，无法进行逆回购操作")

def cleanInstrumentStrategy():
    codes = get_stock_holding_codes()
    instrumentCodes = (
        pydash.chain(codes)
        .map(lambda code: fq_util_code_append_market_code_suffix(code, True))
        .value()
    )
    DBfreshquant["instrument_strategy"].delete_many(
        {
            "instrument_code": {"$nin": instrumentCodes},
        }
    )
