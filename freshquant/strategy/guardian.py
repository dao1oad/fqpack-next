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
from freshquant.order_management.entry_adapter import (
    list_open_entry_views,
    position_type_of,
)
from freshquant.order_management.guardian.sell_semantics import (
    build_guardian_sell_source_plan_v2,
)
from freshquant.order_management.guardian.slice_evaluation import (
    evaluate_guardian_sell_slices,
    resolve_sell_threshold_config,
)
from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    normalize_ledger_intent,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.sell_constraints import (
    PositionVolumeReader,
    resolve_sell_submission_quantity,
)
from freshquant.order_management.submit.guardian import submit_guardian_order
from freshquant.order_management.time_helpers import beijing_datetime_from_epoch
from freshquant.pool.general import queryMustPoolCodes
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
from freshquant.runtime_observability.ids import new_intent_id, new_trace_id
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.strategy.common import get_trade_amount
from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service
from freshquant.strategy.toolkit.threshold import eval_stock_threshold_price
from freshquant.util.datetime_helper import fq_util_datetime_localize

order_alert = signal("order_alert")
MUST_POOL_5M_NEW_OPEN_TAG = "must_pool_5m_new_open"


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
            has_must_pool_5m_new_open_tag = MUST_POOL_5M_NEW_OPEN_TAG in tags
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
                    "has_must_pool_5m_new_open_tag": (has_must_pool_5m_new_open_tag),
                }
            }
            scope_decision_expr = (
                "(position == BUY_LONG and ((has_must_pool_5m_new_open_tag and "
                "in_must_pool and not in_holding) or "
                "(not has_must_pool_5m_new_open_tag and in_holding))) or "
                "(position == SELL_SHORT and in_holding)"
            )
            eligible = False
            scope_branch = "unsupported_position"
            scope_reason_code = "unsupported_position"
            if position == "BUY_LONG":
                if has_must_pool_5m_new_open_tag:
                    if in_holding:
                        scope_branch = "must_pool_5m_new_open_already_holding"
                        scope_reason_code = "must_pool_5m_new_open_already_holding"
                    elif not in_must_pool:
                        scope_branch = "must_pool_5m_new_open_not_in_pool"
                        scope_reason_code = "must_pool_5m_new_open_not_in_pool"
                    else:
                        eligible = True
                        scope_branch = "must_pool_5m_new_open_buy"
                        scope_reason_code = ""
                elif in_holding:
                    eligible = True
                    scope_branch = "holding_buy"
                    scope_reason_code = ""
                elif in_must_pool:
                    scope_branch = "must_pool_5m_new_open_tag_missing"
                    scope_reason_code = "must_pool_5m_new_open_tag_missing"
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
                decision_expr=scope_decision_expr,
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
                    decision_expr=scope_decision_expr,
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
                    if has_must_pool_5m_new_open_tag:
                        self._handle_new_open_buy(
                            signal=signal,
                            code=code,
                            name=name,
                            price=price,
                            remark=remark,
                        )
                    elif in_holding:
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
            fill_reference = _resolve_guardian_buy_fill_reference(code)
            last_fill_dt = None
            last_fill_price = None
            last_fill_source = None
            if fill_reference is not None:
                last_fill_dt = fill_reference["fill_time"]
                last_fill_price = fill_reference["fill_price"]
                last_fill_source = fill_reference["fill_reference_source"]

            if last_fill_dt is not None:
                timing_context = {
                    "timing": {
                        "fire_time": fire_time,
                        "last_fill_time": last_fill_dt,
                        "fill_reference_source": last_fill_source,
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
                threshold = _resolve_guardian_buy_threshold(code, fill_reference)
                threshold_context = {
                    "threshold": {
                        "current_price": price,
                        "last_fill_price": last_fill_price,
                        "fill_reference_source": last_fill_source,
                        "threshold_rule_source": threshold.get("threshold_rule_source"),
                        "grid_interval": threshold.get("grid_interval"),
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
                reason_code = (
                    decision.get("skip_reason") or "new_open_quantity_insufficient"
                )
                quantity_context = {
                    "quantity": {
                        "quantity": decision.get("quantity", 0),
                        "path": decision.get("path"),
                        "skip_reason": decision.get("skip_reason"),
                        "stage": decision.get("stage"),
                        "effective_stage_cap": decision.get("effective_stage_cap"),
                        "current_market_value": decision.get("current_market_value"),
                        "remaining_amount": decision.get("remaining_amount"),
                        "base_quantity": decision.get("base_quantity"),
                        "capacity_quantity": decision.get("capacity_quantity"),
                        "capacity_ratio": decision.get("capacity_ratio"),
                        "set_new_open_cooldown": True,
                    }
                }
                self._emit_runtime(
                    signal,
                    "quantity_check",
                    action="buy",
                    status="skipped",
                    reason_code=reason_code,
                    decision_branch="new_open_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code=reason_code,
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
                    "skip_reason": decision.get("skip_reason"),
                    "stage": decision.get("stage"),
                    "effective_stage_cap": decision.get("effective_stage_cap"),
                    "current_market_value": decision.get("current_market_value"),
                    "remaining_amount": decision.get("remaining_amount"),
                    "base_quantity": decision.get("base_quantity"),
                    "capacity_quantity": decision.get("capacity_quantity"),
                    "capacity_ratio": decision.get("capacity_ratio"),
                    "set_new_open_cooldown": set_new_open_cooldown,
                }
            }
            if quantity <= 0:
                reason_code = decision.get("skip_reason") or quantity_reason_code
                self._emit_runtime(
                    signal,
                    "quantity_check",
                    action="buy",
                    status="skipped",
                    reason_code=reason_code,
                    decision_branch=f"{submit_branch}_quantity",
                    decision_expr="quantity > 0",
                    decision_context=quantity_context,
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code=reason_code,
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

            active_order_result = _prepare_guardian_buy_orders(code)
            if active_order_result["blocked"]:
                self._emit_finish(
                    signal,
                    action="buy",
                    status="skipped",
                    reason_code=active_order_result["reason_code"],
                    outcome="skip",
                    decision_branch=f"{submit_branch}_active_buy_orders",
                    decision_expr="no_active_buy_orders",
                    decision_context={"orders": active_order_result},
                )
                return

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
                    "skip_reason": decision.get("skip_reason"),
                    "stage": decision.get("stage"),
                    "effective_stage_cap": decision.get("effective_stage_cap"),
                    "current_market_value": decision.get("current_market_value"),
                    "remaining_amount": decision.get("remaining_amount"),
                    "base_quantity": decision.get("base_quantity"),
                    "capacity_quantity": decision.get("capacity_quantity"),
                    "capacity_ratio": decision.get("capacity_ratio"),
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
                    ledger_intent=_resolve_guardian_buy_intent(decision),
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
            # #549：Guardian 只卖 T（不动底仓；底仓由 TPSL 止盈卖出）。
            t_fill_list = [
                item
                for item in fill_list
                if position_type_of(item.get("position_type")) == "t"
            ]
            if fill_list and not t_fill_list:
                self._emit_runtime(
                    signal,
                    "holding_scope_resolve",
                    action="sell",
                    status="skipped",
                    reason_code="no_t_position",
                    decision_branch="sell_ledger_scope",
                    decision_expr="t_slice_count > 0",
                    decision_context={
                        "scope": {
                            "position": "SELL_SHORT",
                            "t_slice_count": 0,
                            "base_slice_count": len(fill_list),
                        }
                    },
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="no_t_position",
                    outcome="skip",
                    decision_branch="sell_ledger_scope",
                    decision_expr="t_slice_count > 0",
                    decision_context={
                        "scope": {
                            "position": "SELL_SHORT",
                            "t_slice_count": 0,
                            "base_slice_count": len(fill_list),
                        }
                    },
                )
                logger.info(
                    "{code} {name} 无做T切片（纯底仓由 TPSL 卖出），跳过下单指令",
                    code=code,
                    name=name,
                )
                return
            fill_list = t_fill_list
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

            fill_reference = _build_arranged_fill_reference(
                last_fill,
                source="guardian_arranged_fill",
            )
            last_fill_dt = fill_reference["fill_time"]
            timing_context = {
                "timing": {
                    "fire_time": fire_time,
                    "last_fill_time": last_fill_dt,
                    "fill_reference_source": fill_reference["fill_reference_source"],
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
            last_fill_price = fill_reference["fill_price"]
            threshold = eval_stock_threshold_price(code, last_fill_price)
            threshold_config = _resolve_guardian_sell_threshold_config(threshold)
            sell_evaluation = evaluate_guardian_sell_slices(
                fill_list,
                signal_price=price,
                threshold_config=threshold_config,
            )
            threshold_context = {
                "threshold": {
                    "current_price": price,
                    "last_fill_price": last_fill_price,
                    "fill_reference_source": fill_reference["fill_reference_source"],
                    "bot_river_price": threshold.get("bot_river_price"),
                    "top_river_price": threshold.get("top_river_price"),
                    "threshold_mode": threshold_config["mode"],
                    "eligible_slice_count": len(sell_evaluation["eligible_slices"]),
                    "threshold_evidence": sell_evaluation["threshold_evidence"],
                }
            }
            if sell_evaluation["raw_quantity"] <= 0:
                self._emit_runtime(
                    signal,
                    "price_threshold_check",
                    action="sell",
                    status="skipped",
                    reason_code="sell_threshold_not_met",
                    decision_branch="profit_take_threshold",
                    decision_expr="per_slice_threshold_met_quantity > 0",
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
                    decision_expr="per_slice_threshold_met_quantity > 0",
                    decision_context=threshold_context,
                )
                logger.info("条件未达，跳过下单指令")
                return

            # mount 过滤（#549）：可卖金额 < mount → 本次不卖，可卖 slices
            # 保留，不消耗 sell:<code> 冷却。
            mount_amount = int(get_trade_amount(code) or 0)
            sellable_amount = sum(
                int(item.get("eligible_quantity") or 0)
                * float(item.get("guardian_price_normalized") or 0.0)
                for item in sell_evaluation["eligible_slices"]
            )
            if mount_amount > 0 and sellable_amount < mount_amount:
                self._emit_runtime(
                    signal,
                    "price_threshold_check",
                    action="sell",
                    status="skipped",
                    reason_code="below_mount",
                    decision_branch="sell_mount",
                    decision_expr="sellable_amount >= mount",
                    decision_context={
                        "mount": {
                            "mount_amount": mount_amount,
                            "sellable_amount": round(sellable_amount, 2),
                        }
                    },
                    decision_outcome={"outcome": "skip"},
                )
                self._emit_finish(
                    signal,
                    action="sell",
                    status="skipped",
                    reason_code="below_mount",
                    outcome="skip",
                    decision_branch="sell_mount",
                    decision_expr="sellable_amount >= mount",
                    decision_context={
                        "mount": {
                            "mount_amount": mount_amount,
                            "sellable_amount": round(sellable_amount, 2),
                        }
                    },
                )
                logger.info(
                    "{code} {name} 可卖金额低于 mount，跳过下单指令",
                    code=code,
                    name=name,
                )
                return

            self._emit_runtime(
                signal,
                "price_threshold_check",
                action="sell",
                status="success",
                decision_branch="profit_take_threshold",
                decision_expr="per_slice_threshold_met_quantity > 0",
                decision_context=threshold_context,
                decision_outcome={"outcome": "pass"},
            )

            current_node = "quantity_check"
            quantity = int(sell_evaluation["raw_quantity"] or 0)
            profitable_fill_count = len(sell_evaluation["eligible_slices"])

            quantity_context = {
                "quantity": {
                    "quantity": quantity,
                    "profitable_fill_count": profitable_fill_count,
                    "fill_count": len(fill_list),
                    "eligible_slice_ids": [
                        item.get("entry_slice_id")
                        for item in sell_evaluation["eligible_slices"]
                    ],
                    "threshold_evidence": sell_evaluation["threshold_evidence"],
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
                eligible_evidence=sell_evaluation["eligible_slices"],
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
                    ledger_intent="t",
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
        ledger_intent=None,
    ):
        submit_kwargs = {
            "remark": remark,
            "is_profitable": is_profitable,
            "strategy_context": strategy_context,
            # #571：最终架构直接强制传 ledger_intent，无兼容垫片。
            "ledger_intent": ledger_intent,
            # #571：trace_id / intent_id 也强制统一直传，无参数探测垫片。
            "trace_id": signal.get("trace_id"),
            "intent_id": signal.get("intent_id"),
        }
        return submit_guardian_order(
            action,
            code,
            price,
            quantity,
            **submit_kwargs,
        )


_runtime_logger = None
_position_reader = None
_order_management_repository = None


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


def _get_order_management_repository():
    global _order_management_repository
    if _order_management_repository is None:
        _order_management_repository = OrderManagementRepository()
    return _order_management_repository


def _prepare_guardian_buy_orders(code):
    states = {
        "ACCEPTED",
        "QUEUED",
        "SUBMITTING",
        "SUBMITTED",
        "PARTIAL_FILLED",
        "BROKER_BYPASSED",
        "CANCEL_REQUESTED",
        "INFERRED_PENDING",
    }
    repository = _get_order_management_repository()
    if not hasattr(repository, "list_broker_orders"):
        return {
            "blocked": False,
            "reason_code": None,
            "count": 0,
            "canceled": 0,
            "waiting": 0,
            "unmapped": 0,
        }
    orders = [
        item
        for item in repository.list_broker_orders(symbol=code, states=states)
        if str(item.get("side") or "").lower() == "buy"
    ]
    # #549：跳过 base_line（买入线补仓）在途买单——buy 线评估器不复用本函数，
    # 若不跳过会误杀 buy 线补仓单。
    orders = [item for item in orders if not _is_base_line_buy_order(repository, item)]
    if not orders:
        return {
            "blocked": False,
            "reason_code": None,
            "count": 0,
            "canceled": 0,
            "waiting": 0,
            "unmapped": 0,
        }
    from freshquant.order_management.submit.service import OrderSubmitService

    canceled = 0
    waiting = 0
    unmapped = 0
    for order in orders:
        state = str(order.get("state") or "").upper()
        source = str(order.get("source_type") or "").lower()
        broker_order_id = order.get("broker_order_id")
        if state in {"CANCEL_REQUESTED", "INFERRED_PENDING"} or source in {
            "external_reported",
            "external_inferred",
        }:
            waiting += 1
            continue
        if state == "BROKER_BYPASSED" and not broker_order_id:
            waiting += 1
            continue
        internal_order_id = order.get("internal_order_id")
        if not internal_order_id:
            waiting += 1
            unmapped += 1
            continue
        OrderSubmitService().cancel_order(
            {
                "internal_order_id": internal_order_id,
                "source": "guardian_replace_buy",
                "strategy_name": "Guardian",
                "remark": "cancel active buy before recalculation",
            }
        )
        canceled += 1
    reason = (
        "active_buy_orders_cancel_requested"
        if canceled
        else "active_buy_orders_waiting"
    )
    return {
        "blocked": True,
        "reason_code": reason,
        "count": len(orders),
        "canceled": canceled,
        "waiting": waiting,
        "unmapped": unmapped,
    }


def _is_base_line_buy_order(repository, order):
    """判断某在途买单是否属于买入线（base_line）系统。"""

    internal_order_id = str(order.get("internal_order_id") or "").strip()
    if not internal_order_id or not hasattr(repository, "find_order"):
        return False
    try:
        order_doc = repository.find_order(internal_order_id) or {}
    except Exception:
        return False
    request_id = str(order_doc.get("request_id") or "").strip()
    if request_id and hasattr(repository, "find_order_request"):
        try:
            request = repository.find_order_request(request_id) or {}
        except Exception:
            request = {}
    else:
        request = {}
    context = dict((request or {}).get("strategy_context") or {})
    # #571：base_line 判定 = guardian_buy_grid.path（运行态策略语义）
    # + ledger_intent=base；旧 buy_ledger 字段不再参与。
    grid = dict(context.get("guardian_buy_grid") or {})
    return (
        str(grid.get("path") or "").strip().lower() == "base_line"
        and normalize_ledger_intent(request.get("ledger_intent")) == LEDGER_BASE
    )


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
    eligible_evidence=None,
):
    eligible_evidence = list(eligible_evidence or [])
    if not eligible_evidence:
        return None
    source_plan = build_guardian_sell_source_plan_v2(
        eligible_evidence,
        requested_quantity=requested_quantity,
        submit_quantity=submit_quantity,
        profitable_fill_count=profitable_fill_count,
    )
    return {'guardian_sell_sources': source_plan}


def _resolve_guardian_buy_intent(decision) -> str:
    """Guardian 买入路径 → ledger_intent（#8：new_open/base_line → base、
    holding_add → t、缺省 base）。"""

    path = str((decision or {}).get("path") or "").strip().lower()
    if path == "holding_add":
        return "t"
    return "base"


def _resolve_guardian_sell_threshold_config(threshold):
    return resolve_sell_threshold_config(threshold)


def _resolve_guardian_buy_fill_reference(code):
    """#549 做T买入门槛基准：execution fill → 平均成本 → xt avg 兜底。

    基准来源优先级：
    1. 最近一笔 execution fill 成交价（含 fill_time，参与时序校验）；
    2. 无成交记录 → 全部持仓（base+T 所有 open entries 按剩余股数加权）
       平均成本价（无 fill_time，跳过时序校验）；
    3. 无 execution fill 且无 OM entries → ``xt_positions.avg_price`` 兜底；
    4. 三者皆无 → 返回 None（不买）。
    """

    execution_fill_reference = _get_latest_execution_fill_reference(code)
    if execution_fill_reference is not None:
        return execution_fill_reference
    ledger_reference = _get_ledger_average_cost_reference(code)
    if ledger_reference is not None:
        return ledger_reference
    return _get_broker_position_average_cost_reference(code)


def _resolve_guardian_buy_threshold(code, fill_reference):
    if fill_reference is None:
        return None
    threshold = dict(eval_stock_threshold_price(code, fill_reference["fill_price"]))
    threshold["threshold_rule_source"] = "threshold_config"
    return threshold


def _get_latest_execution_fill_reference(code):
    repository = _get_order_management_repository()
    execution_fills = repository.list_execution_fills(symbol=code) or []
    valid_fills = [
        item
        for item in execution_fills
        if _coerce_int(item.get("trade_time")) is not None
        and item.get("price") not in {None, ""}
    ]
    if not valid_fills:
        return None
    last_fill = max(valid_fills, key=_execution_fill_sort_key)
    return {
        "fill_time": beijing_datetime_from_epoch(last_fill["trade_time"]),
        "fill_price": float(last_fill["price"]),
        "fill_reference_source": "execution_fill",
    }


def _build_arranged_fill_reference(fill, *, source):
    if fill is None:
        return None
    last_fill_dt = datetime.strptime(
        "%s %s" % (str(fill["date"]), fill["time"]),
        "%Y%m%d %H:%M:%S",
    )
    return {
        "fill_time": fq_util_datetime_localize(last_fill_dt),
        "fill_price": fill["price"],
        "fill_reference_source": source,
    }


def _get_ledger_average_cost_reference(code):
    """无 execution fill 时：全部持仓（base+T）open entries 剩余股数加权成本。"""

    entries = list_open_entry_views(symbol=code)
    open_entries = [
        item for item in entries if int(item.get("remaining_quantity") or 0) > 0
    ]
    if not open_entries:
        return None
    total_quantity = sum(
        int(item.get("remaining_quantity") or 0) for item in open_entries
    )
    if total_quantity <= 0:
        return None
    total_cost = sum(
        int(item.get("remaining_quantity") or 0)
        * float(item.get("entry_price") or item.get("buy_price_real") or 0.0)
        for item in open_entries
    )
    return {
        "fill_time": None,
        "fill_price": round(total_cost / total_quantity, 6),
        "fill_reference_source": "ledger_average_cost",
    }


def _get_broker_position_average_cost_reference(code):
    """无 execution fill 且无 OM entries：xt_positions.avg_price 兜底。"""

    try:
        position = DBfreshquant["xt_positions"].find_one(
            {
                "$or": [
                    {"stock_code": code},
                    {"code": code},
                    {"symbol": code},
                ]
            },
            {"avg_price": 1, "volume": 1},
        )
    except Exception:
        return None
    if not position:
        return None
    if int(position.get("volume") or 0) <= 0:
        return None
    avg_price = position.get("avg_price")
    if avg_price in {None, ""}:
        return None
    try:
        avg_price_float = float(avg_price)
    except (TypeError, ValueError):
        return None
    if avg_price_float <= 0:
        return None
    return {
        "fill_time": None,
        "fill_price": round(avg_price_float, 6),
        "fill_reference_source": "broker_position_avg_price",
    }


def _execution_fill_sort_key(item):
    return (
        _coerce_int(item.get("trade_time")) or -1,
        str(item.get("created_at") or ""),
        str(item.get("broker_trade_id") or ""),
        str(item.get("execution_fill_id") or ""),
    )


def _coerce_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
