# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from freshquant.db import DBfreshquant
from freshquant.order_management.entry_adapter import (
    list_entry_stoploss_bindings_compat,
    list_open_entry_slices_compat,
    position_type_of,
)
from freshquant.order_management.ids import new_event_id
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.sell_constraints import (
    PositionVolumeReader as _PositionReader,
)
from freshquant.order_management.sell_constraints import (
    resolve_sell_submission_quantity as _resolve_sell_submission_quantity,
)
from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
from freshquant.runtime_observability.ids import new_intent_id, new_trace_id
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.tpsl.stoploss_batch import build_stoploss_batch
from freshquant.tpsl.takeprofit_quantity import (
    choose_takeprofit_level,
    resolve_takeprofit_sell_quantity,
)
from freshquant.tpsl.takeprofit_service import TakeprofitService
from freshquant.util.code import normalize_to_base_code

_BUY_LEVEL_INDEX = {"BUY-1": 0, "BUY-2": 1, "BUY-3": 2}
_BASE_BUY_COOLDOWN_SECONDS = 15 * 60
_PENDING_BUY_STATES = {
    "ACCEPTED",
    "QUEUED",
    "SUBMITTING",
    "SUBMITTED",
    "PARTIAL_FILLED",
    "BROKER_BYPASSED",
    "CANCEL_REQUESTED",
    "INFERRED_PENDING",
}

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore


class TpslService:
    def __init__(
        self,
        *,
        takeprofit_service=None,
        order_submit_service=None,
        order_repository=None,
        position_reader=None,
        symbol_stoploss_price_loader=None,
        lock_client=None,
        cooldown_seconds=3,
        runtime_logger=None,
    ):
        self.takeprofit_service = takeprofit_service or TakeprofitService()
        self.order_submit_service = order_submit_service
        self.order_repository = order_repository or OrderManagementRepository()
        self.position_reader = position_reader or _PositionReader(DBfreshquant)
        self.symbol_stoploss_price_loader = (
            symbol_stoploss_price_loader or _default_symbol_stoploss_price_loader
        )
        self.lock_client = lock_client or _CooldownLockClient(redis_db)
        self.cooldown_seconds = max(int(cooldown_seconds or 0), 0)
        self.runtime_logger = runtime_logger or _get_runtime_logger()

    def save_takeprofit_profile(self, symbol, *, tiers, updated_by="system"):
        return self.takeprofit_service.save_profile(
            symbol,
            tiers=tiers,
            updated_by=updated_by,
        )

    def get_takeprofit_profile(self, symbol):
        return self.takeprofit_service.get_profile_with_state(symbol)

    def set_takeprofit_tier_enabled(
        self, symbol, *, level, enabled, updated_by="system"
    ):
        return self.takeprofit_service.set_tier_manual_enabled(
            symbol,
            level=level,
            enabled=enabled,
            updated_by=updated_by,
        )

    def get_takeprofit_state(self, symbol):
        return self.takeprofit_service.get_state(symbol)

    def mark_takeprofit_triggered(
        self,
        *,
        symbol,
        level,
        batch_id,
        updated_by="system",
        trigger_price=None,
        entry_details=None,
        buy_lot_details=None,
    ):
        return self.takeprofit_service.mark_level_triggered(
            symbol,
            level=level,
            batch_id=batch_id,
            updated_by=updated_by,
            trigger_price=trigger_price,
            entry_details=entry_details,
            buy_lot_details=buy_lot_details,
        )

    def mark_stoploss_triggered(self, *, batch):
        repository = getattr(self.takeprofit_service, "repository", None)
        if repository is None or not hasattr(repository, "insert_exit_trigger_event"):
            return None

        scope_type = str(batch.get("scope_type") or "").strip() or "stoploss_batch"
        strategy_name = str(batch.get("strategy_name") or "").strip()
        is_symbol_full_stoploss = scope_type == "symbol_stoploss_batch"
        entry_quantities = dict(batch.get("entry_quantities") or {})
        binding_map = {
            item.get("entry_id"): item
            for item in (batch.get("triggered_bindings") or [])
            if item.get("entry_id")
        }
        fallback_stop_price = _safe_float_or_none(
            batch.get("full_stop_price")
            or batch.get("stop_price")
            or batch.get("price")
        )
        entry_details = []
        for entry_id, quantity in entry_quantities.items():
            detail = {
                "entry_id": entry_id,
                "quantity": int(quantity),
            }
            binding = binding_map.get(entry_id) or {}
            if binding.get("stop_price") is not None:
                detail["stop_price"] = float(binding["stop_price"])
            elif fallback_stop_price is not None:
                detail["stop_price"] = float(fallback_stop_price)
            if binding.get("ratio") is not None:
                detail["ratio"] = float(binding["ratio"])
            entry_details.append(detail)

        event = {
            "event_id": new_event_id(),
            "event_type": (
                "symbol_full_stoploss_hit"
                if is_symbol_full_stoploss
                else "entry_stoploss_hit"
            ),
            "kind": "stoploss",
            "symbol": _normalize_symbol(batch.get("symbol")),
            "batch_id": batch.get("batch_id"),
            "scope_type": scope_type,
            "strategy_name": strategy_name,
            "remark": batch.get("remark"),
            "trigger_price": float(batch.get("bid1") or batch.get("price") or 0.0),
            "entry_ids": [item["entry_id"] for item in entry_details],
            "entry_details": entry_details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        repository.insert_exit_trigger_event(event)
        return event

    def rearm_takeprofit(self, symbol, *, updated_by="system"):
        return self.takeprofit_service.rearm_all_levels(
            symbol,
            updated_by=updated_by,
            reason="manual",
        )

    def list_events(self, *, symbol=None, limit=50):
        repository = self.takeprofit_service.repository
        if not hasattr(repository, "list_exit_trigger_events"):
            return []
        return repository.list_exit_trigger_events(symbol=symbol, limit=limit)

    def get_batch_events(self, batch_id):
        repository = self.takeprofit_service.repository
        if not hasattr(repository, "list_exit_trigger_events"):
            return []
        return repository.list_exit_trigger_events(batch_id=batch_id, limit=200)

    def submit_takeprofit_batch(self, batch):
        return self._submit_batch(
            batch=batch,
            scope_type="takeprofit_batch",
            source="tpsl_takeprofit",
            strategy_name="Takeprofit",
        )

    def submit_stoploss_batch(self, batch):
        scope_type = str(batch.get("scope_type") or "").strip() or "stoploss_batch"
        strategy_name = str(batch.get("strategy_name") or "").strip() or (
            "FullPositionStoploss"
            if scope_type == "symbol_stoploss_batch"
            else "PerEntryStoplossBatch"
        )
        return self._submit_batch(
            batch=batch,
            scope_type=scope_type,
            source=(
                "tpsl_symbol_stoploss"
                if scope_type == "symbol_stoploss_batch"
                else "tpsl_stoploss"
            ),
            strategy_name=strategy_name,
        )

    def evaluate_takeprofit(
        self,
        *,
        symbol=None,
        code=None,
        ask1,
        bid1=None,
        last_price=None,
        tick_time=None,
        trace_id=None,
    ):
        base_symbol = _normalize_symbol(symbol or code)
        current_node = "profile_load"
        trace_id_value = None
        try:
            profile = self.takeprofit_service.get_profile_with_state(base_symbol)
        except ValueError:
            return None
        try:
            state = profile.get("state") or {}
            current_node = "trigger_eval"
            hit = choose_takeprofit_level(
                ask1=ask1,
                tiers=profile.get("tiers") or [],
                armed_levels=state.get("armed_levels") or {},
            )
            trigger_payload = {
                "kind": "takeprofit",
                "hit_level": (hit or {}).get("level"),
                "triggered": bool(hit),
            }
            if not hit:
                return None

            open_slices = list_open_entry_slices_compat(
                symbol=base_symbol,
                repository=self.order_repository,
            )
            # #549：TPSL 只卖 base；过滤一次，quantity 与 breakdown 共用。
            base_slices = [
                item
                for item in open_slices
                if position_type_of(item.get("position_type")) != "t"
            ]
            if not base_slices:
                self._emit_runtime(
                    "trigger_eval",
                    symbol=base_symbol,
                    trace_id=trace_id or new_trace_id(),
                    status="skipped",
                    reason_code="no_base_position",
                    payload={
                        **trigger_payload,
                        "quantity": 0,
                        "trigger_consumed": False,
                    },
                )
                return None
            total_base_quantity = sum(
                max(int(item.get("remaining_quantity") or 0), 0) for item in base_slices
            )
            if hasattr(self.position_reader, "get_position_volumes"):
                position_volumes = self.position_reader.get_position_volumes(
                    base_symbol
                )
            else:
                legacy_volume = self.position_reader.get_can_use_volume(base_symbol)
                position_volumes = {
                    "volume": legacy_volume,
                    "can_use_volume": legacy_volume,
                }
            quantity_result = resolve_takeprofit_sell_quantity(
                open_slices=base_slices,
                tier_price=hit["price"],
                level=int(hit["level"]),
                total_position_quantity=total_base_quantity,
                can_use_volume=position_volumes["can_use_volume"],
            )
            if int(quantity_result["quantity"] or 0) <= 0:
                self._emit_runtime(
                    "trigger_eval",
                    symbol=base_symbol,
                    trace_id=trace_id or new_trace_id(),
                    status="skipped",
                    reason_code="no_submittable_quantity",
                    payload={
                        **trigger_payload,
                        "quantity": 0,
                        "trigger_consumed": False,
                    },
                )
                return {
                    "status": "skipped",
                    "symbol": base_symbol,
                    "quantity": 0,
                    "skip_reason": "no_submittable_quantity",
                    "trigger_consumed": False,
                }

            sell_cap = position_volumes["can_use_volume"]
            sell_quantity = _resolve_sell_submission_quantity(
                requested_quantity=quantity_result["quantity"],
                can_use_volume=sell_cap,
            )
            if sell_quantity["status"] == "blocked":
                self._emit_runtime(
                    "trigger_eval",
                    symbol=base_symbol,
                    payload=trigger_payload,
                )
                return {
                    "status": "blocked",
                    "symbol": base_symbol,
                    "blocked_reason": sell_quantity["blocked_reason"],
                    "quantity": 0,
                }
            quantity_cap = int(sell_quantity["quantity_cap"])
            order_quantity = int(sell_quantity["quantity"])

            trace_id_value = str(trace_id or "").strip() or new_trace_id()
            self._emit_runtime(
                "trigger_eval",
                symbol=base_symbol,
                trace_id=trace_id_value,
                payload=trigger_payload,
            )
            capped = _cap_takeprofit_breakdown(
                quantity_result.get("profit_slices") or [],
                quantity_cap=order_quantity,
            )
            batch_id = f"takeprofit_batch_{uuid4().hex}"
            intent_id_value = new_intent_id()
            current_node = "batch_create"
            self._emit_runtime(
                "batch_create",
                symbol=base_symbol,
                trace_id=trace_id_value,
                intent_id=intent_id_value,
                payload={
                    "kind": "takeprofit",
                    "batch_id": batch_id,
                    "quantity": order_quantity,
                },
            )
            return {
                "batch_id": batch_id,
                "status": "ready",
                "symbol": base_symbol,
                "trace_id": trace_id_value,
                "intent_id": intent_id_value,
                "price": float(hit["price"]),
                "quantity": order_quantity,
                "level": int(hit["level"]),
                "tier_price": float(hit["price"]),
                "ask1": float(ask1 or 0.0),
                "bid1": float(bid1 or 0.0),
                "last_price": float(last_price or 0.0),
                "tick_time": int(tick_time or 0),
                "scope_type": "takeprofit_batch",
                "scope_ref_id": batch_id,
                "source": "takeprofit",
                "strategy_name": "Takeprofit",
                "remark": f"takeprofit:{base_symbol}:L{int(hit['level'])}",
                "entry_quantities": capped["entry_quantities"],
                "buy_lot_quantities": capped["buy_lot_quantities"],
                "slice_quantities": capped["slice_quantities"],
                "slice_details": capped["slice_details"],
                "allocation_policy": "takeprofit_ratio_v1",
            }
        except Exception as exc:
            self._emit_runtime(
                current_node,
                symbol=base_symbol,
                trace_id=trace_id_value or trace_id,
                status="error",
                reason_code="unexpected_exception",
                payload=build_exception_payload(exc),
            )
            mark_exception_emitted(exc)
            raise

    def evaluate_stoploss(
        self,
        *,
        symbol=None,
        code=None,
        bid1,
        ask1=None,
        last_price=None,
        tick_time=None,
        trace_id=None,
    ):
        base_symbol = _normalize_symbol(symbol or code)
        current_node = "trigger_eval"
        trace_id_value = None
        try:
            full_stop_price = _safe_float_or_none(
                self.symbol_stoploss_price_loader(base_symbol)
            )
            if full_stop_price is not None and float(bid1 or 0.0) <= float(
                full_stop_price
            ):
                can_use_volume = self.position_reader.get_can_use_volume(base_symbol)
                open_slices = list_open_entry_slices_compat(
                    symbol=base_symbol,
                    repository=self.order_repository,
                )
                batch = build_stoploss_batch(
                    repository=self.order_repository,
                    symbol=base_symbol,
                    bid1=bid1,
                    entry_ids=_collect_entry_ids(open_slices),
                    stop_price=full_stop_price,
                    can_use_volume=can_use_volume,
                    scope_type="symbol_stoploss_batch",
                    strategy_name="FullPositionStoploss",
                )
                trigger_payload = {
                    "kind": "stoploss",
                    "stoploss_mode": "symbol_full",
                    "scope_type": "symbol_stoploss_batch",
                    "strategy_name": "FullPositionStoploss",
                    "full_stop_price": float(full_stop_price),
                    "triggered_bindings": 0,
                }
                if batch.get("status") == "blocked":
                    batch["full_stop_price"] = float(full_stop_price)
                    batch["triggered_bindings"] = []
                    batch.pop("trace_id", None)
                    batch.pop("intent_id", None)
                    self._emit_runtime(
                        "trigger_eval",
                        symbol=base_symbol,
                        payload=trigger_payload,
                    )
                    return batch

                trace_id_value = str(trace_id or "").strip() or new_trace_id()
                self._emit_runtime(
                    "trigger_eval",
                    symbol=base_symbol,
                    trace_id=trace_id_value,
                    payload=trigger_payload,
                )
                intent_id_value = new_intent_id()
                batch["ask1"] = float(ask1 or 0.0)
                batch["last_price"] = float(last_price or 0.0)
                batch["tick_time"] = int(tick_time or 0)
                batch["trace_id"] = trace_id_value
                batch["intent_id"] = intent_id_value
                batch["full_stop_price"] = float(full_stop_price)
                batch["triggered_bindings"] = []
                current_node = "batch_create"
                self._emit_runtime(
                    "batch_create",
                    symbol=base_symbol,
                    trace_id=trace_id_value,
                    intent_id=intent_id_value,
                    payload={
                        "kind": "stoploss",
                        "stoploss_mode": "symbol_full",
                        "scope_type": "symbol_stoploss_batch",
                        "strategy_name": "FullPositionStoploss",
                        "batch_id": batch.get("batch_id"),
                        "quantity": batch.get("quantity"),
                    },
                )
                return batch

            triggered_bindings = []
            for binding in list_entry_stoploss_bindings_compat(
                symbol=base_symbol,
                enabled=True,
                repository=self.order_repository,
            ):
                stop_price = binding.get("stop_price")
                if stop_price is None:
                    continue
                if float(bid1 or 0.0) <= float(stop_price):
                    triggered_bindings.append(binding)
            trigger_payload = {
                "kind": "stoploss",
                "stoploss_mode": "entry",
                "scope_type": "stoploss_batch",
                "strategy_name": "PerEntryStoplossBatch",
                "triggered_bindings": len(triggered_bindings),
            }
            if not triggered_bindings:
                return None

            can_use_volume = self.position_reader.get_can_use_volume(base_symbol)
            batch = build_stoploss_batch(
                repository=self.order_repository,
                symbol=base_symbol,
                bid1=bid1,
                triggered_bindings=triggered_bindings,
                can_use_volume=can_use_volume,
            )
            if batch.get("status") == "blocked":
                batch.pop("trace_id", None)
                batch.pop("intent_id", None)
                self._emit_runtime(
                    "trigger_eval",
                    symbol=base_symbol,
                    payload=trigger_payload,
                )
                return batch

            trace_id_value = str(trace_id or "").strip() or new_trace_id()
            self._emit_runtime(
                "trigger_eval",
                symbol=base_symbol,
                trace_id=trace_id_value,
                payload=trigger_payload,
            )
            intent_id_value = new_intent_id()
            batch["ask1"] = float(ask1 or 0.0)
            batch["last_price"] = float(last_price or 0.0)
            batch["tick_time"] = int(tick_time or 0)
            batch["trace_id"] = trace_id_value
            batch["intent_id"] = intent_id_value
            batch["triggered_bindings"] = list(triggered_bindings)
            current_node = "batch_create"
            self._emit_runtime(
                "batch_create",
                symbol=base_symbol,
                trace_id=trace_id_value,
                intent_id=intent_id_value,
                payload={
                    "kind": "stoploss",
                    "stoploss_mode": "entry",
                    "scope_type": "stoploss_batch",
                    "strategy_name": "PerEntryStoplossBatch",
                    "batch_id": batch.get("batch_id"),
                    "quantity": batch.get("quantity"),
                },
            )
            return batch
        except Exception as exc:
            self._emit_runtime(
                current_node,
                symbol=base_symbol,
                trace_id=trace_id_value or trace_id,
                status="error",
                reason_code="unexpected_exception",
                payload=build_exception_payload(exc),
            )
            mark_exception_emitted(exc)
            raise

    def on_new_buy_trade(self, *, symbol, buy_price, position_type="base"):
        """#549 rearm 门控：仅 base 买入事件（首开 + buy 线触发 + 手动加仓）
        全开止盈档；T 买入不触发状态机（Guardian 做T与固定触发机制解耦）。
        """

        if position_type_of(position_type) != "base":
            return None
        try:
            profile = self.takeprofit_service.get_profile_with_state(symbol)
        except ValueError:
            return None
        prices = [
            float(item["price"])
            for item in profile.get("tiers") or []
            if item.get("price") is not None
        ]
        if not prices:
            return None
        return self.takeprofit_service.rearm_all_levels(
            symbol,
            updated_by="buy_trade",
            reason="base_buy_rearm",
        )

    def evaluate_base_buyline(
        self,
        *,
        symbol=None,
        code=None,
        bid1=None,
        last_price=None,
        tick_time=None,
        trace_id=None,
    ):
        """固定价格触发买入线评估（#549，挂在 TPSL tick worker）。

        R_N = cap_N − max(D+C, MV) − 在途（占用取大）；MV 缺失 fail-closed；
        ``B < min_buy_amount`` 或不足一手不买（不消耗冷却）。
        """

        base_symbol = _normalize_symbol(symbol or code)
        try:
            source_price = float(bid1 if bid1 not in (None, "") else last_price or 0.0)
        except (TypeError, ValueError):
            source_price = 0.0
        if source_price <= 0:
            return None
        decision = _get_guardian_buy_grid_service().build_base_line_decision(
            base_symbol,
            source_price,
        )
        quantity = int(decision.get("quantity") or 0)
        if quantity <= 0:
            return {
                "status": "skipped",
                "symbol": base_symbol,
                "quantity": 0,
                "skip_reason": decision.get("skip_reason") or "no_quantity",
                "stage": decision.get("stage"),
                "grid_level": decision.get("grid_level"),
                "price": source_price,
                "tick_time": int(tick_time or 0),
                "trigger_consumed": False,
            }
        return {
            "status": "ready",
            "symbol": base_symbol,
            "quantity": quantity,
            "price": source_price,
            "grid_level": decision.get("grid_level"),
            "stage": decision.get("stage"),
            "effective_stage_cap": decision.get("effective_stage_cap"),
            "current_market_value": decision.get("current_market_value"),
            "remaining_amount": decision.get("remaining_amount"),
            "ledger_occupancy": decision.get("ledger_occupancy"),
            "pending_buy_amount": decision.get("pending_buy_amount"),
            "tick_time": int(tick_time or 0),
            "decision": decision,
        }

    def submit_base_buy_batch(self, decision, *, trace_id=None):
        """提交买入线补仓单（base 账本，buy_ledger=base_line）。

        触发即关（阶梯事件）+ 全开止盈档；独立冷却 ``base_buy:<code>``；
        提交前在途复核（超 cap 放弃）；不取消 T 侧在途买单。
        """

        symbol = str(decision.get("symbol") or "").strip()
        if not symbol:
            return None
        quantity = int(decision.get("quantity") or 0)
        price = float(decision.get("price") or 0.0)
        grid_level = str(decision.get("grid_level") or "").upper()
        level_index = _BUY_LEVEL_INDEX.get(grid_level)
        if quantity <= 0 or price <= 0 or level_index is None:
            return {
                "status": "blocked",
                "symbol": symbol,
                "blocked_reason": "invalid_decision",
                "quantity": 0,
            }
        cooldown_key = f"base_buy:{symbol}"
        if not self.lock_client.acquire(
            cooldown_key,
            ttl_seconds=_BASE_BUY_COOLDOWN_SECONDS,
        ):
            return {
                "status": "cooldown",
                "symbol": symbol,
                "blocked_reason": "base_buy_cooldown",
                "quantity": 0,
            }
        # 提交侧在途复核：超 cap 放弃（不采用共用冷却键，与独立冷却承诺一致）。
        try:
            from freshquant.strategy.guardian_buy_grid import (
                get_guardian_buy_grid_service,
            )

            capacity = get_guardian_buy_grid_service()._resolve_remaining_capacity(
                symbol,
                price,
                cap=float(decision.get("effective_stage_cap") or 0.0),
            )
        except Exception:
            capacity = None
        if capacity is not None and capacity["remaining"] <= 0:
            return {
                "status": "blocked",
                "symbol": symbol,
                "blocked_reason": "in_flight_capacity_exhausted",
                "quantity": 0,
            }
        intent_id = new_intent_id()
        trace_id_value = str(trace_id or "").strip() or new_trace_id()
        ladder = _get_ladder_state()
        triggered = ladder.on_buy_line_trigger(
            code=symbol,
            level_index=level_index,
            event_key=intent_id,
        )
        if not triggered:
            # 已被其他进程/事件处理：本轮放弃（下一 tick 重试）。
            return {
                "status": "blocked",
                "symbol": symbol,
                "blocked_reason": "ladder_conflict",
                "quantity": 0,
            }
        strategy_context = {
            "buy_ledger": "base_line",
            "guardian_buy_grid": {
                "path": "base_line",
                "grid_level": grid_level,
                "source_price": price,
                "buy_prices_snapshot": decision.get("buy_prices_snapshot"),
                "effective_stage_cap": decision.get("effective_stage_cap"),
                "current_market_value": decision.get("current_market_value"),
                "remaining_amount": decision.get("remaining_amount"),
                "ledger_occupancy": decision.get("ledger_occupancy"),
                "pending_buy_amount": decision.get("pending_buy_amount"),
                # 不带 hit_levels：_mark_guardian_buy_grid_after_accept 天然跳过，
                # 不污染旧 buy_active 审计态。
            },
        }
        try:
            from freshquant.order_management.submit.guardian import (
                submit_guardian_order,
            )

            submit_result = submit_guardian_order(
                "buy",
                symbol,
                price,
                quantity,
                remark=f"base_buyline:{symbol}:{grid_level}",
                strategy_context=strategy_context,
                trace_id=trace_id_value,
                intent_id=intent_id,
            )
        except Exception as exc:
            # 本地提交失败：补偿重开该买入线 + 冷却，避免每 tick 重试风暴。
            ladder.on_buy_zero_fill_terminal(
                code=symbol,
                level_index=level_index,
                event_key=f"{intent_id}:submit_failed",
            )
            self._emit_runtime(
                "submit_intent",
                symbol=symbol,
                trace_id=trace_id_value,
                intent_id=intent_id,
                status="error",
                reason_code="unexpected_exception",
                payload=build_exception_payload(
                    exc,
                    extra={"grid_level": grid_level, "quantity": quantity},
                ),
            )
            raise
        self._emit_runtime(
            "submit_intent",
            symbol=symbol,
            trace_id=trace_id_value,
            intent_id=intent_id,
            request_id=submit_result.get("request_id"),
            internal_order_id=submit_result.get("internal_order_id"),
            payload={
                "kind": "base_buyline",
                "grid_level": grid_level,
                "quantity": quantity,
            },
        )
        return submit_result

    def _submit_batch(self, *, batch, scope_type, source, strategy_name):
        if not batch or batch.get("status") == "blocked":
            return batch

        symbol = str(batch["symbol"])
        batch_id = batch["batch_id"]
        lock_key = f"tpsl:cooldown:{symbol}:{scope_type}"
        if self.cooldown_seconds > 0 and not self.lock_client.acquire(
            lock_key,
            ttl_seconds=self.cooldown_seconds,
        ):
            return {
                **batch,
                "status": "cooldown",
                "blocked_reason": "cooldown",
            }

        try:
            submit_result = self._get_order_submit_service().submit_order(
                {
                    "action": "sell",
                    "symbol": symbol,
                    "price": float(batch["price"]),
                    "quantity": int(batch["quantity"]),
                    "trace_id": batch.get("trace_id"),
                    "intent_id": batch.get("intent_id"),
                    "scope_type": scope_type,
                    "scope_ref_id": batch_id,
                    "source": source,
                    "strategy_name": batch.get("strategy_name") or strategy_name,
                    "remark": batch.get("remark") or f"{scope_type}:{batch_id}",
                    "price_mode": "auto",
                    "strategy_context": (
                        {
                            "guardian_sell_sources": {
                                "allocation_policy": batch.get("allocation_policy"),
                                "level": batch.get("level"),
                                "tier_price": batch.get("tier_price"),
                                "entries": _build_entry_details(
                                    batch.get("entry_quantities") or {}
                                ),
                            }
                        }
                        if scope_type == "takeprofit_batch"
                        else None
                    ),
                }
            )
            self._emit_runtime(
                "submit_intent",
                symbol=symbol,
                trace_id=batch.get("trace_id"),
                intent_id=batch.get("intent_id"),
                request_id=submit_result.get("request_id"),
                internal_order_id=submit_result.get("internal_order_id"),
                payload={"scope_type": scope_type, "batch_id": batch_id},
            )
            if scope_type == "takeprofit_batch" and batch.get("level") is not None:
                self.mark_takeprofit_triggered(
                    symbol=symbol,
                    level=int(batch["level"]),
                    batch_id=batch_id,
                    updated_by="tpsl_submit",
                    trigger_price=batch.get("tier_price") or batch.get("price"),
                    entry_details=_build_entry_details(
                        batch.get("entry_quantities") or {}
                    ),
                    buy_lot_details=_build_buy_lot_details(
                        batch.get("buy_lot_quantities") or {}
                    ),
                )
            if scope_type in {"stoploss_batch", "symbol_stoploss_batch"}:
                self.mark_stoploss_triggered(batch=batch)
            return submit_result
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_runtime(
                    "submit_intent",
                    symbol=symbol,
                    trace_id=batch.get("trace_id"),
                    intent_id=batch.get("intent_id"),
                    status="error",
                    reason_code="unexpected_exception",
                    payload=build_exception_payload(exc, extra={"batch_id": batch_id}),
                )
                mark_exception_emitted(exc)
            raise

    def _get_order_submit_service(self):
        if self.order_submit_service is None:
            self.order_submit_service = OrderSubmitService()
        return self.order_submit_service

    def _emit_runtime(
        self,
        node,
        *,
        symbol,
        trace_id=None,
        intent_id=None,
        request_id=None,
        internal_order_id=None,
        status="info",
        reason_code="",
        payload=None,
    ):
        event = {
            "component": "tpsl_worker",
            "node": node,
            "trace_id": trace_id,
            "intent_id": intent_id,
            "request_id": request_id,
            "internal_order_id": internal_order_id,
            "symbol": symbol,
            "status": status,
            "reason_code": reason_code,
            "payload": dict(payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


class _CooldownLockClient:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self._memory = {}

    def acquire(self, key, *, ttl_seconds):
        ttl = max(int(ttl_seconds or 0), 0)
        if ttl <= 0:
            return True

        if self.redis_client is not None:
            try:
                return bool(self.redis_client.set(key, "1", ex=ttl, nx=True))
            except Exception as exc:
                raise RuntimeError("tpsl cooldown redis lock failed") from exc

        now = time.time()
        expired_at = float(self._memory.get(key) or 0.0)
        if expired_at > now:
            return False
        self._memory[key] = now + ttl
        return True


def _normalize_symbol(symbol):
    return normalize_to_base_code(str(symbol or ""))


def _collect_entry_ids(rows):
    entry_ids = []
    seen = set()
    for item in rows or []:
        entry_id = str(item.get("entry_id") or "").strip()
        if not entry_id or entry_id in seen:
            continue
        seen.add(entry_id)
        entry_ids.append(entry_id)
    return entry_ids


def _safe_float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_symbol_stoploss_price_loader(symbol):
    normalized_symbol = _normalize_symbol(symbol)
    try:
        document = DBfreshquant["must_pool"].find_one({"code": normalized_symbol}) or {}
    except Exception:
        return None
    return _safe_float_or_none(document.get("stop_loss_price"))


def _cap_takeprofit_breakdown(profit_slices, *, quantity_cap):
    remaining = max(int(quantity_cap or 0), 0)
    slice_quantities = {}
    entry_quantities = {}
    buy_lot_quantities = {}
    slice_details = []

    for slice_document in profit_slices or []:
        if remaining <= 0:
            break
        allocatable = min(int(slice_document.get("remaining_quantity") or 0), remaining)
        if allocatable <= 0:
            continue
        slice_id = slice_document.get("entry_slice_id") or slice_document.get(
            "lot_slice_id"
        )
        entry_id = slice_document.get("entry_id") or slice_document.get("buy_lot_id")
        if not slice_id or not entry_id:
            continue
        slice_quantities[slice_id] = allocatable
        entry_quantities[entry_id] = entry_quantities.get(entry_id, 0) + allocatable
        buy_lot_id = slice_document.get("buy_lot_id")
        if buy_lot_id:
            buy_lot_quantities[buy_lot_id] = (
                buy_lot_quantities.get(buy_lot_id, 0) + allocatable
            )
        slice_details.append(
            {
                "entry_slice_id": slice_id,
                "entry_id": entry_id,
                "allocated_quantity": allocatable,
                "guardian_price": float(slice_document.get("guardian_price") or 0.0),
            }
        )
        if buy_lot_id:
            slice_details[-1]["buy_lot_id"] = buy_lot_id
        remaining -= allocatable

    return {
        "slice_quantities": slice_quantities,
        "entry_quantities": entry_quantities,
        "buy_lot_quantities": buy_lot_quantities,
        "slice_details": slice_details,
    }


def _build_entry_details(entry_quantities):
    details = []
    for entry_id, quantity in dict(entry_quantities or {}).items():
        details.append(
            {
                "entry_id": entry_id,
                "quantity": int(quantity),
            }
        )
    return details


def _build_buy_lot_details(buy_lot_quantities):
    details = []
    for buy_lot_id, quantity in dict(buy_lot_quantities or {}).items():
        details.append(
            {
                "buy_lot_id": buy_lot_id,
                "quantity": int(quantity),
            }
        )
    return details


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("tpsl_worker")
    return _runtime_logger


def _get_guardian_buy_grid_service():
    from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service

    return get_guardian_buy_grid_service()


def _get_ladder_state():
    from freshquant.strategy.guardian_ladder import get_guardian_ladder_state

    return get_guardian_ladder_state()
