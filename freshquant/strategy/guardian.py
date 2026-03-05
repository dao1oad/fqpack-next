import json
from datetime import datetime, timedelta

import pendulum
import pymongo
from blinker import signal
from loguru import logger

import freshquant.util.datetime_helper as datetime_helper
from freshquant.basic.singleton_type import SingletonType
from freshquant.carnation.config import STOCK_ORDER_QUEUE
from freshquant.data.astock.holding import (
    get_arranged_stock_fill_list,
    get_stock_holding_codes,
)
from freshquant.database.redis import redis_db
from freshquant.db import DBfreshquant
from freshquant.ordering.general import query_strategy_id
from freshquant.pool.general import queryMustPoolCodes
from freshquant.position.stock import query_stock_position_pct
from freshquant.strategy.common import get_auto_open, get_position_pct, get_trade_amount
from freshquant.strategy.toolkit.threshold import eval_stock_threshold_price
from freshquant.util.code import fq_util_code_append_market_code_suffix
from freshquant.util.datetime_helper import fq_util_datetime_localize

order_alert = signal("order_alert")


class StrategyGuardian(metaclass=SingletonType):
    def on_signal(self, signal):

        # 当天有买入卖出交易的时候，不触发买入，防止频繁交易
        code = signal["code"]
        name = signal["name"]
        fire_time = signal["fire_time"]
        discover_time = signal.setdefault("discover_time", datetime_helper.now())
        position = signal["position"]
        price = signal["price"]
        period = signal["period"]
        remark = signal["remark"]
        tags = signal["tags"] or []
        zsdata = signal["zsdata"]
        fills = signal["fills"]

        stock_code = fq_util_code_append_market_code_suffix(code, upper_case=True)
        position_pct = query_stock_position_pct(True)

        if position == "BUY_LONG":
            last_sell_trades = list(
                DBfreshquant["xt_trades"]
                .find(
                    {
                        "stock_code": stock_code,
                    }
                )
                .sort("traded_time", pymongo.DESCENDING)
                .limit(1)
            )
            last_sell_trade = last_sell_trades[0] if len(last_sell_trades) > 0 else None
            if last_sell_trade is not None:
                if (
                    last_sell_trade["traded_time"]
                    > pendulum.now().start_of("day").timestamp()
                ):
                    logger.info(
                        f"{stock_code} 当天有买入卖出交易的时候，不触发买入，防止频繁交易"
                    )
                    return

        holdingCodes = get_stock_holding_codes()
        mustPoolCodes = queryMustPoolCodes()

        log_data = {
            "code": code,
            "name": name,
            "position": position,
            "period": period,
            "price": price,
            "remark": remark,
            "fire_time": fire_time.strftime("%Y-%m-%d %H:%M:%S"),
            "discover_time": discover_time.strftime("%Y-%m-%d %H:%M:%S"),
            "title": f'{"买点通知" if position == "BUY_LONG" else "卖点通知"} {code} {name}',
        }
        logger.info(json.dumps(log_data, ensure_ascii=False))

        if code in holdingCodes or code in mustPoolCodes:
            if fire_time < pendulum.now().add(minutes=-30):
                logger.info(
                    "{code} {name} 超过30分钟，跳过下单指令", code=code, name=name
                )
                return
            if position_pct is None:
                logger.info(
                    "{code} {name} 不知道持仓比例，跳过下单指令", code=code, name=name
                )
                return
            fillList = get_arranged_stock_fill_list(code)
            last_fill = None
            if fillList is not None and len(fillList) > 0:
                last_fill = (
                    fillList[-1] if fillList is not None and len(fillList) > 0 else None
                )
            dt = None
            last_fill_price = None
            if last_fill is not None:
                dt = datetime.strptime(
                    "%s %s" % (str(last_fill["date"]), last_fill["time"]),
                    "%Y%m%d %H:%M:%S",
                )
                dt = fq_util_datetime_localize(dt)
                last_fill_price = last_fill["price"]
            if dt is not None and fire_time < dt:
                logger.info("触发时间异常，跳过下单指令")
                return
            if position == "BUY_LONG":
                if (
                    last_fill_price is not None
                    and price
                    > eval_stock_threshold_price(code, last_fill_price)[
                        "bot_river_price"
                    ]
                ):
                    logger.info("触发价格未达，跳过下单指令")
                    return
                # 判断买点节奏（就是有没有相隔至少一个中枢）
                if fills is not None and len(fills) > 0:
                    fill_time = str(fills[-1]["date"]) + " " + fills[-1]["time"]
                    fill_time = datetime.strptime(fill_time, "%Y%m%d %H:%M:%S").replace(
                        tzinfo=pendulum.local_timezone()
                    )
                    if zsdata is None or len(zsdata) == 0:
                        logger.info(
                            "{code} {name} 没有中枢，跳过下单指令", code=code, name=name
                        )
                        return
                    fire_signal = False
                    for zs in reversed(zsdata):
                        zs_start = datetime.strptime(
                            zs[0][0], "%Y-%m-%d %H:%M"
                        ).replace(tzinfo=pendulum.local_timezone())
                        zs_end = datetime.strptime(zs[1][0], "%Y-%m-%d %H:%M").replace(
                            tzinfo=pendulum.local_timezone()
                        )
                        if (
                            fire_time >= zs_end
                            and fill_time <= zs_start
                            and fills[-1]["price"] > zs[0][1]
                            and fills[-1]["price"] > zs[1][1]
                        ):
                            fire_signal = True
                            break
                    if not fire_signal:
                        logger.info(
                            "{code} {name} 无相隔中枢，跳过下单指令",
                            code=code,
                            name=name,
                        )
                        return
                # 下买入订单
                tradeAmount = get_trade_amount(stock_code)
                if position_pct >= 60 and position_pct < 80:
                    tradeAmount = tradeAmount * 2 / 3
                elif position_pct >= 80:
                    tradeAmount = tradeAmount / 3
                if "near_pattern:descending" in tags:
                    tradeAmount = tradeAmount / 3
                elif (
                    "near_pattern:contracting" in tags
                    or "near_pattern:spreading" in tags
                ):
                    tradeAmount = tradeAmount * 2 / 3
                quantity = int(tradeAmount / price / 100) * 100
                if quantity == 0:
                    quantity = 100
                signal["quantity"] = quantity
                if redis_db.get(f"buy:{code}") is None:
                    logger.info("下买入订单")
                    redis_db.set(f"buy:{code}", "1", timedelta(minutes=15))
                    redis_db.lpush(
                        STOCK_ORDER_QUEUE,
                        json.dumps(
                            {
                                "action": "buy",
                                "symbol": code,
                                "price": price,
                                "quantity": quantity,
                                "fire_time": pendulum.now().format(
                                    "YYYY-MM-DD hh:mm:ss"
                                ),
                                "strategy_name": query_strategy_id("Guardian"),
                            }
                        ),
                    )
            elif position == "SELL_SHORT":
                if last_fill is None:
                    logger.info("无持仓，跳过下单指令")
                    return
                is_skip = (
                    last_fill_price is not None
                    and price
                    < eval_stock_threshold_price(code, last_fill_price)[
                        "top_river_price"
                    ]
                )
                # 如果仓位>=90%，不需要判断是否获利
                is_force = False
                if is_skip:
                    if query_stock_position_pct() >= 90:
                        is_skip = False
                        is_force = True
                if is_skip:
                    logger.info("条件未达，跳过下单指令")
                    return
                # 下卖出订单
                quantity = 0
                if quantity <= 0:
                    if not is_force:
                        for i in range(len(fillList) - 1, -1, -1):
                            if price > fillList[i]["price"]:
                                quantity = quantity + fillList[i]["quantity"]
                            else:
                                break
                    else:
                        for i in range(len(fillList) - 1, -1, -1):
                            quantity = fillList[i]["quantity"]
                            break
                if quantity > 0:
                    signal["quantity"] = quantity
                    if redis_db.get(f"sell:{code}") is None:
                        logger.info("下卖出订单")
                        if is_force:
                            # 强制卖出的三天内不再自动卖出，防止单个股票卖出太多
                            redis_db.set(f"sell:{code}", "1", timedelta(days=3))
                        else:
                            redis_db.set(f"sell:{code}", "1", timedelta(minutes=15))
                        redis_db.lpush(
                            STOCK_ORDER_QUEUE,
                            json.dumps(
                                {
                                    "action": "sell",
                                    "symbol": code,
                                    "price": price,
                                    "quantity": quantity,
                                    "fire_time": pendulum.now().format(
                                        "YYYY-MM-DD hh:mm:ss"
                                    ),
                                    "strategy_name": query_strategy_id("Guardian"),
                                }
                            ),
                        )
        elif (
            redis_db.get("fq:xtrade:last_new_order_time") is None
            and position == "BUY_LONG"
        ):
            if get_auto_open():
                if position_pct < get_position_pct() and get_auto_open():
                    tradeAmount = get_trade_amount(stock_code)
                    normal_quantity = int(tradeAmount / price / 100) * 100
                    if position_pct >= 60 and position_pct < 80:
                        tradeAmount = tradeAmount * 2 / 3
                    elif position_pct >= 80:
                        tradeAmount = tradeAmount / 3
                    if "near_pattern:descending" in tags:
                        tradeAmount = tradeAmount / 3
                    elif (
                        "near_pattern:contracting" in tags
                        or "near_pattern:spreading" in tags
                    ):
                        tradeAmount = tradeAmount * 2 / 3
                    quantity = int(tradeAmount / price / 100) * 100
                    if quantity == 0:
                        quantity = normal_quantity
                    if quantity > 0:
                        signal["quantity"] = quantity
                        redis_db.set(
                            "fq:xtrade:last_new_order_time",
                            pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                            timedelta(minutes=15),
                        )
                        buy_order_payload = json.dumps(
                            {
                                "action": "buy",
                                "symbol": code,
                                "price": price,
                                "quantity": quantity,
                                "fire_time": pendulum.now().format(
                                    "YYYY-MM-DD hh:mm:ss"
                                ),
                                "strategy_name": query_strategy_id("Guardian"),
                            }
                        )
                        logger.info("下买单: " + buy_order_payload)
                        redis_db.lpush(STOCK_ORDER_QUEUE, buy_order_payload)
                    else:
                        logger.info("可交易额度不足，不再自动买入")
                else:
                    logger.info("持仓比例达到阈值，不再自动买入")
            else:
                logger.info("持仓信息获取失败，不再自动买入")
        else:
            if position == "BUY_LONG":
                last_new_order_time = redis_db.get("fq:xtrade:last_new_order_time")
                logger.info(
                    f"上次下单时间未超过15分钟，不再自动买入{last_new_order_time}"
                )

        if code in holdingCodes or code in mustPoolCodes:
            order_alert.send("guardian", private=True, payload=signal)
        else:
            if position == "BUY_LONG":
                order_alert.send("guardian", payload=signal)


def test_order_alert_signal():
    # 创建测试信号数据
    test_signal = {
        "code": "TEST001",
        "name": "测试股票",
        "period": "1m",
        "position": "BUY_LONG",
        "price": 10.0,
        "fire_time": pendulum.now(),
        "tags": ["test"],
        "zsdata": [],
        "fills": [],
    }

    order_alert.send("guardian", payload=test_signal)
    order_alert.send("guardian", private=True, payload=test_signal)


if __name__ == "__main__":
    # 运行测试
    test_order_alert_signal()

    last_sell_trades = list(
        DBfreshquant["xt_trades"]
        .find({"stock_code": "300681.SZ", "order_type": 24})
        .sort("traded_time", pymongo.DESCENDING)
        .limit(1)
    )
    last_sell_trade = last_sell_trades[0] if len(last_sell_trades) > 0 else None
    if last_sell_trade is not None:
        if last_sell_trade["traded_time"] > pendulum.now().start_of("day").timestamp():
            logger.info("300681.SZ 当天有买入卖出交易的时候，不触发买入，防止频繁交易")
