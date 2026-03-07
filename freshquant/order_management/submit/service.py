# -*- coding: utf-8 -*-

import json
from datetime import datetime, timezone

from freshquant.carnation.config import STOCK_ORDER_QUEUE
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.util.code import normalize_to_base_code


class OrderSubmitService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        queue_client=None,
        position_management_service=None,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.queue_client = queue_client or _load_queue_client()
        self.position_management_service = (
            position_management_service or _load_position_management_service()
        )

    def submit_order(self, payload):
        action = payload["action"].lower()
        if action not in {"buy", "sell"}:
            raise ValueError(f"unsupported action: {action}")

        symbol = _normalize_symbol(payload["symbol"])
        price = float(payload["price"])
        quantity = int(payload["quantity"])
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        position_decision = None
        if payload.get("source") == "strategy":
            position_decision = (
                self.position_management_service.evaluate_strategy_order(
                    {
                        **payload,
                        "action": action,
                        "symbol": symbol,
                        "price": price,
                        "quantity": quantity,
                    }
                )
            )
            if not position_decision.allowed:
                raise PositionManagementRejectedError(
                    f"position management rejected: {position_decision.reason_code}"
                )

        request_id = self.tracking_service.submit_order(
            {
                **payload,
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
            }
        )
        order = self.repository.find_order_by_request_id(request_id)
        self.tracking_service.mark_order_queued(order["internal_order_id"])

        queue_payload = {
            "action": action,
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "fire_time": _now_local_string(),
            "strategy_name": payload.get("strategy_name"),
            "remark": payload.get("remark"),
            "retry_count": payload.get("retry_count", 0),
            "force": bool(payload.get("force", False)),
            "internal_order_id": order["internal_order_id"],
            "request_id": request_id,
            "source": payload.get("source", "unknown"),
            "scope_type": payload.get("scope_type"),
            "scope_ref_id": payload.get("scope_ref_id"),
        }
        if position_decision is not None:
            queue_payload["position_management_state"] = position_decision.state
            queue_payload["position_management_decision_id"] = (
                position_decision.decision_id
            )
            if position_decision.meta.get("force_profit_reduce") is not None:
                queue_payload["position_management_force_profit_reduce"] = bool(
                    position_decision.meta.get("force_profit_reduce")
                )
            if position_decision.meta.get("profit_reduce_mode"):
                queue_payload["position_management_profit_reduce_mode"] = (
                    position_decision.meta.get("profit_reduce_mode")
                )
        self.queue_client.lpush(
            STOCK_ORDER_QUEUE,
            json.dumps(queue_payload, ensure_ascii=False),
        )
        return {
            "request_id": request_id,
            "internal_order_id": order["internal_order_id"],
            "queue_payload": queue_payload,
        }

    def cancel_order(self, payload):
        internal_order_id = payload["internal_order_id"]
        request_id = self.tracking_service.cancel_order(payload)
        order = self.repository.find_order(internal_order_id)
        queue_payload = {
            "action": "cancel",
            "internal_order_id": internal_order_id,
            "broker_order_id": (
                str(order["broker_order_id"])
                if order.get("broker_order_id") is not None
                else None
            ),
            "symbol": order.get("symbol"),
            "strategy_name": payload.get("strategy_name"),
            "remark": payload.get("remark"),
            "request_id": request_id,
            "fire_time": _now_local_string(),
            "source": payload.get("source", "unknown"),
        }
        self.queue_client.lpush(
            STOCK_ORDER_QUEUE,
            json.dumps(queue_payload, ensure_ascii=False),
        )
        self.repository.insert_order_event(
            {
                "event_id": f"evt_cancel_queue_{request_id}",
                "request_id": request_id,
                "internal_order_id": internal_order_id,
                "event_type": "cancel_queued",
                "state": order["state"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return {
            "request_id": request_id,
            "internal_order_id": internal_order_id,
            "queue_payload": queue_payload,
        }


def _normalize_symbol(symbol):
    normalized = normalize_to_base_code(symbol)
    return normalized or symbol


def _load_queue_client():
    from freshquant.database.redis import redis_db

    return redis_db


def _load_position_management_service():
    from freshquant.position_management.service import PositionManagementService

    return PositionManagementService()


def _now_local_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
