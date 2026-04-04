import inspect
import json
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
from freshquant.db import DBfreshquant
from freshquant.order_management.entry_adapter import list_open_entry_views
from freshquant.order_management.guardian.sell_semantics import (
    build_guardian_sell_source_entries,
)
from freshquant.order_management.sell_constraints import (
    PositionVolumeReader,
    resolve_sell_submission_quantity,
)
from freshquant.order_management.submit.guardian import submit_guardian_order
from freshquant.pool.general import queryMustPoolCodes
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
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
        self._ensure_trace_id(signal)
        current_node = "receive_signal"
        action = self._resolve_action(signal.get("position"))
        try:
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
            action = self._resolve_action(position)

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
                action=action,
                decision_branch="signal_received",
                decision_outcome={"outcome": "continue"},
                payload={
                    "period": period,
                    "price": price,
                    "remark": remark,
                    "tags": tags,
                },
            )

            current_node = "holding_scope_resolve"
            holding_codes = set(get_stock_holding_codes())
            must_pool_codes = set(queryMustPoolCodes())
            in_holding = code in holding_codes
            in_must_pool = code in must_pool_codes
            should_alert_private = in_holding or in_must_pool
            should_alert_public = position == "BUY_LONG" and not should_alert_private

            scope_context = {
                "scope": {
                    "position": position,
                    "in_holding": in_holding,
                    "in_must_pool": in_must_pool,
                }
            }
            eligible = False
            scope_branch = "unsupported_position"
            scope_reason_code = "unsupported_position"
            if position == "BUY_LONG":
                if in_holding:
                    eligible = True
                    scope_branch = "holding_buy"
                    scope_reason_code = ""
                elif in_must_pool:
                    eligible = True
                    scope_branch = "new_open_buy"
                    scope_reason_code = ""
                else:
                    scope_branch = "buy_out_of_scope"
                    scope_reason_code = "buy_out_of_scope"
            elif position == "SELL_SHORT":
                if in_holding:
                    eligible = True
                    scope_branch = "holding_sell"
                    scope_reason_code = ""
                else:
                    scope_branch = "sell_out_of_scope"
                    scope_reason_code = "sell_out_of_scope"

            self._emit_runtime(
                signal,
                "holding_scope_resolve",
                action=action,
                status="success" if eligible else "skipped",
                reason_code=scope_reason_code,
                decision_branch=scope_branch,
                decision_expr=(
                    "position == BUY_LONG ? (in_holding or in_must_pool) : in_holding"
                ),
                decision_context=scope_context,
                decision_outcome={"outcome": "pass" if eligible else "skip"},
                payload={"in_holding": in_holding, "in_must_pool": in_must_pool},
            )

            if not eligible:
                self._emit_finish(
                    signal,
                    action=action,
                    status="skipped",
                    reason_code=scope_reason_code,
                    outcome="skip",
                    decision_branch=scope_branch,
                    decision_expr=(
                        "position == BUY_LONG ? (in_holding or in_must_pool) : in_holding"
                    ),
                    decision_context=scope_context,
                )
            else:
                current_node = "timing_check"
                cutoff_time = pendulum.now().add(minutes=-30)
                timing_context = {
                    "timing": {
                        "fire_time": fire_time,
                        "discover_time": discover_time,
                        "cutoff_time": cutoff_time,
                        "max_age_minutes": 30,
                    }
                }
                if fire_time < cutoff_time:
                    self._emit_runtime(
                        signal,
                        "timing_check",
                        action=action,
                        status="skipped",
                        reason_code="signal_too_old",
                        decision_branch="signal_freshness",
                        decision_expr="fire_time >= cutoff_time",
                        decision_context=timing_context,
                        decision_outcome={"outcome": "skip"},
                    )
                    self._emit_finish(
                        signal,
                        action=action,
                        status="skipped",
                        reason_code="signal_too_old",
                        outcome="skip",
                        decision_branch="signal_freshness",
                        decision_expr="fire_time >= cutoff_time",
                        decision_context=timing_context,
                    )
                    logger.info(
                        "{code} {name} 超过30分钟，跳过下单指令",
                        code=code,
                        name=name,
                    )
                    return

                self._emit_runtime(
                    signal,
                    "timing_check",
                    action=action,
                    status="success",
                    decision_branch="signal_freshness",
                    decision_expr="fire_time >= cutoff_time",
                    decision_context=timing_context,
                    decision_outcome={"outcome": "pass"},
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

            if should_alert_private:
                order_alert.send("guardian", private=True, payload=signal)
            elif should_alert_public:
                order_alert.send("guardian", payload=signal)
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_unexpected_exception(
                    signal,
                    node=current_node,
                    action=action,
                    exc=exc,
                )
            raise

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
        current_node = "timing_check"
        try:
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

            if last_fill_dt is not None:
                timing_context = {
                    "timing": {
                        "fire_time": fire_time,
                        "last_fill_time": last_fill_dt,
                    }
                }
                if fire_time < last_fill_dt:
                    self._emit_runtime(
                        signal,
                        "timing_check",
                        action="buy",
                        status="skipped",
                        reason_code="signal_before_last_fill",
                        decision_branch="fill_ordering",
                        decision_expr="fire_time >= last_fill_time",
                        decision_context=timing_context,
                        decision_outcome={"outcome": "skip"},
                    )
                    self._emit_finish(
                        signal,
                        action="buy",
                        status="skipped",
                        reason_code="signal_before_last_fill",
                        outcome="skip",
                        decision_branch="fill_ordering",
                        decision_expr="fire_time >= last_fill_time",
                        decision_context=timing_context,
                    )
                    logger.info("触发时间异常，跳过下单指令")
                    return

                self._emit_runtime(
                    signal,
                    "timing_check",
                    action="buy",
                    status="success",
                    decision_branch="fill_ordering",
                    decision_expr="fire_time >= last_fill_time",
                    decision_context=timing_context,
                    decision_outcome={"outcome": "pass"},
                )

            current_node = "price_threshold_check"
            if last_fill_price is not None:
                threshold = eval_stock_threshold_price(code, last_fill_price)
                threshold_context = {
                    "threshold": {
                        "current_price": price,
                        "last_fill_price": last_fill_price,
                        "bot_river_price": threshold.get("bot_river_price"),
                        "top_river_price": threshold.get("top_river_price"),
                    }
                }
                if price > threshold["bot_river_price"]:
                    self._emit_runtime(
                        signal,
                        "price_threshold_check",
                        action="buy",
                        status="skipped",
                        reason_code="price_threshold_not_met",
                        decision_branch="holding_add_threshold",
                        decision_expr="current_price <= bot_river_price",
                        decision_context=threshold_context,
                        decision_outcome={"outcome": "skip"},
                    )
                    self._emit_finish(
                        signal,
                        action="buy",
                        status="skipped",
                        reason_code="price_threshold_not_met",
                        outcome="skip",
                        decision_branch="holding_add_threshold",
                        decision_expr="current_price <= bot_river_price",
                        decision_context=threshold_context,
                    )
                    logger.info("触发价格未达，跳过下单指令")
                    return

                self._emit_runtime(
                    signal,
                    "price_threshold_check",
                    action="buy",
                    status="success",
                    decision_branch="holding_add_threshold",
                    decision_expr="current_price <= bot_river_price",
                    decision_context=threshold_context,
                    decision_outcome={"outcome": "pass"},
                )

            current_node = "signal_structure_check"
            structure_result = self._evaluate_signal_structure(
                code=code,
                name=name,
                fire_time=fire_time,
                fills=fills,
                zsdata=zsdata,
            )
            self._emit_runtime(
                signal,
                "signal_structure_check",
                action="buy",
                status="success" if structure_result["passed"] else "skipped",
                reason_code=structure_result["reason_code"],
                decision_branch=structure_result["decision_branch"],
                decision_expr="fills empty or signal has separating zs",
                decision_context=structure_result["decision_context"],
                decision_outcome={
                    "outcome": "pass" if structure_result["passed"] else "skip"
                },
            )
            if not structure_result["passed"]:
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code=structure_result["reason_code"],
                    outcome="skip",
                    decision_branch=structure_result["decision_branch"],
                    decision_expr="fills empty or signal has separating zs",
                    decision_context=structure_result["decision_context"],
                )
                return

            current_node = "quantity_check"
            decision = get_guardian_buy_grid_service().build_holding_add_decision(
                code,
                price,
            )
            current_node = "submit_intent"
            self._submit_buy_order(
                signal=signal,
                code=code,
                price=price,
                remark=remark,
                decision=decision,
                set_new_open_cooldown=False,
                quantity_reason_code="quantity_invalid",
                submit_branch="holding_add",
            )
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_unexpected_exception(
                    signal,
                    node=current_node,
                    action="buy",
                    exc=exc,
                )
            raise

    def _handle_new_open_buy(self, *, signal, code, name, price, remark):
        current_node = "cooldown_check"
        try:
            cooldown_key = "fq:xtrade:last_new_order_time"
            last_new_order_time = redis_db.get(cooldown_key)
            cooldown_context = {
                "cooldown": {
                    "key": cooldown_key,
                    "active": last_new_order_time is not None,
                    "last_value": last_new_order_time,
                    "cooldown_minutes": 15,
                }
            }
            if last_new_order_time is not None:
                self._emit_runtime(
                    signal,
                    "cooldown_check",
                    action="buy",
                    status="skipped",
                    reason_code="new_open_cooldown_active",
                    decision_branch="new_open_cooldown",
                    decision_expr="last_new_order_time is None",
                    decision_context=cooldown_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code="new_open_cooldown_active",
                    outcome="skip",
                    decision_branch="new_open_cooldown",
                    decision_expr="last_new_order_time is None",
                    decision_context=cooldown_context,
                )
                logger.info(
                    f"上次新开仓下单时间未超过15分钟，不再自动买入：{last_new_order_time}"
                )
                return

            self._emit_runtime(
                signal,
                "cooldown_check",
                action="buy",
                status="success",
                decision_branch="new_open_cooldown",
                decision_expr="last_new_order_time is None",
                decision_context=cooldown_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "quantity_check"
            decision = get_guardian_buy_grid_service().build_new_open_decision(
                code, price
            )
            if decision.get("quantity", 0) <= 0:
                quantity_context = {
                    "quantity": {
                        "quantity": decision.get("quantity", 0),
                        "path": decision.get("path"),
                        "set_new_open_cooldown": True,
                    }
                }
                self._emit_runtime(
                    signal,
                    "quantity_check",
                    action="buy",
                    status="skipped",
                    reason_code="new_open_quantity_insufficient",
                    decision_branch="new_open_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code="new_open_quantity_insufficient",
                    outcome="skip",
                    decision_branch="new_open_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                )
                logger.info(
                    "{code} {name} 新开仓可交易数量不足，跳过下单",
                    code=code,
                    name=name,
                )
                return

            current_node = "submit_intent"
            self._submit_buy_order(
                signal=signal,
                code=code,
                price=price,
                remark=remark,
                decision=decision,
                set_new_open_cooldown=True,
                quantity_reason_code="new_open_quantity_insufficient",
                submit_branch="new_open",
            )
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_unexpected_exception(
                    signal,
                    node=current_node,
                    action="buy",
                    exc=exc,
                )
            raise

    def _submit_buy_order(
        self,
        *,
        signal,
        code,
        price,
        remark,
        decision,
        set_new_open_cooldown,
        quantity_reason_code,
        submit_branch,
    ):
        current_node = "quantity_check"
        try:
            quantity = int(decision.get("quantity") or 0)
            quantity_context = {
                "quantity": {
                    "quantity": quantity,
                    "path": decision.get("path"),
                    "grid_level": decision.get("grid_level"),
                    "source_price": decision.get("source_price"),
                    "set_new_open_cooldown": set_new_open_cooldown,
                }
            }
            if quantity <= 0:
                self._emit_runtime(
                    signal,
                    "quantity_check",
                    action="buy",
                    status="skipped",
                    reason_code=quantity_reason_code,
                    decision_branch=f"{submit_branch}_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code=quantity_reason_code,
                    outcome="skip",
                    decision_branch=f"{submit_branch}_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                )
                logger.info("{code} 买入数量无效，跳过下单", code=code)
                return

            self._emit_runtime(
                signal,
                "quantity_check",
                action="buy",
                status="success",
                decision_branch=f"{submit_branch}_quantity",
                decision_expr="quantity > 0",
                decision_context=quantity_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "cooldown_check"
            cooldown_key = f"buy:{code}"
            cooldown_active = redis_db.get(cooldown_key) is not None
            cooldown_context = {
                "cooldown": {
                    "key": cooldown_key,
                    "active": cooldown_active,
                    "cooldown_minutes": 15,
                }
            }
            if cooldown_active:
                self._emit_runtime(
                    signal,
                    "cooldown_check",
                    action="buy",
                    status="skipped",
                    reason_code="buy_cooldown_active",
                    decision_branch=f"{submit_branch}_buy_cooldown",
                    decision_expr="buy_cooldown is None",
                    decision_context=cooldown_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code="buy_cooldown_active",
                    outcome="skip",
                    decision_branch=f"{submit_branch}_buy_cooldown",
                    decision_expr="buy_cooldown is None",
                    decision_context=cooldown_context,
                )
                logger.info("{code} 买入冷却中，跳过下单", code=code)
                return

            self._emit_runtime(
                signal,
                "cooldown_check",
                action="buy",
                status="success",
                decision_branch=f"{submit_branch}_buy_cooldown",
                decision_expr="buy_cooldown is None",
                decision_context=cooldown_context,
                decision_outcome={"outcome": "pass"},
            )

            strategy_context = {
                "guardian_buy_grid": {
                    "path": decision.get("path"),
                    "grid_level": decision.get("grid_level"),
                    "hit_levels": list(decision.get("hit_levels") or []),
                    "signal_time": self._json_safe(signal.get("fire_time")),
                    "multiplier": decision.get("multiplier", 1),
                    "source_price": decision.get("source_price"),
                    "buy_prices_snapshot": decision.get("buy_prices_snapshot"),
                    "buy_active_before": decision.get("buy_active_before"),
                    "initial_amount": decision.get("initial_amount"),
                    "base_amount": decision.get("base_amount"),
                }
            }

            current_node = "submit_intent"
            signal["quantity"] = quantity
            signal.setdefault("intent_id", new_intent_id())
            self._emit_runtime(
                signal,
                "submit_intent",
                action="buy",
                status="success",
                decision_branch=submit_branch,
                decision_expr="quantity > 0 and cooldown_inactive",
                decision_context=quantity_context,
                decision_outcome={"outcome": "submit"},
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
                rejection_context = {
                    "quantity": quantity_context["quantity"],
                    "position_management": {
                        "action": "buy",
                        "reason": str(exc),
                    },
                }
                self._emit_runtime(
                    signal,
                    "position_management_check",
                    action="buy",
                    status="failed",
                    reason_code="position_management_rejected",
                    decision_branch=f"{submit_branch}_position_management",
                    decision_expr="position_management_accepts",
                    decision_context=rejection_context,
                    decision_outcome={"outcome": "reject"},
                    payload={"reason": str(exc)},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="failed",
                    reason_code="position_management_rejected",
                    outcome="reject",
                    decision_branch=f"{submit_branch}_position_management",
                    decision_expr="position_management_accepts",
                    decision_context=rejection_context,
                )
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
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_unexpected_exception(
                    signal,
                    node=current_node,
                    action="buy",
                    exc=exc,
                )
            raise

    def _handle_sell(self, *, signal, code, name, fire_time, price, remark):
        current_node = "timing_check"
        try:
            fill_list = get_arranged_stock_fill_list(code) or []
            last_fill = fill_list[-1] if fill_list else None
            if last_fill is None:
                arrangement_scope = _resolve_guardian_arrangement_scope(code)
                arrangement_state = arrangement_scope["arrangement_state"]
                reason_code = {
                    "entry_present_arrangement_degraded": "arrangement_degraded",
                    "entry_present_without_slices": "entry_without_slices",
                }.get(arrangement_state, "no_holding_fill")
                holding_context = {
                    "scope": {
                        "position": "SELL_SHORT",
                        "fill_count": 0,
                        "in_holding": arrangement_scope["entry_count"] > 0,
                        "entry_count": arrangement_scope["entry_count"],
                        "degraded_entry_count": arrangement_scope[
                            "degraded_entry_count"
                        ],
                        "remaining_quantity": arrangement_scope["remaining_quantity"],
                        "arrangement_state": arrangement_state,
                    }
                }
                self._emit_runtime(
                    signal,
                    "holding_scope_resolve",
                    action="sell",
                    status="skipped",
                    reason_code=reason_code,
                    decision_branch="sell_fill_scope",
                    decision_expr="fill_count > 0",
                    decision_context=holding_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code=reason_code,
                    outcome="skip",
                    decision_branch="sell_fill_scope",
                    decision_expr="fill_count > 0",
                    decision_context=holding_context,
                )
                message = {
                    "arrangement_degraded": "持仓已确认但 arranged fills 降级缺失，跳过下单指令",
                    "entry_without_slices": "持仓 entry 已存在但无 arranged fills，跳过下单指令",
                }.get(reason_code, "无 arranged fills，跳过下单指令")
                logger.info(message)
                return

            last_fill_dt = datetime.strptime(
                "%s %s" % (str(last_fill["date"]), last_fill["time"]),
                "%Y%m%d %H:%M:%S",
            )
            last_fill_dt = fq_util_datetime_localize(last_fill_dt)
            timing_context = {
                "timing": {
                    "fire_time": fire_time,
                    "last_fill_time": last_fill_dt,
                }
            }
            if fire_time < last_fill_dt:
                self._emit_runtime(
                    signal,
                    "timing_check",
                    action="sell",
                    status="skipped",
                    reason_code="signal_before_last_fill",
                    decision_branch="fill_ordering",
                    decision_expr="fire_time >= last_fill_time",
                    decision_context=timing_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="signal_before_last_fill",
                    outcome="skip",
                    decision_branch="fill_ordering",
                    decision_expr="fire_time >= last_fill_time",
                    decision_context=timing_context,
                )
                logger.info("触发时间异常，跳过下单指令")
                return

            self._emit_runtime(
                signal,
                "timing_check",
                action="sell",
                status="success",
                decision_branch="fill_ordering",
                decision_expr="fire_time >= last_fill_time",
                decision_context=timing_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "price_threshold_check"
            last_fill_price = last_fill["price"]
            threshold = eval_stock_threshold_price(code, last_fill_price)
            threshold_context = {
                "threshold": {
                    "current_price": price,
                    "last_fill_price": last_fill_price,
                    "bot_river_price": threshold.get("bot_river_price"),
                    "top_river_price": threshold.get("top_river_price"),
                }
            }
            if price < threshold["top_river_price"]:
                self._emit_runtime(
                    signal,
                    "price_threshold_check",
                    action="sell",
                    status="skipped",
                    reason_code="sell_threshold_not_met",
                    decision_branch="profit_take_threshold",
                    decision_expr="current_price >= top_river_price",
                    decision_context=threshold_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="sell_threshold_not_met",
                    outcome="skip",
                    decision_branch="profit_take_threshold",
                    decision_expr="current_price >= top_river_price",
                    decision_context=threshold_context,
                )
                logger.info("条件未达，跳过下单指令")
                return

            self._emit_runtime(
                signal,
                "price_threshold_check",
                action="sell",
                status="success",
                decision_branch="profit_take_threshold",
                decision_expr="current_price >= top_river_price",
                decision_context=threshold_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "quantity_check"
            quantity = 0
            profitable_fill_count = 0
            for i in range(len(fill_list) - 1, -1, -1):
                if price > fill_list[i]["price"]:
                    quantity = quantity + fill_list[i]["quantity"]
                    profitable_fill_count += 1
                else:
                    break

            quantity_context = {
                "quantity": {
                    "quantity": quantity,
                    "profitable_fill_count": profitable_fill_count,
                    "fill_count": len(fill_list),
                }
            }
            if quantity <= 0:
                self._emit_runtime(
                    signal,
                    "quantity_check",
                    action="sell",
                    status="skipped",
                    reason_code="no_profitable_quantity",
                    decision_branch="sell_profitable_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="no_profitable_quantity",
                    outcome="skip",
                    decision_branch="sell_profitable_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                )
                logger.info("{code} {name} 当前无可卖盈利切片", code=code, name=name)
                return

            self._emit_runtime(
                signal,
                "quantity_check",
                action="sell",
                status="success",
                decision_branch="sell_profitable_quantity",
                decision_expr="quantity > 0",
                decision_context=quantity_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "sellable_volume_check"
            requested_quantity = int(quantity or 0)
            sell_quantity = resolve_sell_submission_quantity(
                requested_quantity=quantity,
                can_use_volume=_get_position_reader().get_can_use_volume(code),
            )
            sellable_context = {
                "quantity": {
                    **quantity_context["quantity"],
                    "raw_quantity": int(sell_quantity["raw_quantity"] or 0),
                    "can_use_volume": int(sell_quantity["can_use_volume"] or 0),
                    "quantity_cap": int(sell_quantity["quantity_cap"] or 0),
                    "submit_quantity": int(sell_quantity["quantity"] or 0),
                }
            }
            if sell_quantity["status"] != "ready":
                reason_code = {
                    "can_use_volume": "sell_can_use_volume_blocked",
                    "board_lot": "sell_board_lot_blocked",
                }.get(sell_quantity["blocked_reason"], "sell_quantity_invalid")
                self._emit_runtime(
                    signal,
                    "sellable_volume_check",
                    action="sell",
                    status="skipped",
                    reason_code=reason_code,
                    decision_branch="sell_submit_quantity",
                    decision_expr="submit_quantity >= 100 and submit_quantity <= can_use_volume",
                    decision_context=sellable_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code=reason_code,
                    outcome="skip",
                    decision_branch="sell_submit_quantity",
                    decision_expr="submit_quantity >= 100 and submit_quantity <= can_use_volume",
                    decision_context=sellable_context,
                )
                if sell_quantity["blocked_reason"] == "can_use_volume":
                    logger.info(
                        "{code} {name} 当前可卖数量不足，跳过下单", code=code, name=name
                    )
                else:
                    logger.info(
                        "{code} {name} 当前可卖数量不足一手，跳过下单",
                        code=code,
                        name=name,
                    )
                return

            quantity = int(sell_quantity["quantity"])
            quantity_context = sellable_context
            self._emit_runtime(
                signal,
                "sellable_volume_check",
                action="sell",
                status="success",
                decision_branch="sell_submit_quantity",
                decision_expr="submit_quantity >= 100 and submit_quantity <= can_use_volume",
                decision_context=quantity_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "cooldown_check"
            cooldown_key = f"sell:{code}"
            cooldown_active = redis_db.get(cooldown_key) is not None
            cooldown_context = {
                "cooldown": {
                    "key": cooldown_key,
                    "active": cooldown_active,
                    "cooldown_minutes": 15,
                }
            }
            if cooldown_active:
                self._emit_runtime(
                    signal,
                    "cooldown_check",
                    action="sell",
                    status="skipped",
                    reason_code="sell_cooldown_active",
                    decision_branch="sell_cooldown",
                    decision_expr="sell_cooldown is None",
                    decision_context=cooldown_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="sell_cooldown_active",
                    outcome="skip",
                    decision_branch="sell_cooldown",
                    decision_expr="sell_cooldown is None",
                    decision_context=cooldown_context,
                )
                logger.info("{code} 卖出冷却中，跳过下单", code=code)
                return

            self._emit_runtime(
                signal,
                "cooldown_check",
                action="sell",
                status="success",
                decision_branch="sell_cooldown",
                decision_expr="sell_cooldown is None",
                decision_context=cooldown_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "submit_intent"
            signal["quantity"] = quantity
            signal.setdefault("intent_id", new_intent_id())
            strategy_context = _build_guardian_sell_strategy_context(
                fill_list,
                requested_quantity=requested_quantity,
                submit_quantity=quantity,
                profitable_fill_count=profitable_fill_count,
            )
            self._emit_runtime(
                signal,
                "submit_intent",
                action="sell",
                status="success",
                decision_branch="sell_profit_take",
                decision_expr="quantity > 0 and cooldown_inactive",
                decision_context=quantity_context,
                decision_outcome={"outcome": "submit"},
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
                    strategy_context=strategy_context,
                )
            except PositionManagementRejectedError as exc:
                rejection_context = {
                    "quantity": quantity_context["quantity"],
                    "position_management": {
                        "action": "sell",
                        "reason": str(exc),
                    },
                }
                self._emit_runtime(
                    signal,
                    "position_management_check",
                    action="sell",
                    status="failed",
                    reason_code="position_management_rejected",
                    decision_branch="sell_position_management",
                    decision_expr="position_management_accepts",
                    decision_context=rejection_context,
                    decision_outcome={"outcome": "reject"},
                    payload={"reason": str(exc)},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="failed",
                    reason_code="position_management_rejected",
                    outcome="reject",
                    decision_branch="sell_position_management",
                    decision_expr="position_management_accepts",
                    decision_context=rejection_context,
                )
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
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_unexpected_exception(
                    signal,
                    node=current_node,
                    action="sell",
                    exc=exc,
                )
            raise

    def _evaluate_signal_structure(self, *, code, name, fire_time, fills, zsdata):
        structure_context = {
            "signal_structure": {
                "fire_time": fire_time,
                "fill_count": len(fills or []),
                "zs_count": len(zsdata or []),
            }
        }
        if fills is None or len(fills) == 0:
            structure_context["signal_structure"]["requires_zs"] = False
            return {
                "passed": True,
                "reason_code": "",
                "decision_branch": "no_fill_history",
                "decision_context": structure_context,
            }
        fill_time = str(fills[-1]["date"]) + " " + fills[-1]["time"]
        fill_time = datetime.strptime(fill_time, "%Y%m%d %H:%M:%S").replace(
            tzinfo=pendulum.local_timezone()
        )
        structure_context["signal_structure"]["fill_time"] = fill_time
        structure_context["signal_structure"]["fill_price"] = fills[-1].get("price")
        if zsdata is None or len(zsdata) == 0:
            structure_context["signal_structure"]["requires_zs"] = True
            logger.info("{code} {name} 没有中枢，跳过下单指令", code=code, name=name)
            return {
                "passed": False,
                "reason_code": "signal_structure_missing_zs",
                "decision_branch": "missing_zs",
                "decision_context": structure_context,
            }
        for zs in reversed(zsdata):
            zs_start = datetime.strptime(zs[0][0], "%Y-%m-%d %H:%M").replace(
                tzinfo=pendulum.local_timezone()
            )
            zs_end = datetime.strptime(zs[1][0], "%Y-%m-%d %H:%M").replace(
                tzinfo=pendulum.local_timezone()
            )
            structure_context["signal_structure"]["candidate_zs"] = {
                "start": zs_start,
                "end": zs_end,
                "low_1": zs[0][1],
                "low_2": zs[1][1],
            }
            if (
                fire_time >= zs_end
                and fill_time <= zs_start
                and fills[-1]["price"] > zs[0][1]
                and fills[-1]["price"] > zs[1][1]
            ):
                structure_context["signal_structure"]["separating"] = True
                return {
                    "passed": True,
                    "reason_code": "",
                    "decision_branch": "separating_zs",
                    "decision_context": structure_context,
                }
        structure_context["signal_structure"]["separating"] = False
        logger.info("{code} {name} 无相隔中枢，跳过下单指令", code=code, name=name)
        return {
            "passed": False,
            "reason_code": "signal_structure_not_separating",
            "decision_branch": "no_separating_zs",
            "decision_context": structure_context,
        }

    def _resolve_action(self, position):
        return "buy" if position == "BUY_LONG" else "sell"

    def _emit_finish(
        self,
        signal,
        *,
        action,
        status,
        reason_code,
        outcome,
        decision_branch="",
        decision_expr="",
        decision_context=None,
        payload=None,
    ):
        self._emit_runtime(
            signal,
            "finish",
            action=action,
            status=status,
            reason_code=reason_code,
            decision_branch=decision_branch,
            decision_expr=decision_expr,
            decision_context=decision_context,
            decision_outcome={
                "outcome": outcome,
                "reason_code": reason_code,
            },
            payload=payload,
        )

    def _build_signal_summary(self, signal):
        return {
            "code": signal.get("code"),
            "name": signal.get("name"),
            "position": signal.get("position"),
            "period": signal.get("period"),
            "price": signal.get("price"),
            "fire_time": signal.get("fire_time"),
            "discover_time": signal.get("discover_time"),
            "remark": signal.get("remark"),
            "tags": list(signal.get("tags") or []),
        }

    def _json_safe(self, value):
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        if isinstance(value, datetime):
            return value.astimezone().isoformat()
        if hasattr(value, "isoformat") and callable(value.isoformat):
            try:
                return value.isoformat()
            except TypeError:
                pass
        return value

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
        decision_branch="",
        decision_expr="",
        decision_context=None,
        decision_outcome=None,
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
            "decision_branch": decision_branch,
            "decision_expr": decision_expr,
            "signal_summary": self._json_safe(self._build_signal_summary(signal)),
            "decision_context": self._json_safe(decision_context or {}),
            "decision_outcome": self._json_safe(decision_outcome or {}),
            "payload": self._json_safe(dict(payload or {})),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return

    def _emit_unexpected_exception(self, signal, *, node, action, exc):
        self._emit_runtime(
            signal,
            node,
            action=action,
            status="error",
            reason_code="unexpected_exception",
            decision_outcome={"outcome": "error"},
            payload=build_exception_payload(exc),
        )
        mark_exception_emitted(exc)

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
_position_reader = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("guardian_strategy")
    return _runtime_logger


def _get_position_reader():
    global _position_reader
    if _position_reader is None:
        _position_reader = PositionVolumeReader(DBfreshquant)
    return _position_reader


def _resolve_guardian_arrangement_scope(code):
    entries = list_open_entry_views(symbol=code)
    open_entries = [
        item for item in entries if int(item.get("remaining_quantity") or 0) > 0
    ]
    degraded_entries = [
        item
        for item in open_entries
        if bool(item.get("arrange_degraded"))
        or str(item.get("arrange_status") or "").upper() == "DEGRADED"
    ]
    if degraded_entries:
        arrangement_state = "entry_present_arrangement_degraded"
    elif open_entries:
        arrangement_state = "entry_present_without_slices"
    else:
        arrangement_state = "entry_absent"
    return {
        "arrangement_state": arrangement_state,
        "entry_count": len(open_entries),
        "degraded_entry_count": len(degraded_entries),
        "remaining_quantity": sum(
            int(item.get("remaining_quantity") or 0) for item in open_entries
        ),
    }


def _build_guardian_sell_strategy_context(
    fill_list,
    *,
    requested_quantity,
    submit_quantity,
    profitable_fill_count,
):
    source_entries = _resolve_guardian_sell_source_entries(
        fill_list,
        quantity=submit_quantity,
    )
    if not source_entries:
        return None
    return {
        "guardian_sell_sources": {
            "profitable_fill_count": int(profitable_fill_count or 0),
            "requested_quantity": int(requested_quantity or 0),
            "submit_quantity": int(submit_quantity or 0),
            "entries": source_entries,
        }
    }


def _resolve_guardian_sell_source_entries(fill_list, *, quantity):
    return build_guardian_sell_source_entries(fill_list, quantity=quantity)
