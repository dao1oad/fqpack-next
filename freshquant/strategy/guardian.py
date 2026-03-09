import json
import inspect
from datetime import datetime, timedelta

import pendulum
from blinker import signal
from loguru import logger

import freshquant.util.datetime_helper as datetime_helper
from freshquant.basic.singleton_type import SingletonType
from freshquant.data.astock.holding import (
    get_arranged_stock_fill_list,
    get_stock_holding_codes,
)
from freshquant.database.redis import redis_db
from freshquant.order_management.submit.guardian import submit_guardian_order
from freshquant.pool.general import queryMustPoolCodes
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.runtime_observability.ids import new_intent_id, new_trace_id
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service
from freshquant.strategy.toolkit.threshold import eval_stock_threshold_price
from freshquant.util.code import fq_util_code_append_market_code_suffix
from freshquant.util.datetime_helper import fq_util_datetime_localize

order_alert = signal("order_alert")


class StrategyGuardian(metaclass=SingletonType):
    def __init__(self, runtime_logger=None):
        if runtime_logger is not None:
            self.runtime_logger = runtime_logger
        elif not hasattr(self, "runtime_logger"):
            self.runtime_logger = _get_runtime_logger()

    def on_signal(self, signal):
        trace_id = self._ensure_trace_id(signal)
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

        holding_codes = set(get_stock_holding_codes())
        must_pool_codes = set(queryMustPoolCodes())
        in_holding = code in holding_codes
        in_must_pool = code in must_pool_codes

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
        self._emit_runtime(
            signal,
            "receive_signal",
            action="buy" if position == "BUY_LONG" else "sell",
            payload={"period": period, "price": price, "remark": remark},
        )

        if (in_holding or in_must_pool) and fire_time < pendulum.now().add(minutes=-30):
            self._emit_runtime(
                signal,
                "timing_check",
                action="buy" if position == "BUY_LONG" else "sell",
                status="skipped",
                reason_code="signal_too_old",
            )
            logger.info("{code} {name} 超过30分钟，跳过下单指令", code=code, name=name)
            return

        self._emit_runtime(
            signal,
            "holding_scope_resolve",
            action="buy" if position == "BUY_LONG" else "sell",
            payload={"in_holding": in_holding, "in_must_pool": in_must_pool},
        )

        if position == "BUY_LONG":
            if in_holding:
                self._handle_holding_buy(
                    signal=signal,
                    code=code,
                    name=name,
                    fire_time=fire_time,
                    price=price,
                    remark=remark,
                    zsdata=zsdata,
                    fills=fills,
                )
            elif in_must_pool:
                self._handle_new_open_buy(
                    signal=signal,
                    code=code,
                    name=name,
                    price=price,
                    remark=remark,
                )
        elif position == "SELL_SHORT" and in_holding:
            self._handle_sell(
                signal=signal,
                code=code,
                name=name,
                fire_time=fire_time,
                price=price,
                remark=remark,
            )

        if in_holding or in_must_pool:
            order_alert.send("guardian", private=True, payload=signal)
        elif position == "BUY_LONG":
            order_alert.send("guardian", payload=signal)

    def _handle_holding_buy(
        self,
        *,
        signal,
        code,
        name,
        fire_time,
        price,
        remark,
        zsdata,
        fills,
    ):
        fill_list = get_arranged_stock_fill_list(code) or []
        last_fill = fill_list[-1] if fill_list else None
        last_fill_dt = None
        last_fill_price = None
        if last_fill is not None:
            last_fill_dt = datetime.strptime(
                "%s %s" % (str(last_fill["date"]), last_fill["time"]),
                "%Y%m%d %H:%M:%S",
            )
            last_fill_dt = fq_util_datetime_localize(last_fill_dt)
            last_fill_price = last_fill["price"]

        if last_fill_dt is not None and fire_time < last_fill_dt:
            logger.info("触发时间异常，跳过下单指令")
            return

        if last_fill_price is not None:
            threshold = eval_stock_threshold_price(code, last_fill_price)
            if price > threshold["bot_river_price"]:
                logger.info("触发价格未达，跳过下单指令")
                return

        if not self._has_separating_zs(
            code=code,
            name=name,
            fire_time=fire_time,
            fills=fills,
            zsdata=zsdata,
        ):
            return

        decision = get_guardian_buy_grid_service().build_holding_add_decision(
            code,
            price,
        )
        self._submit_buy_order(
            signal=signal,
            code=code,
            price=price,
            remark=remark,
            decision=decision,
            set_new_open_cooldown=False,
        )

    def _handle_new_open_buy(self, *, signal, code, name, price, remark):
        if redis_db.get("fq:xtrade:last_new_order_time") is not None:
            last_new_order_time = redis_db.get("fq:xtrade:last_new_order_time")
            logger.info(
                f"上次新开仓下单时间未超过15分钟，不再自动买入：{last_new_order_time}"
            )
            return

        decision = get_guardian_buy_grid_service().build_new_open_decision(code, price)
        if decision.get("quantity", 0) <= 0:
            logger.info(
                "{code} {name} 新开仓可交易数量不足，跳过下单", code=code, name=name
            )
            return

        self._submit_buy_order(
            signal=signal,
            code=code,
            price=price,
            remark=remark,
            decision=decision,
            set_new_open_cooldown=True,
        )

    def _submit_buy_order(
        self,
        *,
        signal,
        code,
        price,
        remark,
        decision,
        set_new_open_cooldown,
    ):
        quantity = int(decision.get("quantity") or 0)
        if quantity <= 0:
            logger.info("{code} 买入数量无效，跳过下单", code=code)
            return

        if redis_db.get(f"buy:{code}") is not None:
            self._emit_runtime(
                signal,
                "cooldown_check",
                action="buy",
                status="skipped",
                reason_code="buy_cooldown",
            )
            logger.info("{code} 买入冷却中，跳过下单", code=code)
            return

        strategy_context = {
            "guardian_buy_grid": {
                "path": decision.get("path"),
                "grid_level": decision.get("grid_level"),
                "hit_levels": list(decision.get("hit_levels") or []),
                "multiplier": decision.get("multiplier", 1),
                "source_price": decision.get("source_price"),
                "buy_prices_snapshot": decision.get("buy_prices_snapshot"),
                "buy_active_before": decision.get("buy_active_before"),
                "initial_amount": decision.get("initial_amount"),
                "base_amount": decision.get("base_amount"),
            }
        }

        signal["quantity"] = quantity
        signal.setdefault("intent_id", new_intent_id())
        self._emit_runtime(
            signal,
            "submit_intent",
            action="buy",
            payload={"quantity": quantity, "grid_path": decision.get("path")},
        )

        try:
            self._submit_guardian_order(
                action="buy",
                code=code,
                price=price,
                quantity=quantity,
                remark=remark,
                strategy_context=strategy_context,
                signal=signal,
            )
        except PositionManagementRejectedError as exc:
            logger.info(
                "{code} 买单被仓位管理拒绝：{reason}",
                code=code,
                reason=str(exc),
            )
            return

        redis_db.set(f"buy:{code}", "1", timedelta(minutes=15))
        if set_new_open_cooldown:
            redis_db.set(
                "fq:xtrade:last_new_order_time",
                pendulum.now().format("YYYY-MM-DD HH:mm:ss"),
                timedelta(minutes=15),
            )

    def _handle_sell(self, *, signal, code, name, fire_time, price, remark):
        fill_list = get_arranged_stock_fill_list(code) or []
        last_fill = fill_list[-1] if fill_list else None
        if last_fill is None:
            logger.info("无持仓，跳过下单指令")
            return

        last_fill_dt = datetime.strptime(
            "%s %s" % (str(last_fill["date"]), last_fill["time"]),
            "%Y%m%d %H:%M:%S",
        )
        last_fill_dt = fq_util_datetime_localize(last_fill_dt)
        if fire_time < last_fill_dt:
            logger.info("触发时间异常，跳过下单指令")
            return

        last_fill_price = last_fill["price"]
        if price < eval_stock_threshold_price(code, last_fill_price)["top_river_price"]:
            logger.info("条件未达，跳过下单指令")
            return

        quantity = 0
        for i in range(len(fill_list) - 1, -1, -1):
            if price > fill_list[i]["price"]:
                quantity = quantity + fill_list[i]["quantity"]
            else:
                break

        if quantity <= 0:
            logger.info("{code} {name} 当前无可卖盈利切片", code=code, name=name)
            return

        if redis_db.get(f"sell:{code}") is not None:
            self._emit_runtime(
                signal,
                "cooldown_check",
                action="sell",
                status="skipped",
                reason_code="sell_cooldown",
            )
            logger.info("{code} 卖出冷却中，跳过下单", code=code)
            return

        signal["quantity"] = quantity
        signal.setdefault("intent_id", new_intent_id())
        self._emit_runtime(
            signal,
            "submit_intent",
            action="sell",
            payload={"quantity": quantity, "is_profitable": True},
        )
        try:
            submit_result = self._submit_guardian_order(
                action="sell",
                code=code,
                price=price,
                quantity=quantity,
                remark=remark,
                is_profitable=True,
                signal=signal,
            )
        except PositionManagementRejectedError as exc:
            logger.info(
                "{code} 卖单被仓位管理拒绝：{reason}",
                code=code,
                reason=str(exc),
            )
            return

        redis_db.set(f"sell:{code}", "1", timedelta(minutes=15))
        queue_payload = (submit_result or {}).get("queue_payload") or {}
        if queue_payload.get("position_management_force_profit_reduce"):
            logger.info(
                "{code} 命中仓位管理减仓盈利模式：{mode}",
                code=code,
                mode=queue_payload.get("position_management_profit_reduce_mode"),
            )

    def _has_separating_zs(self, *, code, name, fire_time, fills, zsdata):
        if fills is None or len(fills) == 0:
            return True
        fill_time = str(fills[-1]["date"]) + " " + fills[-1]["time"]
        fill_time = datetime.strptime(fill_time, "%Y%m%d %H:%M:%S").replace(
            tzinfo=pendulum.local_timezone()
        )
        if zsdata is None or len(zsdata) == 0:
            logger.info("{code} {name} 没有中枢，跳过下单指令", code=code, name=name)
            return False
        for zs in reversed(zsdata):
            zs_start = datetime.strptime(zs[0][0], "%Y-%m-%d %H:%M").replace(
                tzinfo=pendulum.local_timezone()
            )
            zs_end = datetime.strptime(zs[1][0], "%Y-%m-%d %H:%M").replace(
                tzinfo=pendulum.local_timezone()
            )
            if (
                fire_time >= zs_end
                and fill_time <= zs_start
                and fills[-1]["price"] > zs[0][1]
                and fills[-1]["price"] > zs[1][1]
            ):
                return True
        logger.info("{code} {name} 无相隔中枢，跳过下单指令", code=code, name=name)
        return False

    def _ensure_trace_id(self, signal):
        trace_id = str(signal.get("trace_id") or "").strip()
        if not trace_id:
            trace_id = new_trace_id()
            signal["trace_id"] = trace_id
        return trace_id

    def _emit_runtime(
        self,
        signal,
        node,
        *,
        action=None,
        status="info",
        reason_code="",
        payload=None,
    ):
        event = {
            "component": "guardian_strategy",
            "node": node,
            "trace_id": signal.get("trace_id"),
            "intent_id": signal.get("intent_id"),
            "action": action,
            "symbol": signal.get("code"),
            "strategy_name": "Guardian",
            "source": "strategy",
            "status": status,
            "reason_code": reason_code,
            "payload": dict(payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return

    def _submit_guardian_order(
        self,
        *,
        action,
        code,
        price,
        quantity,
        signal,
        remark=None,
        is_profitable=None,
        strategy_context=None,
    ):
        submit_kwargs = {
            "remark": remark,
            "is_profitable": is_profitable,
            "strategy_context": strategy_context,
        }
        try:
            parameters = inspect.signature(submit_guardian_order).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "trace_id" in parameters:
            submit_kwargs["trace_id"] = signal.get("trace_id")
        if "intent_id" in parameters:
            submit_kwargs["intent_id"] = signal.get("intent_id")
        return submit_guardian_order(
            action,
            code,
            price,
            quantity,
            **submit_kwargs,
        )


def test_order_alert_signal():
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
    test_order_alert_signal()


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("guardian_strategy")
    return _runtime_logger
