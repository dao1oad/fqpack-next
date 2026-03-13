# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4

from freshquant.db import DBfreshquant
from freshquant.order_management.ids import new_event_id
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.runtime_observability.ids import new_intent_id, new_trace_id
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.tpsl.stoploss_batch import build_stoploss_batch
from freshquant.tpsl.takeprofit_quantity import (
    choose_takeprofit_level,
    resolve_takeprofit_sell_quantity,
)
from freshquant.tpsl.takeprofit_service import TakeprofitService
from freshquant.util.code import normalize_to_base_code

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
        lock_client=None,
        cooldown_seconds=3,
        runtime_logger=None,
    ):
        self.takeprofit_service = takeprofit_service or TakeprofitService()
        self.order_submit_service = order_submit_service
        self.order_repository = order_repository or OrderManagementRepository()
        self.position_reader = position_reader or _PositionReader(DBfreshquant)
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
        buy_lot_details=None,
    ):
        return self.takeprofit_service.mark_level_triggered(
            symbol,
            level=level,
            batch_id=batch_id,
            updated_by=updated_by,
            trigger_price=trigger_price,
            buy_lot_details=buy_lot_details,
        )

    def mark_stoploss_triggered(self, *, batch):
        repository = getattr(self.takeprofit_service, "repository", None)
        if repository is None or not hasattr(repository, "insert_exit_trigger_event"):
            return None

        buy_lot_quantities = dict(batch.get("buy_lot_quantities") or {})
        binding_map = {
            item.get("buy_lot_id"): item
            for item in (batch.get("triggered_bindings") or [])
            if item.get("buy_lot_id")
        }
        buy_lot_details = []
        for buy_lot_id, quantity in buy_lot_quantities.items():
            detail = {
                "buy_lot_id": buy_lot_id,
                "quantity": int(quantity),
            }
            binding = binding_map.get(buy_lot_id) or {}
            if binding.get("stop_price") is not None:
                detail["stop_price"] = float(binding["stop_price"])
            if binding.get("ratio") is not None:
                detail["ratio"] = float(binding["ratio"])
            buy_lot_details.append(detail)

        event = {
            "event_id": new_event_id(),
            "event_type": "stoploss_hit",
            "kind": "stoploss",
            "symbol": _normalize_symbol(batch.get("symbol")),
            "batch_id": batch.get("batch_id"),
            "trigger_price": float(batch.get("bid1") or batch.get("price") or 0.0),
            "buy_lot_ids": [item["buy_lot_id"] for item in buy_lot_details],
            "buy_lot_details": buy_lot_details,
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
        return self._submit_batch(
            batch=batch,
            scope_type="stoploss_batch",
            source="tpsl_stoploss",
            strategy_name="PerLotStoplossBatch",
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
        try:
            profile = self.takeprofit_service.get_profile_with_state(base_symbol)
        except ValueError:
            return None
        self._emit_runtime(
            "profile_load",
            symbol=base_symbol,
            trace_id=trace_id,
            payload={"code": code},
        )

        state = profile.get("state") or {}
        hit = choose_takeprofit_level(
            ask1=ask1,
            tiers=profile.get("tiers") or [],
            armed_levels=state.get("armed_levels") or {},
        )
        self._emit_runtime(
            "trigger_eval",
            symbol=base_symbol,
            trace_id=trace_id,
            payload={"kind": "takeprofit", "hit_level": (hit or {}).get("level")},
        )
        if hit is None:
            return None

        open_slices = self.order_repository.list_open_slices(base_symbol)
        quantity_result = resolve_takeprofit_sell_quantity(
            open_slices=open_slices,
            tier_price=hit["price"],
        )
        if int(quantity_result["quantity"] or 0) <= 0:
            return None

        sell_cap = self.position_reader.get_can_use_volume(base_symbol)
        if int(sell_cap or 0) <= 0:
            return {
                "status": "blocked",
                "symbol": base_symbol,
                "blocked_reason": "can_use_volume",
                "quantity": 0,
            }
        quantity_cap = min(int(quantity_result["quantity"]), int(sell_cap))
        order_quantity = _floor_to_board_lot(quantity_cap)
        if order_quantity < 100:
            return {
                "status": "blocked",
                "symbol": base_symbol,
                "blocked_reason": "board_lot",
                "quantity": 0,
            }

        capped = _cap_takeprofit_breakdown(
            quantity_result.get("profit_slices") or [],
            quantity_cap=order_quantity,
        )
        batch_id = f"takeprofit_batch_{uuid4().hex}"
        trace_id_value = str(trace_id or "").strip() or new_trace_id()
        intent_id_value = new_intent_id()
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
            "buy_lot_quantities": capped["buy_lot_quantities"],
            "slice_quantities": capped["slice_quantities"],
            "slice_details": capped["slice_details"],
        }

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
        triggered_bindings = []
        for binding in self.order_repository.list_stoploss_bindings(
            symbol=base_symbol,
            enabled=True,
        ):
            stop_price = binding.get("stop_price")
            if stop_price is None:
                continue
            if float(bid1 or 0.0) <= float(stop_price):
                triggered_bindings.append(binding)
        self._emit_runtime(
            "trigger_eval",
            symbol=base_symbol,
            trace_id=trace_id,
            payload={
                "kind": "stoploss",
                "triggered_bindings": len(triggered_bindings),
            },
        )
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
        if batch.get("status") != "blocked":
            trace_id_value = str(trace_id or "").strip() or new_trace_id()
            intent_id_value = new_intent_id()
            batch["ask1"] = float(ask1 or 0.0)
            batch["last_price"] = float(last_price or 0.0)
            batch["tick_time"] = int(tick_time or 0)
            batch["trace_id"] = trace_id_value
            batch["intent_id"] = intent_id_value
            batch["triggered_bindings"] = list(triggered_bindings)
            self._emit_runtime(
                "batch_create",
                symbol=base_symbol,
                trace_id=trace_id_value,
                intent_id=intent_id_value,
                payload={
                    "kind": "stoploss",
                    "batch_id": batch.get("batch_id"),
                    "quantity": batch.get("quantity"),
                },
            )
        return batch

    def on_new_buy_trade(self, *, symbol, buy_price):
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

        if float(buy_price) < min(prices):
            return self.takeprofit_service.rearm_all_levels(
                symbol,
                updated_by="buy_trade",
                reason="new_buy_below_lowest_tier",
            )
        return None

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
                buy_lot_details=_build_buy_lot_details(
                    batch.get("buy_lot_quantities") or {}
                ),
            )
        if scope_type == "stoploss_batch":
            self.mark_stoploss_triggered(batch=batch)
        return submit_result

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
            except Exception:
                pass

        now = time.time()
        expired_at = float(self._memory.get(key) or 0.0)
        if expired_at > now:
            return False
        self._memory[key] = now + ttl
        return True


class _PositionReader:
    def __init__(self, database):
        self.database = database

    def get_can_use_volume(self, symbol):
        base_symbol = _normalize_symbol(symbol)
        for doc in self.database["xt_positions"].find(
            {},
            {
                "stock_code": 1,
                "code": 1,
                "symbol": 1,
                "can_use_volume": 1,
                "volume": 1,
            },
        ):
            raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
            if _normalize_symbol(raw) != base_symbol:
                continue
            try:
                return max(
                    int(doc.get("can_use_volume") or 0),
                    int(doc.get("volume") or 0),
                )
            except Exception:
                return 0
        return 0


def _normalize_symbol(symbol):
    return normalize_to_base_code(str(symbol or ""))


def _floor_to_board_lot(quantity):
    value = max(int(quantity or 0), 0)
    return value - (value % 100)


def _cap_takeprofit_breakdown(profit_slices, *, quantity_cap):
    remaining = max(int(quantity_cap or 0), 0)
    slice_quantities = {}
    buy_lot_quantities = {}
    slice_details = []

    for slice_document in profit_slices or []:
        if remaining <= 0:
            break
        allocatable = min(int(slice_document.get("remaining_quantity") or 0), remaining)
        if allocatable <= 0:
            continue
        slice_id = slice_document["lot_slice_id"]
        buy_lot_id = slice_document["buy_lot_id"]
        slice_quantities[slice_id] = allocatable
        buy_lot_quantities[buy_lot_id] = (
            buy_lot_quantities.get(buy_lot_id, 0) + allocatable
        )
        slice_details.append(
            {
                "lot_slice_id": slice_id,
                "buy_lot_id": buy_lot_id,
                "allocated_quantity": allocatable,
                "guardian_price": float(slice_document.get("guardian_price") or 0.0),
            }
        )
        remaining -= allocatable

    return {
        "slice_quantities": slice_quantities,
        "buy_lot_quantities": buy_lot_quantities,
        "slice_details": slice_details,
    }


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
