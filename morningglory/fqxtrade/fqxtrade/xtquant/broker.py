import json
import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

import fqxtrade.xtquant.puppet as puppet
import pydash
import tornado.web
from fqxtrade import ORDER_QUEUE
from fqxtrade.database.redis import redis_db
from fqxtrade.util.trade_date_hist import tool_trade_date_seconds_to_start
from fqxtrade.xtquant.connection_manager import ConnectionManager
from fqxtrade.xtquant.fqtype import (
    FqXtAccountStatus,
    FqXtAsset,
    FqXtCancelError,
    FqXtCancelOrderResponse,
    FqXtOrder,
    FqXtOrderError,
    FqXtOrderResponse,
    FqXtPosition,
    FqXtSmtAppointmentResponse,
    FqXtTrade,
)
from fqxtrade.xtquant.handlers import handlers

# 导入新的单例 TradingManager 和 ConnectionManager（从 xtquant/base 子目录中导入）
from fqxtrade.xtquant.trading_manager import TradingManager
from loguru import logger
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

from freshquant.carnation.param import queryParam
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.submit.execution_bridge import (
    dispatch_cancel_execution,
    finalize_submit_execution,
    prepare_submit_execution,
)
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.trade.trade import checkManualStrategyInstument
from freshquant.util.code import fq_util_code_append_market_code_suffix

# 全局交易对象管理（单例模式）
trading_manager = TradingManager()

# 全局连接管理对象（单例模式）
connection_manager = ConnectionManager()
order_management_repository = OrderManagementRepository()
order_tracking_service = OrderTrackingService(repository=order_management_repository)


class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_connected(self):
        """
        连接成功推送
        """
        logger.info("连接成功")

    def on_disconnected(self):
        logger.warning("交易接口断开，即将重连")
        connection_manager.mark_disconnected()

    def on_stock_order(self, order):
        """
        委托回报推送
        :param order: XtOrder对象
        :return:
        """
        logger.info("收到委托回报推送: {order}", order=FqXtOrder(order).to_dict())
        puppet.saveOrders([order])

    def on_stock_asset(self, asset):
        """
        资金变动推送
        :param asset: XtAsset对象
        :return:
        """
        logger.info("收到资金变动推送: {asset}", asset=FqXtAsset(asset).to_dict())
        puppet.saveAssets([asset])

    def on_stock_trade(self, trade):
        """
        成交变动推送
        :param trade: XtTrade对象
        :return:
        """
        logger.info("收到成交变动推送: {trade}", trade=FqXtTrade(trade).to_dict())
        puppet.saveTrades([trade])

    def on_stock_position(self, position):
        """
        持仓变动推送
        :param position: XtPosition对象
        :return:
        """
        logger.info(
            "收到持仓变动推送: {position}", position=FqXtPosition(position).to_dict()
        )

    def on_order_error(self, order_error):
        """
        委托失败推送
        :param order_error:XtOrderError 对象
        :return:
        """
        logger.info(
            "收到委托失败推送: {error}", error=FqXtOrderError(order_error).to_dict()
        )

    def on_cancel_error(self, cancel_error):
        """
        撤单失败推送
        :param cancel_error: XtCancelError 对象
        :return:
        """
        logger.info(
            "委托失败推送: {error}", error=FqXtCancelError(cancel_error).to_dict()
        )

    def on_order_stock_async_response(self, response):
        """
        异步下单回报推送
        :param response: XtOrderResponse 对象
        :return:
        """
        logger.info(
            "收到异步下单回报推送: {response}",
            response=FqXtOrderResponse(response).to_dict(),
        )

    def on_account_status(self, status):
        """
        :param response: XtAccountStatus 对象
        :return:
        """
        logger.info(
            "收到账号状态变化推送: {status}", status=FqXtAccountStatus(status).to_dict()
        )

    def on_smt_appointment_async_response(self, response):
        """
        :param response: XtAppointmentResponse 对象
        :return:
        """
        logger.info(
            "收到异步约券委托反馈推送: {response}",
            response=FqXtSmtAppointmentResponse(response).to_dict(),
        )

    def on_cancel_order_stock_async_response(self, response):
        """
        :param response: XtCancelOrderResponse 对象
        :return:
        """
        logger.info(
            "收到异步委托撤单推送: {response}",
            response=FqXtCancelOrderResponse(response).to_dict(),
        )


def connect(session_id: int = 100):
    try:
        path = queryParam("xtquant.path", "")
        if not path:
            logger.error("请在配置文件中设置 xtquant.path 参数")
            return None, None, False
        xt_trader = XtQuantTrader(path, session_id)
        account = str(queryParam("xtquant.account", ""))
        if not account:
            logger.error("请在配置文件中设置 xtquant.account 参数")
            return None, None, False
        acc = StockAccount(account)
        callback = MyXtQuantTraderCallback()
        xt_trader.register_callback(callback)
        # 启动交易线程
        xt_trader.start()
        # 建立交易连接，返回0表示连接成功
        connect_result = xt_trader.connect()
        if connect_result != 0:
            connection_manager.mark_disconnected()
            logger.error(f"连接失败，错误码: {connect_result}")
            return xt_trader, acc, False
        else:
            logger.info("连接成功")

        # 对交易回调进行订阅，订阅后可以收到交易主推，返回0表示订阅成功
        subscribe_result = xt_trader.subscribe(acc)
        if subscribe_result != 0:
            logger.error(f'账号订阅失败，错误码: {subscribe_result}')
            connection_manager.mark_disconnected()
            return xt_trader, acc, False
        else:
            logger.info("订阅成功")
        connection_manager.mark_connected()
        return xt_trader, acc, True

    except Exception as e:
        logger.error(f"连接过程中发生异常: {str(e)}")
        connection_manager.mark_disconnected()
        return None, None, False


def trading_main_loop():
    while True:
        session_ids = [i for i in range(100, 200)]
        random.shuffle(session_ids)
        for session_id in session_ids:
            try:
                if not connection_manager.connected:
                    xt_trader, acc, success = connect(session_id)
                    if not success:
                        delay = connection_manager.get_retry_delay()
                        if connection_manager.can_retry():
                            logger.warning(
                                f"对接miniqmt失败，将在{delay}秒后重试... (重试次数: {connection_manager.retry_count}/{connection_manager.max_retries})"
                            )
                        else:
                            logger.error(
                                f"达到最大重试次数({connection_manager.max_retries})，开始重新连接"
                            )
                            connection_manager.reset_retry_count()
                        time.sleep(delay)
                        continue
                    else:
                        with trading_manager.lock():
                            trading_manager.update_connection(xt_trader, acc, success)
                nextStart = tool_trade_date_seconds_to_start()
                order = redis_db.brpop([ORDER_QUEUE], 300)
                if order is not None:
                    logger.info(order[1])
                    order = json.loads(order[1])
                    if (
                        order.get("action") in {"buy", "sell"}
                        and order.get("symbol")
                        and checkManualStrategyInstument(
                            fq_util_code_append_market_code_suffix(
                                order["symbol"], upper_case=True
                            )
                        )
                    ):
                        logger.info("{symbol}是手动交易策略", symbol=order["symbol"])
                        continue
                    force = order.get("force", False)
                    if nextStart <= 0 or force or order.get("action") == "cancel":
                        if order["action"] == "buy":
                            execution = prepare_submit_execution(
                                order,
                                repository=order_management_repository,
                                tracking_service=order_tracking_service,
                            )
                            if execution.get("status") == "skipped":
                                continue
                            r = puppet.buy(
                                order["symbol"],
                                order["price"],
                                order["quantity"],
                                pydash.get(order, "strategy_name", "N/A"),
                                pydash.get(order, "remark", "N/A"),
                                pydash.get(order, "retry_count", 0),
                            )
                            logger.info(r)
                            finalize_submit_execution(
                                order,
                                broker_order_id=r,
                                repository=order_management_repository,
                                tracking_service=order_tracking_service,
                            )
                        elif order["action"] == "sell":
                            execution = prepare_submit_execution(
                                order,
                                repository=order_management_repository,
                                tracking_service=order_tracking_service,
                            )
                            if execution.get("status") == "skipped":
                                continue
                            r = puppet.sell(
                                order["symbol"],
                                pydash.get(order, "price_type"),
                                order["price"],
                                order["quantity"],
                                pydash.get(order, "strategy_name", "N/A"),
                                pydash.get(order, "remark", "N/A"),
                                pydash.get(order, "retry_count", 0),
                            )
                            logger.info(r)
                            finalize_submit_execution(
                                order,
                                broker_order_id=r,
                                repository=order_management_repository,
                                tracking_service=order_tracking_service,
                            )
                        elif order["action"] == "cancel":
                            xt_trader, acc, _ = trading_manager.get_connection()
                            dispatch_result = dispatch_cancel_execution(
                                order,
                                cancel_executor=(
                                    lambda broker_order_id: (
                                        xt_trader.cancel_order_stock(
                                            acc, broker_order_id
                                        )
                                        if xt_trader is not None and acc is not None
                                        else -1
                                    )
                                ),
                                repository=order_management_repository,
                                tracking_service=order_tracking_service,
                            )
                            logger.info(dispatch_result)
                        elif order["action"] == "sync-trades":
                            puppet.sync_trades()
                        elif order["action"] == "sync-orders":
                            puppet.sync_orders()
                        elif order["action"] == "sync-summary":
                            puppet.sync_summary()
                        elif order["action"] == "sync-positions":
                            puppet.sync_positions()
                        elif order["action"] == "sync-all":
                            puppet.sync_positions()
                            puppet.sync_orders()
                            puppet.sync_trades()
                            puppet.sync_summary()
                    else:
                        logger.info("非交易时间，不执行交易下单")
                else:
                    if nextStart <= 0:
                        # 开市期间查询账户状态
                        # 查询持仓情况
                        puppet.sync_positions()
                        # 查询委托记录
                        puppet.sync_orders()
                        # 查询当日成交记录
                        puppet.sync_trades()
                        # 查询资金情况
                        summary = puppet.sync_summary()
                        if summary is None:
                            # 查询不到资产就认为连接已经不正常了
                            connection_manager.mark_disconnected()
                            logger.warning("资产查询失败，标记连接为断开状态")

            except (Exception, KeyboardInterrupt, SystemExit) as e:
                if isinstance(e, KeyboardInterrupt) or isinstance(e, SystemExit):
                    break
                logger.error(traceback.format_exc())


def main():
    trading_thread = threading.Thread(target=trading_main_loop, daemon=True)
    trading_thread.start()

    thread_pool = ThreadPoolExecutor(max_workers=4)
    # 配置 Tornado
    app = tornado.web.Application(
        handlers, autoreload=True, compress_response=True, thread_pool=thread_pool
    )

    app.listen(10088)
    logger.info("服务已启动，REST API 端口: 10088")
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        thread_pool.shutdown()
        logger.info("服务正常退出")


if __name__ == "__main__":
    main()
