# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.ids import (
    new_execution_fill_id,
    new_event_id,
    new_internal_order_id,
    new_request_id,
    new_trade_fact_id,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.state_machine import OrderStateMachine


class OrderTrackingService:
    def __init__(self, repository=None, state_machine=None):
        self.repository = repository or OrderManagementRepository()
        self.state_machine = state_machine or OrderStateMachine()

    def submit_order(self, payload):
        request_id = payload.get("request_id") or new_request_id()
        internal_order_id = payload.get("internal_order_id") or new_internal_order_id()
        now = _utc_now_iso()

        request_document = {
            "request_id": request_id,
            "action": payload["action"],
            "source": payload.get("source", "unknown"),
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "account_type": payload.get("account_type"),
            "symbol": payload.get("symbol"),
            "price": payload.get("price"),
            "quantity": payload.get("quantity"),
            "credit_trade_mode": payload.get("credit_trade_mode"),
            "price_mode": payload.get("price_mode"),
            "strategy_name": payload.get("strategy_name"),
            "remark": payload.get("remark"),
            "strategy_context": payload.get("strategy_context"),
            "scope_type": payload.get("scope_type"),
            "scope_ref_id": payload.get("scope_ref_id"),
            "req_id": payload.get("req_id") or request_id,
            "state": "ACCEPTED",
            "created_at": now,
        }
        order_document = {
            "internal_order_id": internal_order_id,
            "request_id": request_id,
            "broker_order_id": payload.get("broker_order_id"),
            "broker_order_type": payload.get("broker_order_type"),
            "broker_price_type": payload.get("broker_price_type"),
            "account_type": payload.get("account_type"),
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "symbol": payload.get("symbol"),
            "side": payload["action"],
            "credit_trade_mode_requested": payload.get("credit_trade_mode"),
            "credit_trade_mode_resolved": payload.get("credit_trade_mode_resolved"),
            "price_mode_requested": payload.get("price_mode"),
            "price_mode_resolved": payload.get("price_mode_resolved"),
            "state": "ACCEPTED",
            "source_type": payload.get("source", "unknown"),
            "submitted_at": None,
            "filled_quantity": 0,
            "avg_filled_price": None,
            "updated_at": now,
        }
        event_document = {
            "event_id": new_event_id(),
            "request_id": request_id,
            "internal_order_id": internal_order_id,
            "event_type": "accepted",
            "state": "ACCEPTED",
            "created_at": now,
        }

        self.repository.insert_order_request(request_document)
        self.repository.insert_order(order_document)
        self.repository.upsert_broker_order(
            {
                "broker_order_key": internal_order_id,
                "internal_order_id": internal_order_id,
                "request_id": request_id,
                "broker_order_id": payload.get("broker_order_id"),
                "broker_order_type": payload.get("broker_order_type"),
                "broker_price_type": payload.get("broker_price_type"),
                "account_type": payload.get("account_type"),
                "trace_id": payload.get("trace_id"),
                "intent_id": payload.get("intent_id"),
                "symbol": payload.get("symbol"),
                "side": payload["action"],
                "credit_trade_mode_requested": payload.get("credit_trade_mode"),
                "credit_trade_mode_resolved": payload.get("credit_trade_mode_resolved"),
                "price_mode_requested": payload.get("price_mode"),
                "price_mode_resolved": payload.get("price_mode_resolved"),
                "state": "ACCEPTED",
                "source_type": payload.get("source", "unknown"),
                "submitted_at": None,
                "requested_quantity": payload.get("quantity"),
                "filled_quantity": 0,
                "avg_filled_price": None,
                "fill_count": 0,
                "first_fill_time": None,
                "last_fill_time": None,
                "updated_at": now,
            },
            unique_keys=["broker_order_key"],
        )
        self.repository.insert_order_event(event_document)
        return request_id

    def cancel_order(self, payload):
        now = _utc_now_iso()
        request_id = new_request_id()
        internal_order_id = payload["internal_order_id"]
        current_order = self.repository.find_order(internal_order_id)
        current_state = current_order["state"]
        next_state = self.state_machine.transition(current_state, "CANCEL_REQUESTED")

        request_document = {
            "request_id": request_id,
            "action": "cancel",
            "source": payload.get("source", "unknown"),
            "symbol": current_order.get("symbol"),
            "price": None,
            "quantity": None,
            "strategy_name": payload.get("strategy_name"),
            "remark": payload.get("remark"),
            "strategy_context": payload.get("strategy_context"),
            "scope_type": "internal_order",
            "scope_ref_id": internal_order_id,
            "req_id": payload.get("request_id") or request_id,
            "state": next_state,
            "created_at": now,
        }
        event_document = {
            "event_id": new_event_id(),
            "request_id": request_id,
            "internal_order_id": internal_order_id,
            "event_type": "cancel_requested",
            "state": next_state,
            "created_at": now,
        }

        self.repository.insert_order_request(request_document)
        self.repository.update_order(
            internal_order_id,
            {"state": next_state, "updated_at": now},
        )
        self._sync_broker_order_report(
            internal_order_id,
            {
                "state": next_state,
            },
        )
        self.repository.insert_order_event(event_document)
        return request_id

    def mark_order_queued(self, internal_order_id):
        order = self.repository.find_order(internal_order_id)
        current_state = order["state"]
        next_state = self.state_machine.transition(current_state, "QUEUED")
        now = _utc_now_iso()
        self.repository.update_order(
            internal_order_id,
            {"state": next_state, "updated_at": now},
        )
        self._sync_broker_order_report(
            internal_order_id,
            {
                "state": next_state,
            },
        )
        self.repository.insert_order_event(
            {
                "event_id": new_event_id(),
                "request_id": order["request_id"],
                "internal_order_id": internal_order_id,
                "event_type": "queued",
                "state": next_state,
                "created_at": now,
            }
        )
        return self.repository.find_order(internal_order_id)

    def ingest_order_report(self, report):
        return self.ingest_order_report_with_meta(report)["order"]

    def ingest_order_report_with_meta(self, report):
        internal_order_id = report["internal_order_id"]
        current_order = self.repository.find_order(internal_order_id)
        current_state = current_order["state"]
        updates = {}
        if report.get("broker_order_id") and not current_order.get("broker_order_id"):
            updates["broker_order_id"] = report.get("broker_order_id")
        if report.get("submitted_at") and not current_order.get("submitted_at"):
            updates["submitted_at"] = report.get("submitted_at")
        if current_state == report["state"]:
            if updates:
                updates["updated_at"] = _utc_now_iso()
                updated_order = self.repository.update_order(internal_order_id, updates)
                self._sync_broker_order_report(
                    internal_order_id,
                    {
                        "broker_order_id": report.get("broker_order_id"),
                        "submitted_at": report.get("submitted_at"),
                        "state": current_state,
                    },
                )
                return {
                    "order": updated_order,
                    "changed": True,
                    "absorbed": False,
                }
            return {"order": current_order, "changed": False, "absorbed": False}
        if _should_absorb_terminal_replay(current_state, report["state"]):
            if updates:
                updates["updated_at"] = _utc_now_iso()
                current_order = self.repository.update_order(internal_order_id, updates)
                self._sync_broker_order_report(
                    internal_order_id,
                    {
                        "broker_order_id": report.get("broker_order_id"),
                        "submitted_at": report.get("submitted_at"),
                        "state": current_order.get("state"),
                    },
                )
            return {"order": current_order, "changed": False, "absorbed": True}
        next_state = self.state_machine.transition(current_state, report["state"])
        now = _utc_now_iso()

        updated_order = self.repository.update_order(
            internal_order_id,
            {
                "state": next_state,
                "broker_order_id": report.get("broker_order_id"),
                "submitted_at": report.get("submitted_at"),
                "updated_at": now,
            },
        )
        self.repository.insert_order_event(
            {
                "event_id": new_event_id(),
                "request_id": current_order["request_id"],
                "internal_order_id": internal_order_id,
                "event_type": report.get("event_type", "order_reported"),
                "state": next_state,
                "created_at": now,
            }
        )
        self._sync_broker_order_report(
            internal_order_id,
            {
                "broker_order_id": report.get("broker_order_id"),
                "submitted_at": report.get("submitted_at"),
                "state": next_state,
            },
        )
        return {"order": updated_order, "changed": True, "absorbed": False}

    def ingest_trade_report(self, report):
        return self.ingest_trade_report_with_meta(report)["trade_fact"]

    def ingest_trade_report_with_meta(self, report):
        current_order = self.repository.find_order(report["internal_order_id"])
        broker_order_key = _resolve_broker_order_key(report, current_order=current_order)
        execution_fill = {
            "execution_fill_id": report.get("execution_fill_id")
            or new_execution_fill_id(),
            "broker_order_key": broker_order_key,
            "internal_order_id": report["internal_order_id"],
            "request_id": current_order.get("request_id") if current_order else None,
            "broker_order_id": report.get("broker_order_id")
            or (current_order.get("broker_order_id") if current_order else None),
            "broker_trade_id": report["broker_trade_id"],
            "symbol": report["symbol"],
            "side": report["side"],
            "quantity": report["quantity"],
            "price": report["price"],
            "trade_time": report["trade_time"],
            "date": report.get("date"),
            "time": report.get("time"),
            "source": report.get("source", "unknown"),
            "provisional": report.get("provisional", False),
        }
        saved_execution_fill, created_execution_fill = self.repository.upsert_execution_fill(
            execution_fill,
            unique_keys=["broker_trade_id"],
        )
        trade_fact = {
            "trade_fact_id": report.get("trade_fact_id") or new_trade_fact_id(),
            "internal_order_id": report["internal_order_id"],
            "broker_trade_id": report["broker_trade_id"],
            "symbol": report["symbol"],
            "side": report["side"],
            "quantity": report["quantity"],
            "price": report["price"],
            "trade_time": report["trade_time"],
            "date": report.get("date"),
            "time": report.get("time"),
            "source": report.get("source", "unknown"),
            "provisional": report.get("provisional", False),
        }
        saved_trade_fact, created = self.repository.upsert_trade_fact(
            trade_fact,
            unique_keys=["broker_trade_id"],
        )
        if created:
            broker_order = self._apply_fill_to_broker_order(
                broker_order_key,
                saved_execution_fill,
                current_order=current_order,
            )
            self.repository.insert_order_event(
                {
                    "event_id": new_event_id(),
                    "request_id": None,
                    "internal_order_id": report["internal_order_id"],
                    "event_type": "trade_reported",
                    "state": (broker_order or {}).get("state", "PARTIAL_FILLED"),
                    "created_at": _utc_now_iso(),
                }
            )
        return {
            "trade_fact": saved_trade_fact,
            "execution_fill": saved_execution_fill,
            "created": created,
        }

    def _sync_broker_order_report(self, broker_order_key, report):
        broker_order = self.repository.find_broker_order(broker_order_key)
        if broker_order is None:
            return None
        updates = {
            "updated_at": _utc_now_iso(),
            "state": report.get("state") or broker_order.get("state"),
            "broker_order_id": report.get("broker_order_id")
            or broker_order.get("broker_order_id"),
            "submitted_at": report.get("submitted_at")
            or broker_order.get("submitted_at"),
        }
        next_document = {
            **broker_order,
            **{key: value for key, value in updates.items() if value is not None},
        }
        saved_broker_order, _ = self.repository.upsert_broker_order(
            next_document,
            unique_keys=["broker_order_key"],
        )
        return saved_broker_order

    def _apply_fill_to_broker_order(self, broker_order_key, execution_fill, *, current_order):
        broker_order = self.repository.find_broker_order(broker_order_key)
        if broker_order is None:
            broker_order = {
                "broker_order_key": broker_order_key,
                "internal_order_id": current_order.get("internal_order_id")
                if current_order
                else broker_order_key,
                "request_id": current_order.get("request_id") if current_order else None,
                "broker_order_id": execution_fill.get("broker_order_id"),
                "account_type": current_order.get("account_type") if current_order else None,
                "trace_id": current_order.get("trace_id") if current_order else None,
                "intent_id": current_order.get("intent_id") if current_order else None,
                "symbol": execution_fill.get("symbol"),
                "side": execution_fill.get("side"),
                "state": "PARTIAL_FILLED",
                "source_type": execution_fill.get("source"),
                "submitted_at": current_order.get("submitted_at") if current_order else None,
                "requested_quantity": None,
                "filled_quantity": 0,
                "avg_filled_price": None,
                "fill_count": 0,
                "first_fill_time": None,
                "last_fill_time": None,
                "updated_at": _utc_now_iso(),
            }
        previous_quantity = int(broker_order.get("filled_quantity") or 0)
        previous_fill_count = int(broker_order.get("fill_count") or 0)
        previous_notional = previous_quantity * float(
            broker_order.get("avg_filled_price") or 0
        )
        fill_quantity = int(execution_fill.get("quantity") or 0)
        fill_price = float(execution_fill.get("price") or 0)
        next_quantity = previous_quantity + fill_quantity
        next_fill_count = previous_fill_count + 1
        next_avg_price = (
            round((previous_notional + fill_quantity * fill_price) / next_quantity, 6)
            if next_quantity > 0
            else None
        )
        requested_quantity = broker_order.get("requested_quantity")
        next_state = "PARTIAL_FILLED"
        if requested_quantity not in (None, "") and next_quantity >= int(requested_quantity):
            next_state = "FILLED"
        next_document = {
            **broker_order,
            "broker_order_id": execution_fill.get("broker_order_id")
            or broker_order.get("broker_order_id"),
            "filled_quantity": next_quantity,
            "avg_filled_price": next_avg_price,
            "fill_count": next_fill_count,
            "first_fill_time": _pick_first_time(
                broker_order.get("first_fill_time"),
                execution_fill.get("trade_time"),
            ),
            "last_fill_time": _pick_last_time(
                broker_order.get("last_fill_time"),
                execution_fill.get("trade_time"),
            ),
            "state": next_state,
            "updated_at": _utc_now_iso(),
        }
        saved_broker_order, _ = self.repository.upsert_broker_order(
            next_document,
            unique_keys=["broker_order_key"],
        )
        return saved_broker_order


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _resolve_broker_order_key(report, *, current_order=None):
    broker_order_key = ""
    if current_order and current_order.get("internal_order_id"):
        broker_order_key = str(current_order.get("internal_order_id") or "").strip()
    if not broker_order_key:
        broker_order_key = str(
            report.get("broker_order_key") or report.get("internal_order_id") or ""
        ).strip()
    if not broker_order_key:
        raise ValueError("broker_order_key is required")
    return broker_order_key


def _pick_first_time(previous, current):
    if previous in (None, ""):
        return current
    if current in (None, ""):
        return previous
    return min(previous, current)


def _pick_last_time(previous, current):
    if previous in (None, ""):
        return current
    if current in (None, ""):
        return previous
    return max(previous, current)


def _should_absorb_terminal_replay(current_state: str, next_state: str) -> bool:
    return current_state == "FILLED" and next_state in {"PARTIAL_FILLED", "CANCELED"}
