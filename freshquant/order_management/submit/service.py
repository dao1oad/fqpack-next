# -*- coding: utf-8 -*-

import json
from datetime import datetime, timezone

from freshquant.carnation.config import STOCK_ORDER_QUEUE
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.submit.credit_order_resolver import (
    build_credit_subject_lookup,
    build_credit_subjects_available,
    get_configured_account_type,
    resolve_submit_credit_order,
)
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    is_exception_emitted,
    mark_exception_emitted,
)
from freshquant.runtime_observability.logger import RuntimeEventLogger
from freshquant.util.code import normalize_to_base_code


class OrderSubmitService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        queue_client=None,
        position_management_service=None,
        account_type_loader=None,
        credit_subject_lookup=None,
        credit_subjects_available=None,
        credit_order_resolver=None,
        runtime_logger=None,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.queue_client = queue_client or _load_queue_client()
        self.position_management_service = (
            position_management_service
            or _load_position_management_service(runtime_logger=runtime_logger)
        )
        self.account_type_loader = account_type_loader or get_configured_account_type
        self.credit_subject_lookup = (
            credit_subject_lookup or _default_credit_subject_lookup
        )
        self.credit_subjects_available = (
            credit_subjects_available or _default_credit_subjects_available
        )
        self.credit_order_resolver = (
            credit_order_resolver or resolve_submit_credit_order
        )
        self.runtime_logger = runtime_logger or _get_runtime_logger()

    def submit_order(self, payload):
        action = payload["action"].lower()
        symbol = _normalize_symbol(payload["symbol"])
        request_id = None
        internal_order_id = None
        current_node = "intent_normalize"
        try:
            if action not in {"buy", "sell"}:
                raise ValueError(f"unsupported action: {action}")

            price = float(payload["price"])
            quantity = int(payload["quantity"])
            if quantity <= 0:
                raise ValueError("quantity must be positive")
            account_type = _normalize_account_type(
                payload.get("account_type") or self.account_type_loader()
            )
            credit_trade_mode = _normalize_mode(payload.get("credit_trade_mode"))
            price_mode = _normalize_mode(payload.get("price_mode"))
            self._emit_runtime(
                "intent_normalize",
                payload=payload,
                action=action,
                symbol=symbol,
            )
            current_node = "credit_mode_resolve"
            credit_resolution = self.credit_order_resolver(
                account_type=account_type,
                action=action,
                symbol=symbol,
                requested_mode=credit_trade_mode,
                credit_subject_lookup=self.credit_subject_lookup,
                credit_subjects_available=self.credit_subjects_available,
            )
            self._emit_runtime(
                "credit_mode_resolve",
                payload=payload,
                action=action,
                symbol=symbol,
                extra_payload={
                    "account_type": account_type,
                    "credit_trade_mode": credit_trade_mode,
                    "credit_trade_mode_resolved": credit_resolution[
                        "credit_trade_mode_resolved"
                    ],
                    "broker_order_type": credit_resolution["broker_order_type"],
                },
            )

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
                        },
                        is_profitable=bool(
                            payload.get("position_management_is_profitable", False)
                        ),
                    )
                )
                if not position_decision.allowed:
                    rejection_reason = (
                        f"position management rejected: {position_decision.reason_code}"
                    )
                    self._emit_runtime(
                        current_node,
                        payload=payload,
                        action=action,
                        symbol=symbol,
                        status="failed",
                        reason_code="position_management_rejected",
                        extra_payload={
                            "reason": rejection_reason,
                            "position_management_state": position_decision.state,
                            "position_management_reason_code": (
                                position_decision.reason_code
                            ),
                            "position_management_decision_id": (
                                position_decision.decision_id
                            ),
                        },
                    )
                    exc = PositionManagementRejectedError(rejection_reason)
                    mark_exception_emitted(exc)
                    raise exc

            current_node = "tracking_create"
            request_id = self.tracking_service.submit_order(
                {
                    **payload,
                    "action": action,
                    "symbol": symbol,
                    "price": price,
                    "quantity": quantity,
                    "account_type": account_type,
                    "credit_trade_mode": credit_trade_mode,
                    "price_mode": price_mode,
                    **credit_resolution,
                }
            )
            order = self.repository.find_order_by_request_id(request_id)
            internal_order_id = (order or {}).get("internal_order_id")
            self._emit_runtime(
                "tracking_create",
                payload=payload,
                action=action,
                symbol=symbol,
                request_id=request_id,
                internal_order_id=internal_order_id,
                extra_payload={
                    "account_type": account_type,
                    "credit_trade_mode": credit_trade_mode,
                    "price_mode": price_mode,
                },
            )
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
                "trace_id": payload.get("trace_id"),
                "intent_id": payload.get("intent_id"),
                "source": payload.get("source", "unknown"),
                "scope_type": payload.get("scope_type"),
                "scope_ref_id": payload.get("scope_ref_id"),
                "strategy_context": payload.get("strategy_context"),
                "account_type": account_type,
                "credit_trade_mode": credit_trade_mode,
                "price_mode": price_mode,
                "credit_trade_mode_resolved": credit_resolution[
                    "credit_trade_mode_resolved"
                ],
                "broker_order_type": credit_resolution["broker_order_type"],
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
            current_node = "queue_payload_build"
            self._emit_runtime(
                "queue_payload_build",
                payload=payload,
                action=action,
                symbol=symbol,
                request_id=request_id,
                internal_order_id=order["internal_order_id"],
                extra_payload={"queue_payload": queue_payload},
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
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_runtime(
                    current_node,
                    payload=payload,
                    action=action,
                    symbol=symbol,
                    request_id=request_id,
                    internal_order_id=internal_order_id,
                    status="error",
                    reason_code="unexpected_exception",
                    extra_payload=build_exception_payload(exc),
                )
                mark_exception_emitted(exc)
            raise

    def cancel_order(self, payload):
        internal_order_id = payload["internal_order_id"]
        request_id = None
        current_node = "cancel_tracking_create"
        current_order = self.repository.find_order(internal_order_id) or {}
        runtime_payload = {
            **payload,
            "action": "cancel",
            "symbol": current_order.get("symbol") or payload.get("symbol"),
            "trace_id": current_order.get("trace_id") or payload.get("trace_id"),
            "intent_id": current_order.get("intent_id") or payload.get("intent_id"),
        }
        try:
            request_id = self.tracking_service.cancel_order(payload)
            order = self.repository.find_order(internal_order_id) or current_order
            runtime_payload["symbol"] = order.get("symbol") or runtime_payload.get(
                "symbol"
            )
            runtime_payload["trace_id"] = order.get("trace_id") or runtime_payload.get(
                "trace_id"
            )
            runtime_payload["intent_id"] = order.get(
                "intent_id"
            ) or runtime_payload.get("intent_id")
            self._emit_runtime(
                "cancel_tracking_create",
                payload=runtime_payload,
                action="cancel",
                symbol=order.get("symbol"),
                request_id=request_id,
                internal_order_id=internal_order_id,
                extra_payload={"state": order.get("state")},
            )

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
                "trace_id": runtime_payload.get("trace_id"),
                "intent_id": runtime_payload.get("intent_id"),
                "fire_time": _now_local_string(),
                "source": payload.get("source", "unknown"),
            }
            current_node = "cancel_queue_payload_build"
            self._emit_runtime(
                "cancel_queue_payload_build",
                payload=runtime_payload,
                action="cancel",
                symbol=order.get("symbol"),
                request_id=request_id,
                internal_order_id=internal_order_id,
                extra_payload={"queue_payload": queue_payload},
            )
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
        except Exception as exc:
            if not is_exception_emitted(exc):
                self._emit_runtime(
                    current_node,
                    payload=runtime_payload,
                    action="cancel",
                    symbol=runtime_payload.get("symbol"),
                    request_id=request_id,
                    internal_order_id=internal_order_id,
                    status="error",
                    reason_code="unexpected_exception",
                    extra_payload=build_exception_payload(exc),
                )
                mark_exception_emitted(exc)
            raise

    def _emit_runtime(
        self,
        node,
        *,
        payload,
        action=None,
        symbol=None,
        request_id=None,
        internal_order_id=None,
        status="info",
        reason_code="",
        extra_payload=None,
    ):
        event = {
            "component": "order_submit",
            "node": node,
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "request_id": request_id,
            "internal_order_id": internal_order_id,
            "action": action or payload.get("action"),
            "symbol": symbol or payload.get("symbol"),
            "strategy_name": payload.get("strategy_name"),
            "source": payload.get("source"),
            "status": status,
            "reason_code": reason_code,
            "payload": dict(extra_payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


def _normalize_symbol(symbol):
    normalized = normalize_to_base_code(symbol)
    return normalized or symbol


def _load_queue_client():
    from freshquant.database.redis import redis_db

    return redis_db


def _load_position_management_service(runtime_logger=None):
    from freshquant.position_management.repository import PositionManagementRepository
    from freshquant.position_management.service import PositionManagementService

    repository = PositionManagementRepository()
    return PositionManagementService(
        repository=repository,
        runtime_logger=runtime_logger,
        symbol_position_loader=lambda symbol: repository.get_symbol_snapshot(symbol),
    )


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("order_submit")
    return _runtime_logger


def _now_local_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_account_type(account_type):
    value = str(account_type or "STOCK").strip().upper()
    return value or "STOCK"


def _normalize_mode(value, default="auto"):
    normalized = str(value or default).strip().lower()
    return normalized or default


def _default_credit_subject_lookup(symbol):
    return build_credit_subject_lookup()(symbol)


def _default_credit_subjects_available():
    return build_credit_subjects_available()()
