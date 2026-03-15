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
from fqxtrade.xtquant.account import resolve_broker_submit_mode, resolve_stock_account
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

from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.submit.execution_bridge import (
    dispatch_cancel_execution,
    finalize_submit_execution,
    prepare_submit_execution,
    resolve_sell_price_type_compat,
)
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.system_settings import system_settings
from freshquant.trade.trade import checkManualStrategyInstument
from freshquant.util.code import fq_util_code_append_market_code_suffix

# 全局交易对象管理（单例模式）
trading_manager = TradingManager()

# 全局连接管理对象（单例模式）
connection_manager = ConnectionManager()
order_management_repository = OrderManagementRepository()
order_tracking_service = OrderTrackingService(repository=order_management_repository)
BROKER_SUBMIT_MODE_NORMAL = "normal"
BROKER_SUBMIT_MODE_OBSERVE_ONLY = "observe_only"


class MyXtQuantTraderCallback(XtQuantTraderCallback):
    def on_connected(self):
        """
        连接成功推送
        """
        _emit_broker_event(
            "watchdog",
            event_type="heartbeat",
            metrics={"connected": 1},
        )
        logger.info("连接成功")

    def on_disconnected(self):
        _emit_broker_event(
            "watchdog",
            event_type="heartbeat",
            status="warning",
            metrics={"connected": 0},
        )
        logger.warning("交易接口断开，即将重连")
        connection_manager.mark_disconnected()

    def on_stock_order(self, order):
        """
        委托回报推送
        :param order: XtOrder对象
        :return:
        """
        order_dict = FqXtOrder(order).to_dict()
        logger.info("收到委托回报推送: {order}", order=order_dict)
        _emit_broker_event(
            "order_callback",
            context=_resolve_runtime_context_by_broker_order_id(
                order_dict.get("order_id")
            ),
            symbol=str(order_dict.get("stock_code") or "")[:6],
            payload={
                "broker_order_id": order_dict.get("order_id"),
                "order_status": order_dict.get("order_status"),
            },
        )
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
        trade_dict = FqXtTrade(trade).to_dict()
        logger.info("收到成交变动推送: {trade}", trade=trade_dict)
        _emit_broker_event(
            "trade_callback",
            context=_resolve_runtime_context_by_broker_order_id(
                trade_dict.get("order_id")
            ),
            symbol=str(trade_dict.get("stock_code") or "")[:6],
            payload={
                "broker_order_id": trade_dict.get("order_id"),
                "broker_trade_id": trade_dict.get("traded_id"),
            },
        )
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
        path = system_settings.xtquant.path
        if not path:
            logger.error("请在配置文件中设置 xtquant.path 参数")
            return None, None, False
        xt_trader = XtQuantTrader(path, session_id)
        acc, account, account_type = resolve_stock_account(
            settings_provider=system_settings
        )
        if not account:
            logger.error("请在配置文件中设置 xtquant.account 参数")
            return None, None, False
        logger.info(
            "use xtquant account {account} type {account_type}",
            account=account,
            account_type=account_type,
        )
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
            logger.error(f"账号订阅失败，错误码: {subscribe_result}")
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
    broker_submit_mode = resolve_broker_submit_mode(settings_provider=system_settings)
    if _is_observe_only_mode(broker_submit_mode):
        logger.info(
            "broker submit mode is observe_only; skip xtquant connect and broker sync"
        )
    while True:
        session_ids = [i for i in range(100, 200)]
        random.shuffle(session_ids)
        for session_id in session_ids:
            try:
                if not connection_manager.connected and not _is_observe_only_mode(
                    broker_submit_mode
                ):
                    xt_trader, acc, success = connect(session_id)
                    if not success:
                        delay = connection_manager.get_retry_delay()
                        _emit_broker_event(
                            "watchdog",
                            event_type="metric_snapshot",
                            status="warning",
                            metrics={
                                "connected": 0,
                                "retry_count": connection_manager.retry_count,
                                "retry_delay_s": delay,
                            },
                        )
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
                    _emit_broker_event(
                        "queue_consume",
                        context=_runtime_context_from_order_message(order),
                        action=order.get("action"),
                        symbol=order.get("symbol"),
                        payload={"force": bool(order.get("force", False))},
                    )
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
                        _emit_broker_event(
                            "action_dispatch",
                            context=_runtime_context_from_order_message(order),
                            action=order.get("action"),
                            symbol=order.get("symbol"),
                            payload={"next_action": order.get("action")},
                        )
                        if order["action"] == "buy":
                            _handle_submit_action(
                                order,
                                action="buy",
                                submit_executor=lambda resolved_order: puppet.buy(
                                    resolved_order["symbol"],
                                    resolved_order["price"],
                                    resolved_order["quantity"],
                                    pydash.get(resolved_order, "strategy_name", "N/A"),
                                    pydash.get(resolved_order, "remark", "N/A"),
                                    pydash.get(resolved_order, "retry_count", 0),
                                    order_type=pydash.get(
                                        resolved_order, "broker_order_type"
                                    ),
                                    price_type=pydash.get(
                                        resolved_order, "broker_price_type"
                                    ),
                                    trace_id=pydash.get(resolved_order, "trace_id"),
                                    intent_id=pydash.get(resolved_order, "intent_id"),
                                    request_id=pydash.get(resolved_order, "request_id"),
                                    internal_order_id=pydash.get(
                                        resolved_order, "internal_order_id"
                                    ),
                                ),
                                broker_submit_mode=broker_submit_mode,
                            )
                        elif order["action"] == "sell":
                            _handle_submit_action(
                                order,
                                action="sell",
                                submit_executor=lambda resolved_order: puppet.sell(
                                    resolved_order["symbol"],
                                    resolve_sell_price_type_compat(resolved_order),
                                    resolved_order["price"],
                                    resolved_order["quantity"],
                                    pydash.get(resolved_order, "strategy_name", "N/A"),
                                    pydash.get(resolved_order, "remark", "N/A"),
                                    pydash.get(resolved_order, "retry_count", 0),
                                    order_type=pydash.get(
                                        resolved_order, "broker_order_type"
                                    ),
                                    trace_id=pydash.get(resolved_order, "trace_id"),
                                    intent_id=pydash.get(resolved_order, "intent_id"),
                                    request_id=pydash.get(resolved_order, "request_id"),
                                    internal_order_id=pydash.get(
                                        resolved_order, "internal_order_id"
                                    ),
                                ),
                                broker_submit_mode=broker_submit_mode,
                            )
                        elif order["action"] == "cancel":
                            _handle_cancel_action(
                                order,
                                broker_submit_mode=broker_submit_mode,
                            )
                        elif order["action"] in {
                            "sync-trades",
                            "sync-orders",
                            "sync-summary",
                            "sync-positions",
                            "sync-all",
                        }:
                            _handle_maintenance_action(
                                order,
                                broker_submit_mode=broker_submit_mode,
                            )
                    else:
                        logger.info("非交易时间，不执行交易下单")
                else:
                    if nextStart <= 0 and not _is_observe_only_mode(broker_submit_mode):
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


def _runtime_context_from_order_message(order):
    payload = dict(order or {})
    return {
        "trace_id": payload.get("trace_id"),
        "intent_id": payload.get("intent_id"),
        "request_id": payload.get("request_id"),
        "internal_order_id": payload.get("internal_order_id"),
        "symbol": payload.get("symbol"),
        "action": payload.get("action"),
    }


def _is_observe_only_mode(broker_submit_mode):
    return broker_submit_mode == BROKER_SUBMIT_MODE_OBSERVE_ONLY


def _emit_broker_bypass(order, *, action=None):
    _emit_broker_event(
        "execution_bypassed",
        context=_runtime_context_from_order_message(order),
        action=action or order.get("action"),
        symbol=order.get("symbol"),
        payload={
            "reason": "observe_only",
            "broker_submit_mode": BROKER_SUBMIT_MODE_OBSERVE_ONLY,
        },
    )


def _handle_submit_action(order, *, action, submit_executor, broker_submit_mode):
    if _is_observe_only_mode(broker_submit_mode):
        result = finalize_submit_execution(
            order,
            broker_order_id=None,
            repository=order_management_repository,
            tracking_service=order_tracking_service,
            broker_submit_mode=broker_submit_mode,
        )
        _emit_broker_bypass(order, action=action)
        return result

    execution = prepare_submit_execution(
        order,
        repository=order_management_repository,
        tracking_service=order_tracking_service,
    )
    if execution.get("status") == "skipped":
        return execution
    resolved_order = execution.get("order_message", order)

    broker_order_id = submit_executor(resolved_order)
    logger.info(broker_order_id)
    finalize_submit_execution(
        order,
        broker_order_id=broker_order_id,
        repository=order_management_repository,
        tracking_service=order_tracking_service,
        broker_submit_mode=broker_submit_mode,
    )
    _emit_broker_event(
        "submit_result",
        context=_runtime_context_from_order_message(resolved_order),
        action=action,
        symbol=resolved_order.get("symbol"),
        status=(
            "success"
            if broker_order_id not in (None, "", "None") and int(broker_order_id) > 0
            else "failed"
        ),
        payload={"broker_order_id": broker_order_id},
    )
    return {"status": "submitted", "broker_order_id": broker_order_id}


def _handle_cancel_action(order, *, broker_submit_mode):
    if _is_observe_only_mode(broker_submit_mode):
        dispatch_result = dispatch_cancel_execution(
            order,
            cancel_executor=lambda broker_order_id: -1,
            repository=order_management_repository,
            tracking_service=order_tracking_service,
            broker_submit_mode=broker_submit_mode,
        )
        logger.info(dispatch_result)
        _emit_broker_bypass(order, action="cancel")
        return dispatch_result

    xt_trader, acc, _ = trading_manager.get_connection()
    dispatch_result = dispatch_cancel_execution(
        order,
        cancel_executor=(
            lambda broker_order_id: (
                xt_trader.cancel_order_stock(acc, broker_order_id)
                if xt_trader is not None and acc is not None
                else -1
            )
        ),
        repository=order_management_repository,
        tracking_service=order_tracking_service,
        broker_submit_mode=broker_submit_mode,
    )
    logger.info(dispatch_result)
    _emit_broker_event(
        "submit_result",
        context=_runtime_context_from_order_message(order),
        action="cancel",
        symbol=order.get("symbol"),
        status=(
            "success"
            if dispatch_result.get("status") == "cancel_submitted"
            else "failed"
        ),
        payload=dispatch_result,
    )
    return dispatch_result


def _handle_maintenance_action(order, *, broker_submit_mode):
    action = order.get("action")
    if _is_observe_only_mode(broker_submit_mode):
        _emit_broker_bypass(order, action=action)
        return {"status": "broker_bypassed"}
    if action == "sync-trades":
        puppet.sync_trades()
    elif action == "sync-orders":
        puppet.sync_orders()
    elif action == "sync-summary":
        puppet.sync_summary()
    elif action == "sync-positions":
        puppet.sync_positions()
    elif action == "sync-all":
        puppet.sync_positions()
        puppet.sync_orders()
        puppet.sync_trades()
        puppet.sync_summary()
    return {"status": "executed", "action": action}


def _resolve_runtime_context_by_broker_order_id(broker_order_id):
    if broker_order_id in (None, "", "None"):
        return {}
    try:
        order = order_management_repository.find_order_by_broker_order_id(
            broker_order_id
        )
    except Exception:
        order = None
    if order is None:
        return {}
    return {
        "trace_id": order.get("trace_id"),
        "intent_id": order.get("intent_id"),
        "request_id": order.get("request_id"),
        "internal_order_id": order.get("internal_order_id"),
        "symbol": order.get("symbol"),
        "action": order.get("side"),
    }


def _emit_broker_event(
    node,
    *,
    context=None,
    action=None,
    symbol=None,
    status="info",
    event_type="trace_step",
    payload=None,
    metrics=None,
):
    event = {
        "component": "broker_gateway",
        "node": node,
        "event_type": event_type,
        "status": status,
        "trace_id": (context or {}).get("trace_id"),
        "intent_id": (context or {}).get("intent_id"),
        "request_id": (context or {}).get("request_id"),
        "internal_order_id": (context or {}).get("internal_order_id"),
        "symbol": symbol or (context or {}).get("symbol"),
        "action": action or (context or {}).get("action"),
        "payload": dict(payload or {}),
        "metrics": dict(metrics or {}),
    }
    try:
        _get_runtime_logger().emit(event)
    except Exception:
        return


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("broker_gateway")
    return _runtime_logger


if __name__ == "__main__":
    main()
