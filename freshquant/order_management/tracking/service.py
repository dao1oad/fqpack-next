# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.ids import (
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
        internal_order_id = report["internal_order_id"]
        current_order = self.repository.find_order(internal_order_id)
        current_state = current_order["state"]
        next_state = self.state_machine.transition(current_state, report["state"])
        now = _utc_now_iso()

        self.repository.update_order(
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

    def ingest_trade_report(self, report):
        trade_fact = {
            "trade_fact_id": report.get("trade_fact_id") or new_trade_fact_id(),
            "internal_order_id": report["internal_order_id"],
            "broker_trade_id": report["broker_trade_id"],
            "symbol": report["symbol"],
            "side": report["side"],
            "quantity": report["quantity"],
            "price": report["price"],
            "trade_time": report["trade_time"],
            "source": report.get("source", "unknown"),
            "provisional": report.get("provisional", False),
        }
        saved_trade_fact, created = self.repository.upsert_trade_fact(
            trade_fact,
            unique_keys=["broker_trade_id"],
        )
        if created:
            self.repository.insert_order_event(
                {
                    "event_id": new_event_id(),
                    "request_id": None,
                    "internal_order_id": report["internal_order_id"],
                    "event_type": "trade_reported",
                    "state": "PARTIAL_FILLED",
                    "created_at": _utc_now_iso(),
                }
            )
        return saved_trade_fact


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
