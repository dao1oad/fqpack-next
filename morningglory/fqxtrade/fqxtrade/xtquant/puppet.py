import json
import time

import pendulum
import pydash
from fqxtrade import ORDER_QUEUE
from fqxtrade.database.mongodb import DBfreshquant
from fqxtrade.database.redis import redis_db
from fqxtrade.xtquant.fqtype import FqXtAsset, FqXtOrder, FqXtPosition, FqXtTrade
from fqxtrade.xtquant.lock import redis_distributed_lock
from fqxtrade.xtquant.trading_manager import TradingManager
from loguru import logger
from pymongo import UpdateOne
from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from xtquant import xtconstant, xtdata

from freshquant.instrument.bond import REPO_CODE_LIST
from freshquant.instrument.general import query_instrument_info
from freshquant.order_management.ingest.xt_reports import (
    try_ingest_xt_order_dict,
    try_ingest_xt_trade_dict,
)
from freshquant.order_management.reconcile.service import ExternalOrderReconcileService
from freshquant.ordering.general import query_strategy_id
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.trade.trade import calculateTradeFee, saveInstrumentStrategy
from freshquant.util.code import fq_util_code_append_market_code_suffix
from freshquant.util.xtquant import translate_account_type, translate_order_type

trading_manager = TradingManager()
external_reconcile_service = ExternalOrderReconcileService()
BUY_ORDER_TYPES = {
    xtconstant.STOCK_BUY,
    xtconstant.CREDIT_BUY,
    xtconstant.CREDIT_FIN_BUY,
}
SELL_ORDER_TYPES = {
    xtconstant.STOCK_SELL,
    xtconstant.CREDIT_SELL,
    xtconstant.CREDIT_SELL_SECU_REPAY,
}


def saveTrades(trades):
    trades = pydash.filter_(trades, lambda x: x.stock_code not in REPO_CODE_LIST)
    batch = []
    for trade in trades:
        batch.append(
            UpdateOne(
                {
                    "account_id": trade.account_id,
                    "traded_id": trade.traded_id,
                },
                {"$set": FqXtTrade(trade).to_dict()},
                upsert=True,
            )
        )
    if len(batch) > 0:
        DBfreshquant["xt_trades"].bulk_write(batch)
    for trade in trades:
        trade_dict = FqXtTrade(trade).to_dict()
        reconciled = external_reconcile_service.reconcile_trade_reports([trade_dict])
        if not reconciled:
            try_ingest_xt_trade_dict(trade_dict)
    trades = pydash.filter_(trades, lambda x: x.order_type in BUY_ORDER_TYPES)
    trades = pydash.uniq_by(trades, lambda x: x.stock_code)
    for trade in trades:
        saveInstrumentStrategy(
            trade.stock_code,
            "stock",
            (
                query_strategy_id("Gardian")
                if trade.strategy_name is None or trade.strategy_name == ""
                else trade.strategy_name
            ),
        )
    trades = list(
        DBfreshquant["xt_trades"].find(
            {"traded_time": {"$gte": int(pendulum.today().timestamp())}}
        )
    )

    def groupByTrades(trade):
        # "date", "stock_code", "order_type", "price"
        # 同一天的同个价位成交的合并在一起
        tradedTime = pendulum.from_timestamp(
            trade["traded_time"], tz=pendulum.local_timezone()
        )
        date = int(tradedTime.format("YYYYMMDD"))
        stock_code = trade["stock_code"]
        order_type = trade["order_type"]
        price = trade["traded_price"]
        return f'{date}, {stock_code}, {order_type}, {price}'

    tradesGroup = pydash.group_by(trades, lambda x: groupByTrades(x))
    batch = []
    for value in tradesGroup.values():
        tradedTime = pendulum.from_timestamp(
            value[-1]["traded_time"], tz=pendulum.local_timezone()
        )
        date = int(tradedTime.format("YYYYMMDD"))
        strTime = tradedTime.to_time_string()
        symbol = value[-1]["stock_code"][0:6]
        stock_code = value[-1]["stock_code"]
        instrumentInfo = query_instrument_info(symbol)
        name = pydash.get(instrumentInfo, "name")
        op = "买" if value[-1]["order_type"] == xtconstant.STOCK_BUY else "卖"
        op = "买" if value[-1]["order_type"] in BUY_ORDER_TYPES else "卖"
        quantity = pydash.sum_([item["traded_volume"] for item in value])
        price = value[-1]["traded_price"]
        amount = pydash.sum_([item["traded_amount"] for item in value])
        source = "deal"
        batch.append(
            UpdateOne(
                {
                    "date": date,
                    "symbol": symbol,
                    "op": op,
                    "price": price,
                },
                {
                    "$set": {
                        "date": date,
                        "time": strTime,
                        "symbol": symbol,
                        "stock_code": stock_code,
                        "name": name,
                        "op": op,
                        "quantity": quantity,
                        "price": price,
                        "amount": amount,
                        "source": source,
                        "traded_ids": [item["traded_id"] for item in value],
                    }
                },
                upsert=True,
            )
        )
    if len(batch) > 0:
        DBfreshquant["stock_fills"].bulk_write(batch)


def sync_trades():
    """线程与进程安全的成交同步函数"""
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            return None
        lock_key = f"lock:sync_trades:{acc}"
        while True:
            with redis_distributed_lock(lock_key) as acquired:
                if acquired:  # 查询当日所有的成交
                    trades = xt_trader.query_stock_trades(acc)
                    if trades is not None and len(trades) > 0:
                        # 创建Rich表格
                        table = Table(
                            show_header=True,
                            header_style="bold magenta",
                            show_lines=True,
                            title="成交记录",
                            title_style="bold",
                        )

                        # 定义列样式
                        column_definitions = {
                            "账户ID": {"style": "dim", "overflow": "fold"},
                            "成交编号": {"overflow": "fold"},
                            "股票代码": {"overflow": "fold"},
                            "股票名称": {"overflow": "fold"},
                            "买卖方向": {"justify": "right", "overflow": "fold"},
                            "成交价格": {"justify": "right", "overflow": "fold"},
                            "成交数量": {"justify": "right", "overflow": "fold"},
                            "成交金额": {"justify": "right", "overflow": "fold"},
                            "成交时间": {"overflow": "fold"},
                            "策略名称": {"overflow": "fold"},
                        }

                        # 添加列
                        for field in column_definitions:
                            table.add_column(field, **column_definitions[field])

                        # 添加数据
                        for trade in trades:
                            trade_dict = FqXtTrade(trade).to_dict()
                            instrument_info = query_instrument_info(
                                trade_dict.get("stock_code", "")[:6]
                            )
                            row_data = [
                                (
                                    lambda x: (
                                        x[: len(x) // 3]
                                        + '*' * (len(x) // 3)
                                        + x[-(len(x) - 2 * (len(x) // 3)) :]
                                        if len(x) >= 3
                                        else x
                                    )
                                )(str(trade_dict.get("account_id", ""))),
                                (
                                    lambda x: (
                                        x[: len(x) // 3]
                                        + '*' * (len(x) // 3)
                                        + x[-(len(x) - 2 * (len(x) // 3)) :]
                                        if len(x) >= 3
                                        else x
                                    )
                                )(str(trade_dict.get("traded_id", ""))),
                                str(trade_dict.get("stock_code", "")),
                                str(pydash.get(instrument_info, "name")),
                                str(
                                    translate_order_type(
                                        trade_dict.get("order_type", "")
                                    )
                                ),
                                f"{trade_dict.get('traded_price', 0):.2f}",
                                f"{trade_dict.get('traded_volume', 0)}",
                                f"{trade_dict.get('traded_amount', 0):.2f}",
                                pendulum.from_timestamp(
                                    trade_dict.get("traded_time", 0),
                                    tz=pendulum.local_timezone(),
                                ).format("YYYY-MM-DD HH:mm:ss"),
                                str(trade_dict.get("strategy_name", "")),
                            ]
                            table.add_row(*row_data)

                        # 打印表格
                        console = Console()
                        t = Padding(table, (1, 0, 0, 0))
                        console.print(t)
                        saveTrades(trades)
                        return trades.copy()  # 返回副本避免外部修改
                    else:
                        logger.info("当日无成交")
                        return None
            time.sleep(1)


def saveOrders(orders):
    batch = []
    for order in orders:
        batch.append(
            UpdateOne(
                {
                    "account_id": order.account_id,
                    "order_id": order.order_id,
                },
                {"$set": FqXtOrder(order).to_dict()},
                upsert=True,
            )
        )
    if len(batch) > 0:
        DBfreshquant["xt_orders"].bulk_write(batch)
    for order in orders:
        try_ingest_xt_order_dict(FqXtOrder(order).to_dict())
    batch = []
    for order in orders:
        orderTime = pendulum.from_timestamp(
            order.order_time, tz=pendulum.local_timezone()
        )
        date = int(orderTime.format("YYYYMMDD"))
        strTime = orderTime.to_time_string()
        short_code = order.stock_code[0:6]
        instrumentInfo = query_instrument_info(short_code)
        name = pydash.get(instrumentInfo, "name")
        op = "买" if order.order_type == xtconstant.STOCK_BUY else "卖"
        status = "未知"
        op = "买" if order.order_type in BUY_ORDER_TYPES else "卖"
        if order.order_status == xtconstant.ORDER_SUCCEEDED:
            status = "已成交"
        if order.order_status == xtconstant.ORDER_PART_SUCC:
            status = "部分成交"
        if order.order_status == xtconstant.ORDER_REPORTED:
            status = "未成交"
        batch.append(
            UpdateOne(
                {
                    "order_id": order.order_id,
                },
                {
                    "$set": {
                        "date": date,
                        "time": strTime,
                        "symbol": short_code,  # 以后删除这个，用stort_code代替
                        "short_code": short_code,
                        "stock_code": order.stock_code,
                        "name": name,
                        "op": op,
                        "status": status,
                        "order_qty": order.order_volume,
                        "quantity": order.order_volume,
                        "order_price": order.price,
                        "price": order.price,
                        "order_id": order.order_id,
                    }
                },
                upsert=True,
            )
        )
    if len(batch) > 0:
        DBfreshquant["stock_orders"].bulk_write(batch)


def sync_orders():
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            return None

        # 查询当日所有的委托
        orders = xt_trader.query_stock_orders(acc)
        if orders is not None and len(orders) > 0:
            # 创建Rich表格
            table = Table(
                show_header=True,
                header_style="bold magenta",
                show_lines=True,
                title="委托记录",
                title_style="bold",
            )

            # 定义列样式
            column_definitions = {
                "账户ID": {"style": "dim", "overflow": "fold"},
                "股票代码": {"overflow": "fold"},
                "股票名称": {"overflow": "fold"},
                "订单类型": {"justify": "right", "overflow": "fold"},
                "价格": {"justify": "right", "overflow": "fold"},
                "委托数量": {"justify": "right", "overflow": "fold"},
                "成交数量": {"justify": "right", "overflow": "fold"},
                "委托时间": {"overflow": "fold"},
                "策略名称": {"overflow": "fold"},
            }

            # 添加列
            for field in column_definitions:
                table.add_column(field, **column_definitions[field])

            # 添加数据
            for order in orders:
                order_dict = FqXtOrder(order).to_dict()
                instrument_info = query_instrument_info(
                    order_dict.get("stock_code", "")[:6]
                )
                row_data = [
                    (
                        lambda x: (
                            x[: len(x) // 3]
                            + '*' * (len(x) // 3)
                            + x[-(len(x) - 2 * (len(x) // 3)) :]
                            if len(x) >= 3
                            else x
                        )
                    )(str(order_dict.get("account_id", ""))),
                    str(order_dict.get("stock_code", "")),
                    pydash.get(instrument_info, "name"),
                    str(translate_order_type(order_dict.get("order_type", ""))),
                    f"{order_dict.get('price', 0):.2f}",
                    f"{order_dict.get('order_volume', 0)}",
                    f"{order_dict.get('traded_volume', 0)}",
                    pendulum.from_timestamp(
                        order_dict.get("order_time", 0), tz=pendulum.local_timezone()
                    ).format("YYYY-MM-DD HH:mm:ss"),
                    str(order_dict.get("strategy_name", "")),
                ]
                table.add_row(*row_data)

            # 打印表格
            console = Console()
            t = Padding(table, (1, 0, 0, 0))
            console.print(t)
            saveOrders(orders)
            return orders
        else:
            logger.info("当日无委托")
            return None


def saveAssets(assets):
    batch = []
    for asset in assets:
        batch.append(
            UpdateOne(
                {
                    "account_id": asset.account_id,
                },
                {"$set": FqXtAsset(asset).to_dict()},
                upsert=True,
            )
        )
    if len(batch) > 0:
        DBfreshquant["xt_assets"].bulk_write(batch)


def sync_summary():
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            return None
        # 查询证券资产
        asset = xt_trader.query_stock_asset(acc)
        if asset is not None:
            saveAssets([asset])
            asset = FqXtAsset(asset).to_dict()
            # 创建Rich表格
            table = Table(
                show_header=True,
                header_style="bold magenta",
                show_lines=True,
                title="资产概况",
                title_style="bold",
            )

            # 定义列样式
            table.add_column("账户ID", style="cyan", overflow="fold")
            table.add_column("账户类型", style="cyan", overflow="fold")
            table.add_column(
                "可用资金", justify="right", style="green", overflow="fold"
            )
            table.add_column(
                "冻结资金", justify="right", style="green", overflow="fold"
            )
            table.add_column("市值", justify="right", style="green", overflow="fold")
            table.add_column("总资产", justify="right", style="green", overflow="fold")
            table.add_column(
                "仓位比例", justify="right", style="green", overflow="fold"
            )

            # 添加资产数据
            table.add_row(
                (
                    lambda x: (
                        x[: len(x) // 3]
                        + '*' * (len(x) // 3)
                        + x[-(len(x) - 2 * (len(x) // 3)) :]
                        if len(x) >= 3
                        else x
                    )
                )(str(asset.get("account_id", ""))),
                str(translate_account_type(asset.get("account_type", ""))),
                f"{asset.get('cash', 0):.2f}",
                f"{asset.get('frozen_cash', 0):.2f}",
                f"{asset.get('market_value', 0):.2f}",
                f"{asset.get('total_asset', 0):.2f}",
                f"{asset.get('position_pct', 0):.2f}%",
            )

            # 打印表格
            console = Console()
            t = Padding(table, (1, 0, 0, 0))
            console.print(t)
            return asset
        else:
            return None


def savePositions(positions):
    batch = []
    stockCodes = []
    for position in positions:
        batch.append(
            UpdateOne(
                {
                    "account_id": position.account_id,
                    "stock_code": position.stock_code,
                },
                {"$set": FqXtPosition(position).to_dict()},
                upsert=True,
            )
        )
        stockCodes.append(position.stock_code)
    if len(batch) > 0:
        DBfreshquant["xt_positions"].bulk_write(batch)
        DBfreshquant["xt_positions"].delete_many({"stock_code": {"$nin": stockCodes}})


def sync_positions():
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            return None
        # 查询当日所有的持仓
        positions = xt_trader.query_stock_positions(acc)
        position_dicts = [FqXtPosition(position).to_dict() for position in positions]
        if len(positions) > 0:
            savePositions(positions)
            positions = position_dicts
            external_reconcile_service.reconcile_account(
                getattr(acc, "account_id", "unknown"),
                positions=position_dicts,
                now=int(time.time()),
            )
            # 创建Rich表格
            table = Table(
                show_header=True,
                header_style="bold magenta",
                show_lines=True,
                title="持仓记录",
                title_style="bold",
            )

            # 定义列样式
            column_definitions = {
                "账户ID": {"style": "dim", "overflow": "fold"},
                "股票代码": {"overflow": "fold"},
                "股票名称": {"overflow": "fold"},
                "持仓数量": {"justify": "right", "overflow": "fold"},
                "平均成本": {"justify": "right", "overflow": "fold"},
                "市值": {"justify": "right", "overflow": "fold"},
                "可用数量": {"justify": "right", "overflow": "fold"},
                "冻结数量": {"justify": "right", "overflow": "fold"},
                "在途数量": {"justify": "right", "overflow": "fold"},
                "昨日数量": {"justify": "right", "overflow": "fold"},
            }

            # 添加列
            for field in column_definitions:
                table.add_column(field, **column_definitions[field])

            # 添加数据
            for position in positions:
                instrument_info = query_instrument_info(
                    position.get("stock_code", "")[:6]
                )
                row_data = [
                    (
                        lambda x: (
                            x[: len(x) // 3]
                            + '*' * (len(x) // 3)
                            + x[-(len(x) - 2 * (len(x) // 3)) :]
                            if len(x) >= 3
                            else x
                        )
                    )(str(position.get("account_id", ""))),
                    str(position.get("stock_code", "")),
                    pydash.get(instrument_info, "name"),
                    f"{position.get('volume', 0)}",
                    f"{position.get('avg_price', 0):.2f}",
                    f"{position.get('market_value', 0):.2f}",
                    f"{position.get('can_use_volume', 0)}",
                    f"{position.get('frozen_volume', 0)}",
                    f"{position.get('on_road_volume', 0)}",
                    f"{position.get('yesterday_volume', 0)}",
                ]
                table.add_row(*row_data)

            # 打印表格
            console = Console()
            t = Padding(table, (1, 0, 0, 0))
            console.print(t)
            return positions
        else:
            external_reconcile_service.reconcile_account(
                getattr(acc, "account_id", "unknown"),
                positions=position_dicts,
                now=int(time.time()),
            )
            logger.info("当前无持仓")
            return None


def buy(
    symbol: str,
    price: float,
    quantity: int,
    strategyName="N/A",
    remark="N/A",
    retryCount=0,
    order_type=None,
    price_type=None,
    trace_id=None,
    intent_id=None,
    request_id=None,
    internal_order_id=None,
):
    context = {
        "trace_id": trace_id,
        "intent_id": intent_id,
        "request_id": request_id,
        "internal_order_id": internal_order_id,
        "symbol": symbol,
        "action": "buy",
    }
    _emit_puppet_event(
        "submit_prepare",
        context=context,
        payload={"price": float(price), "quantity": int(quantity), "retry_count": retryCount},
    )
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            _emit_puppet_event(
                "submit_result",
                context=context,
                status="failed",
                payload={"reason": "not_connected"},
            )
            return None
        today = int(pendulum.now().format("YYYYMMDD"))
        yestoday = int(pendulum.yesterday().format("YYYYMMDD"))
        one = DBfreshquant["stock_orders"].find_one(
            {
                "$or": [
                    {
                        "symbol": symbol,
                        "date": today,
                        "op": {"$regex": "买"},
                        "status": "未成交",
                    },
                    {
                        "symbol": symbol,
                        "date": yestoday,
                        "time": {"$gt": "15:00:00"},
                        "op": {"$regex": "买"},
                        "status": "未成交",
                    },
                ]
            }
        )
        if one is not None:
            logger.info("有未成交订单")
            _emit_puppet_event(
                "submit_result",
                context=context,
                status="skipped",
                payload={"reason": "existing_unfilled_order"},
            )
            return
        asset = xt_trader.query_stock_asset(acc)
        if asset.cash - asset.frozen_cash < float(price) * int(
            quantity
        ) + calculateTradeFee(price, quantity):
            logger.info("资金不足")
            _emit_puppet_event(
                "submit_result",
                context=context,
                status="skipped",
                payload={"reason": "insufficient_cash"},
            )
            return
        stock_code = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
        order_type_to_use = (
            xtconstant.STOCK_BUY
            if order_type in (None, "", "None")
            else int(order_type)
        )
        price_type_to_use = (
            xtconstant.FIX_PRICE
            if price_type in (None, "", "None", 0, "0")
            else int(price_type)
        )
        _emit_puppet_event(
            "submit_decision",
            context=context,
            payload={
                "stock_code": stock_code,
                "order_type": order_type_to_use,
                "price_type": price_type_to_use,
            },
        )
        fix_result_order_id = xt_trader.order_stock(
            acc,
            stock_code,
            order_type_to_use,
            int(quantity),
            price_type_to_use,
            float(price),
            strategy_name=strategyName,
            order_remark=remark,
        )
        logger.info("订单号: " + str(fix_result_order_id))
        _emit_puppet_event(
            "submit_result",
            context=context,
            status="success" if fix_result_order_id and int(fix_result_order_id) > 0 else "failed",
            payload={"broker_order_id": fix_result_order_id},
        )
        if fix_result_order_id < 0:
            if retryCount < 3:
                # Exponential backoff delay: 2^retryCount seconds
                delay = 2**retryCount
                time.sleep(delay)
                redis_db.lpush(
                    ORDER_QUEUE,
                    json.dumps(
                        {
                            "action": "buy",
                            "symbol": symbol,
                            "price": float(price),
                            "quantity": quantity,
                            "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                            "strategy_name": strategyName,
                            "remark": remark,
                            "retry_count": retryCount + 1,
                        }
                    ),
                )
        return fix_result_order_id


def sell(
    symbol: str,
    price_type: int,
    price: float,
    quantity: int,
    strategyName="N/A",
    remark="N/A",
    retryCount=0,
    order_type=None,
    trace_id=None,
    intent_id=None,
    request_id=None,
    internal_order_id=None,
):
    context = {
        "trace_id": trace_id,
        "intent_id": intent_id,
        "request_id": request_id,
        "internal_order_id": internal_order_id,
        "symbol": symbol,
        "action": "sell",
    }
    _emit_puppet_event(
        "submit_prepare",
        context=context,
        payload={"price": float(price), "quantity": int(quantity), "retry_count": retryCount},
    )
    with trading_manager.lock():
        # 获取当前连接的xt_trader和acc
        xt_trader, acc, _ = trading_manager.get_connection()
        if xt_trader is None or acc is None:
            logger.error("未连接到交易系统或账户信息缺失")
            _emit_puppet_event(
                "submit_result",
                context=context,
                status="failed",
                payload={"reason": "not_connected"},
            )
            return None
        today = int(pendulum.now().format("YYYYMMDD"))
        yestoday = int(pendulum.yesterday().format("YYYYMMDD"))
        one = DBfreshquant["stock_orders"].find_one(
            {
                "$or": [
                    {
                        "symbol": symbol,
                        "date": today,
                        "op": {"$regex": "卖"},
                        "status": "未成交",
                    },
                    {
                        "symbol": symbol,
                        "date": yestoday,
                        "time": {"$gt": "15:00:00"},
                        "op": {"$regex": "卖"},
                        "status": "未成交",
                    },
                ]
            }
        )
        if one is not None:
            logger.info("有未成交订单")
            _emit_puppet_event(
                "submit_result",
                context=context,
                status="skipped",
                payload={"reason": "existing_unfilled_order"},
            )
            return
        stock_code = (
            symbol
            if symbol.endswith(".SH") or symbol.endswith(".SZ")
            else fq_util_code_append_market_code_suffix(symbol, upper_case=True)
        )
        price = float(price)
        if price == 0.0:
            ticks = xtdata.get_full_tick([stock_code])
            if ticks is not None and stock_code in ticks:
                price = (
                    ticks[stock_code]["bidPrice"][0]
                    if ticks[stock_code]["bidPrice"][0] != 0
                    else ticks[stock_code]["lastPrice"]
                )
        order_type_to_use = (
            None if order_type in (None, "", "None") else int(order_type)
        )
        if order_type_to_use is None:
            order_type_to_use = xtconstant.STOCK_SELL
            if stock_code in REPO_CODE_LIST:
                order_type_to_use = xtconstant.CREDIT_SELL
        if stock_code not in REPO_CODE_LIST:
            positions = xt_trader.query_stock_positions(acc)
            position = pydash.find(positions, lambda p: p.stock_code == stock_code)
            if position is None:
                logger.info("无持仓")
                _emit_puppet_event(
                    "submit_result",
                    context=context,
                    status="skipped",
                    payload={"reason": "no_position"},
                )
                return
            if position.can_use_volume < int(quantity):
                logger.info("持仓不足")
                _emit_puppet_event(
                    "submit_result",
                    context=context,
                    status="skipped",
                    payload={"reason": "insufficient_position"},
                )
                return
        _emit_puppet_event(
            "submit_decision",
            context=context,
            payload={
                "stock_code": stock_code,
                "order_type": order_type_to_use,
                "price_type": (
                    xtconstant.FIX_PRICE
                    if price_type in (0, None, "", "None", "0")
                    else int(price_type)
                ),
            },
        )
        fix_result_order_id = xt_trader.order_stock(
            acc,
            stock_code,
            order_type_to_use,
            int(quantity),
            (
                xtconstant.FIX_PRICE
                if price_type in (0, None, "", "None", "0")
                else int(price_type)
            ),
            float(price),
            strategyName,
            remark,
        )
        _emit_puppet_event(
            "submit_result",
            context=context,
            status="success" if fix_result_order_id and int(fix_result_order_id) > 0 else "failed",
            payload={"broker_order_id": fix_result_order_id},
        )
        if fix_result_order_id < 0:
            if retryCount < 3:
                # Exponential backoff delay: 2^retryCount seconds
                delay = 2**retryCount
                time.sleep(delay)
                redis_db.lpush(
                    ORDER_QUEUE,
                    json.dumps(
                        {
                            "action": "sell",
                            "symbol": symbol,
                            "price": float(price),
                            "quantity": quantity,
                            "fire_time": pendulum.now().format("YYYY-MM-DD hh:mm:ss"),
                            "strategy_name": strategyName,
                            "remark": remark,
                            "retry_count": retryCount + 1,
                        }
                    ),
                )
        return fix_result_order_id


def _emit_puppet_event(node, *, context=None, status="info", payload=None):
    event = {
        "component": "puppet_gateway",
        "node": node,
        "status": status,
        "trace_id": (context or {}).get("trace_id"),
        "intent_id": (context or {}).get("intent_id"),
        "request_id": (context or {}).get("request_id"),
        "internal_order_id": (context or {}).get("internal_order_id"),
        "symbol": (context or {}).get("symbol"),
        "action": (context or {}).get("action"),
        "payload": dict(payload or {}),
    }
    try:
        _get_runtime_logger().emit(event)
    except Exception:
        return


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("puppet_gateway")
    return _runtime_logger
