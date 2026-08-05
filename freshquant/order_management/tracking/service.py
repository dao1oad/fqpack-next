# -*- coding: utf-8 -*-

import hashlib
import json
from datetime import datetime, timezone

from freshquant.order_management.broker_correlation import (
    build_broker_correlation_token,
    looks_like_broker_correlation_token,
    normalize_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    BrokerIdentityError,
    build_broker_only_internal_order_id,
    build_broker_order_key,
    build_execution_identity,
    identity_conflicts,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    resolve_trading_day,
)
from freshquant.order_management.ids import (
    new_event_id,
    new_execution_fill_id,
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
        raw_correlation_token = payload.get("broker_correlation_token")
        broker_correlation_token = normalize_broker_correlation_token(
            raw_correlation_token
        )
        if raw_correlation_token not in (None, "", "None"):
            if broker_correlation_token is None:
                raise BrokerIdentityError("broker correlation token is invalid")
        else:
            broker_correlation_token = build_broker_correlation_token(internal_order_id)
        now = _utc_now_iso()
        trading_day = resolve_trading_day(payload)
        initial_broker_order_key = (
            build_broker_order_key(
                account_id=payload.get("account_id"),
                order_sysid=payload.get("order_sysid"),
                trading_day=trading_day,
                symbol=payload.get("symbol"),
                side=payload.get("action"),
                broker_order_id=payload.get("broker_order_id"),
                strict=False,
            )
            or internal_order_id
        )

        request_document = {
            "request_id": request_id,
            "action": payload["action"],
            "source": payload.get("source", "unknown"),
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "account_type": payload.get("account_type"),
            "account_id": normalize_account_id(payload.get("account_id")),
            "trading_day": trading_day,
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
            "broker_correlation_token": broker_correlation_token,
            "state": "ACCEPTED",
            "created_at": now,
        }
        order_document = {
            "internal_order_id": internal_order_id,
            "request_id": request_id,
            "broker_order_id": payload.get("broker_order_id"),
            "broker_order_key": initial_broker_order_key,
            "broker_order_type": payload.get("broker_order_type"),
            "broker_price_type": payload.get("broker_price_type"),
            "broker_correlation_token": broker_correlation_token,
            "account_type": payload.get("account_type"),
            "account_id": normalize_account_id(payload.get("account_id")),
            "order_sysid": normalize_identifier(payload.get("order_sysid")),
            "trading_day": trading_day,
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
        if hasattr(self.repository, "upsert_broker_order"):
            self.repository.upsert_broker_order(
                {
                    "broker_order_key": initial_broker_order_key,
                    "internal_order_id": internal_order_id,
                    "request_id": request_id,
                    "broker_order_id": payload.get("broker_order_id"),
                    "broker_order_type": payload.get("broker_order_type"),
                    "broker_price_type": payload.get("broker_price_type"),
                    "broker_correlation_token": broker_correlation_token,
                    "account_type": payload.get("account_type"),
                    "account_id": normalize_account_id(payload.get("account_id")),
                    "order_sysid": normalize_identifier(payload.get("order_sysid")),
                    "trading_day": trading_day,
                    "trace_id": payload.get("trace_id"),
                    "intent_id": payload.get("intent_id"),
                    "symbol": payload.get("symbol"),
                    "side": payload["action"],
                    "credit_trade_mode_requested": payload.get("credit_trade_mode"),
                    "credit_trade_mode_resolved": payload.get(
                        "credit_trade_mode_resolved"
                    ),
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
        report = dict(report)
        internal_order_id = report["internal_order_id"]
        current_order = self.repository.find_order(internal_order_id)
        if current_order is None:
            current_order = self._create_broker_only_order(report)
            broker_order_key = _resolve_broker_order_key(
                report, current_order=current_order
            )
            self._sync_broker_order_report(
                broker_order_key,
                report,
                current_order=current_order,
                placeholder_key=internal_order_id,
            )
            self.repository.insert_order_event(
                {
                    "event_id": new_event_id(),
                    "request_id": None,
                    "internal_order_id": internal_order_id,
                    "event_type": report.get(
                        "event_type", "broker_only_order_reported"
                    ),
                    "state": current_order["state"],
                    "created_at": _utc_now_iso(),
                }
            )
            return {"order": current_order, "changed": True, "absorbed": False}

        _assert_order_report_identity(current_order, report)
        placeholder_key = current_order.get("broker_order_key") or internal_order_id
        merged_identity = {**current_order, **_non_empty_identity_fields(report)}
        broker_order_key = _resolve_broker_order_key(
            merged_identity, current_order=merged_identity
        )
        current_state = current_order["state"]
        updates = {
            key: value
            for key, value in _non_empty_identity_fields(report).items()
            if current_order.get(key) != value
        }
        if current_order.get("broker_order_key") != broker_order_key:
            updates["broker_order_key"] = broker_order_key
        if report.get("submitted_at") and not current_order.get("submitted_at"):
            updates["submitted_at"] = report.get("submitted_at")
        if current_state == report["state"]:
            if updates:
                updates["updated_at"] = _utc_now_iso()
                updated_order = self.repository.update_order(internal_order_id, updates)
                self._sync_broker_order_report(
                    broker_order_key,
                    {
                        **report,
                        "broker_order_id": report.get("broker_order_id"),
                        "submitted_at": report.get("submitted_at"),
                        "state": current_state,
                    },
                    current_order=updated_order,
                    placeholder_key=placeholder_key,
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
                    broker_order_key,
                    {
                        **report,
                        "broker_order_id": report.get("broker_order_id"),
                        "submitted_at": report.get("submitted_at"),
                        "state": current_order.get("state"),
                    },
                    current_order=current_order,
                    placeholder_key=placeholder_key,
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
                **updates,
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
            broker_order_key,
            {
                **report,
                "broker_order_id": report.get("broker_order_id"),
                "submitted_at": report.get("submitted_at"),
                "state": next_state,
            },
            current_order=updated_order,
            placeholder_key=placeholder_key,
        )
        return {"order": updated_order, "changed": True, "absorbed": False}

    def ingest_trade_report(self, report):
        return self.ingest_trade_report_with_meta(report)["trade_fact"]

    def ingest_trade_report_with_meta(self, report):
        report = _normalize_trade_report_identity(report)
        current_order = self.repository.find_order(report["internal_order_id"])
        create_broker_only_order = current_order is None
        if current_order is None:
            current_order = self._build_broker_only_order(
                {**report, "state": "PARTIAL_FILLED"}
            )
        else:
            _assert_order_report_identity(current_order, report)

        placeholder_key = current_order.get("broker_order_key") or current_order.get(
            "internal_order_id"
        )
        identity_updates = {
            key: value
            for key, value in _non_empty_identity_fields(report).items()
            if current_order.get(key) != value
        }
        broker_order_key = _resolve_broker_order_key(
            report, current_order=current_order
        )
        if current_order.get("broker_order_key") != broker_order_key:
            identity_updates["broker_order_key"] = broker_order_key
        effective_order = {**current_order, **identity_updates}

        execution_identity = build_execution_identity(report)
        execution_fill = {
            "execution_fill_id": report.get("execution_fill_id")
            or new_execution_fill_id(),
            "broker_order_key": broker_order_key,
            "internal_order_id": report["internal_order_id"],
            "request_id": effective_order.get("request_id"),
            "broker_order_id": report.get("broker_order_id")
            or effective_order.get("broker_order_id"),
            "broker_trade_id": report["broker_trade_id"],
            "execution_identity": execution_identity,
            "account_id": report.get("account_id"),
            "order_sysid": report.get("order_sysid"),
            "trading_day": report.get("trading_day"),
            "symbol": report["symbol"],
            "side": report["side"],
            "quantity": report["quantity"],
            "price": report["price"],
            "trade_time": report["trade_time"],
            "date": report.get("date"),
            "time": report.get("time"),
            "source": report.get("source", "unknown"),
            "provisional": report.get("provisional", False),
            "projection_status": "PENDING",
            "projection_plan": None,
            "execution_record_version": 2,
        }
        trade_fact = {
            "trade_fact_id": report.get("trade_fact_id") or new_trade_fact_id(),
            "broker_order_key": broker_order_key,
            "internal_order_id": report["internal_order_id"],
            "broker_order_id": report.get("broker_order_id"),
            "broker_trade_id": report["broker_trade_id"],
            "execution_identity": execution_identity,
            "account_id": report.get("account_id"),
            "order_sysid": report.get("order_sysid"),
            "trading_day": report.get("trading_day"),
            "symbol": report["symbol"],
            "side": report["side"],
            "quantity": report["quantity"],
            "price": report["price"],
            "trade_time": report["trade_time"],
            "date": report.get("date"),
            "time": report.get("time"),
            "source": report.get("source", "unknown"),
            "provisional": report.get("provisional", False),
            "execution_record_version": 2,
        }
        if hasattr(self.repository, "preflight_execution_replay"):
            self.repository.preflight_execution_replay(execution_fill)
        saved_trade_fact, created = self.repository.upsert_trade_fact(
            trade_fact,
            unique_keys=["execution_identity"],
        )
        if hasattr(self.repository, "upsert_execution_fill"):
            saved_execution_fill, created_execution_fill = (
                self.repository.upsert_execution_fill(
                    execution_fill,
                    unique_keys=["execution_identity"],
                )
            )
        else:
            saved_execution_fill = dict(execution_fill)
            created_execution_fill = created
            if not created_execution_fill:
                saved_execution_fill["projection_status"] = "APPLIED"
        _assert_execution_replay_consistent(saved_trade_fact, trade_fact)
        _assert_execution_replay_consistent(saved_execution_fill, execution_fill)
        if create_broker_only_order:
            self.repository.insert_order(effective_order)
            current_order = effective_order
        elif identity_updates:
            current_order = self.repository.update_order(
                report["internal_order_id"],
                {**identity_updates, "updated_at": _utc_now_iso()},
            )
        else:
            current_order = effective_order
        created = bool(created_execution_fill)
        projection_pending = (
            str(saved_execution_fill.get("projection_status") or "").upper()
            == "PENDING"
        )
        if created or projection_pending:
            self._migrate_broker_order_placeholder(
                placeholder_key=placeholder_key,
                broker_order_key=broker_order_key,
                current_order=current_order,
                report=report,
            )
            broker_order = self._apply_fill_to_broker_order(
                broker_order_key,
                saved_execution_fill,
                current_order=current_order,
            )
        if created:
            self.repository.insert_order_event(
                {
                    "event_id": new_event_id(),
                    "request_id": current_order.get("request_id"),
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

    def _build_broker_only_order(self, report):
        internal_order_id = normalize_identifier(report.get("internal_order_id"))
        if internal_order_id is None:
            internal_order_id = build_broker_only_internal_order_id(
                account_id=report.get("account_id"),
                order_sysid=report.get("order_sysid"),
                trading_day=resolve_trading_day(report),
                symbol=report.get("symbol"),
                side=report.get("side"),
                broker_order_id=report.get("broker_order_id"),
            )
        broker_order_key = _resolve_broker_order_key(
            {**report, "internal_order_id": internal_order_id}
        )
        now = _utc_now_iso()
        document = {
            "internal_order_id": internal_order_id,
            "request_id": None,
            "broker_order_key": broker_order_key,
            "broker_order_id": normalize_identifier(report.get("broker_order_id")),
            "broker_order_type": report.get("broker_order_type")
            or report.get("order_type"),
            "broker_correlation_token": normalize_broker_correlation_token(
                report.get("broker_correlation_token") or report.get("order_remark")
            ),
            "account_type": report.get("account_type"),
            "account_id": normalize_account_id(report.get("account_id")),
            "order_sysid": normalize_identifier(report.get("order_sysid")),
            "trading_day": resolve_trading_day(report),
            "trace_id": report.get("trace_id"),
            "intent_id": report.get("intent_id"),
            "symbol": normalize_symbol(report.get("symbol")),
            "side": normalize_side(report.get("side")),
            "state": report.get("state") or "PARTIAL_FILLED",
            "source_type": "broker_only",
            "submitted_at": report.get("submitted_at"),
            "filled_quantity": 0,
            "avg_filled_price": None,
            "created_at": now,
            "updated_at": now,
        }
        return document

    def _create_broker_only_order(self, report):
        document = self._build_broker_only_order(report)
        self.repository.insert_order(document)
        return document

    def _migrate_broker_order_placeholder(
        self,
        *,
        placeholder_key,
        broker_order_key,
        current_order,
        report,
    ):
        if not hasattr(self.repository, "find_broker_order") or not hasattr(
            self.repository, "upsert_broker_order"
        ):
            return None
        placeholder_key = normalize_identifier(placeholder_key)
        broker_order_key = normalize_identifier(broker_order_key)
        if broker_order_key is None:
            raise BrokerIdentityError("broker_order_key is required")
        target = self.repository.find_broker_order(broker_order_key)
        placeholder = (
            self.repository.find_broker_order(placeholder_key)
            if placeholder_key and placeholder_key != broker_order_key
            else None
        )
        source = target or placeholder or {}
        next_document = {
            **source,
            "broker_order_key": broker_order_key,
            "internal_order_id": current_order.get("internal_order_id"),
            "request_id": current_order.get("request_id"),
            "broker_order_id": normalize_identifier(
                report.get("broker_order_id")
                or current_order.get("broker_order_id")
                or source.get("broker_order_id")
            ),
            "broker_correlation_token": normalize_broker_correlation_token(
                report.get("broker_correlation_token") or report.get("order_remark")
            )
            or current_order.get("broker_correlation_token")
            or source.get("broker_correlation_token"),
            "account_type": current_order.get("account_type")
            or report.get("account_type")
            or source.get("account_type"),
            "account_id": normalize_account_id(
                report.get("account_id")
                or current_order.get("account_id")
                or source.get("account_id")
            ),
            "order_sysid": normalize_identifier(
                report.get("order_sysid")
                or current_order.get("order_sysid")
                or source.get("order_sysid")
            ),
            "trading_day": resolve_trading_day({**source, **current_order, **report}),
            "symbol": normalize_symbol(
                report.get("symbol")
                or current_order.get("symbol")
                or source.get("symbol")
            ),
            "side": normalize_side(
                report.get("side") or current_order.get("side") or source.get("side")
            ),
            "trace_id": current_order.get("trace_id") or source.get("trace_id"),
            "intent_id": current_order.get("intent_id") or source.get("intent_id"),
            "source_type": source.get("source_type")
            or current_order.get("source_type")
            or report.get("source"),
            "submitted_at": current_order.get("submitted_at")
            or report.get("submitted_at")
            or source.get("submitted_at"),
            "requested_quantity": source.get("requested_quantity"),
            "filled_quantity": int(source.get("filled_quantity") or 0),
            "avg_filled_price": source.get("avg_filled_price"),
            "fill_count": int(source.get("fill_count") or 0),
            "first_fill_time": source.get("first_fill_time"),
            "last_fill_time": source.get("last_fill_time"),
            "state": report.get("state")
            or source.get("state")
            or current_order.get("state"),
            "updated_at": _utc_now_iso(),
        }
        if (
            placeholder_key
            and placeholder_key != broker_order_key
            and hasattr(self.repository, "move_broker_order_key")
        ):
            return self.repository.move_broker_order_key(
                placeholder_key,
                broker_order_key,
                next_document,
            )
        saved, _ = self.repository.upsert_broker_order(
            next_document,
            unique_keys=["broker_order_key"],
        )
        if placeholder_key and placeholder_key != broker_order_key:
            _delete_broker_order(self.repository, placeholder_key)
        return saved

    def _sync_broker_order_report(
        self,
        broker_order_key,
        report,
        *,
        current_order=None,
        placeholder_key=None,
    ):
        if not hasattr(self.repository, "find_broker_order") or not hasattr(
            self.repository, "upsert_broker_order"
        ):
            return None
        current_order = current_order or self.repository.find_order(
            report.get("internal_order_id") or broker_order_key
        )
        if current_order is not None:
            self._migrate_broker_order_placeholder(
                placeholder_key=placeholder_key
                or current_order.get("broker_order_key")
                or current_order.get("internal_order_id"),
                broker_order_key=broker_order_key,
                current_order=current_order,
                report=report,
            )
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
            "account_id": normalize_account_id(report.get("account_id"))
            or broker_order.get("account_id"),
            "order_sysid": normalize_identifier(report.get("order_sysid"))
            or broker_order.get("order_sysid"),
            "trading_day": resolve_trading_day(report)
            or broker_order.get("trading_day"),
            "symbol": normalize_symbol(report.get("symbol"))
            or broker_order.get("symbol"),
            "side": normalize_side(report.get("side")) or broker_order.get("side"),
            "broker_correlation_token": normalize_broker_correlation_token(
                report.get("broker_correlation_token") or report.get("order_remark")
            )
            or broker_order.get("broker_correlation_token"),
        }
        update_fields = {
            key: value for key, value in updates.items() if value is not None
        }
        if hasattr(self.repository, "update_broker_order_fields"):
            return self.repository.update_broker_order_fields(
                broker_order_key,
                update_fields,
            )
        next_document = {
            **broker_order,
            **update_fields,
        }
        saved_broker_order, _ = self.repository.upsert_broker_order(
            next_document,
            unique_keys=["broker_order_key"],
        )
        return saved_broker_order

    def _apply_fill_to_broker_order(
        self, broker_order_key, execution_fill, *, current_order
    ):
        if not hasattr(self.repository, "find_broker_order") or not hasattr(
            self.repository, "upsert_broker_order"
        ):
            return None
        for _attempt in range(8):
            broker_order = self.repository.find_broker_order(broker_order_key)
            if broker_order is None:
                broker_order = {
                    "broker_order_key": broker_order_key,
                    "internal_order_id": (
                        current_order.get("internal_order_id")
                        if current_order
                        else broker_order_key
                    ),
                    "request_id": (
                        current_order.get("request_id") if current_order else None
                    ),
                    "broker_order_id": execution_fill.get("broker_order_id"),
                    "account_id": execution_fill.get("account_id"),
                    "order_sysid": execution_fill.get("order_sysid"),
                    "trading_day": execution_fill.get("trading_day"),
                    "account_type": (
                        current_order.get("account_type") if current_order else None
                    ),
                    "trace_id": (
                        current_order.get("trace_id") if current_order else None
                    ),
                    "intent_id": (
                        current_order.get("intent_id") if current_order else None
                    ),
                    "symbol": execution_fill.get("symbol"),
                    "side": execution_fill.get("side"),
                    "state": "PARTIAL_FILLED",
                    "source_type": execution_fill.get("source"),
                    "submitted_at": (
                        current_order.get("submitted_at") if current_order else None
                    ),
                    "requested_quantity": None,
                    "filled_quantity": 0,
                    "avg_filled_price": None,
                    "fill_count": 0,
                    "fill_set_fingerprint": None,
                    "aggregate_revision": 0,
                    "first_fill_time": None,
                    "last_fill_time": None,
                    "updated_at": _utc_now_iso(),
                }
                broker_order, _ = self.repository.upsert_broker_order(
                    broker_order,
                    unique_keys=["broker_order_key"],
                )
                continue
            conflicts = identity_conflicts(broker_order, execution_fill)
            if conflicts:
                raise BrokerIdentityConflict(
                    "execution fill conflicts with broker aggregate: "
                    + ", ".join(sorted(conflicts))
                )
            fills = _list_broker_execution_fills(
                self.repository,
                broker_order_key=broker_order_key,
                fallback_fill=execution_fill,
            )
            for fill in fills:
                conflicts = identity_conflicts(broker_order, fill)
                if conflicts:
                    raise BrokerIdentityConflict(
                        "broker aggregate contains mixed execution identities: "
                        + ", ".join(sorted(conflicts))
                    )
            next_quantity = sum(int(fill.get("quantity") or 0) for fill in fills)
            next_fill_count = len(fills)
            next_notional = sum(
                int(fill.get("quantity") or 0) * float(fill.get("price") or 0)
                for fill in fills
            )
            next_avg_price = (
                round(next_notional / next_quantity, 6) if next_quantity > 0 else None
            )
            first_fill_time, last_fill_time = _fill_time_bounds(fills)
            requested_quantity = broker_order.get("requested_quantity")
            next_state = "PARTIAL_FILLED"
            if requested_quantity not in (None, "") and next_quantity >= int(
                requested_quantity
            ):
                next_state = "FILLED"
            fill_set_fingerprint = _fill_set_fingerprint(fills)
            next_document = {
                **broker_order,
                "broker_order_id": execution_fill.get("broker_order_id")
                or broker_order.get("broker_order_id"),
                "account_id": execution_fill.get("account_id")
                or broker_order.get("account_id"),
                "order_sysid": execution_fill.get("order_sysid")
                or broker_order.get("order_sysid"),
                "trading_day": execution_fill.get("trading_day")
                or broker_order.get("trading_day"),
                "filled_quantity": next_quantity,
                "avg_filled_price": next_avg_price,
                "fill_count": next_fill_count,
                "fill_set_fingerprint": fill_set_fingerprint,
                "aggregate_revision": int(broker_order.get("aggregate_revision") or 0)
                + 1,
                "first_fill_time": first_fill_time,
                "last_fill_time": last_fill_time,
                "state": next_state,
                "updated_at": _utc_now_iso(),
            }
            if hasattr(self.repository, "compare_and_set_broker_order"):
                saved_broker_order = self.repository.compare_and_set_broker_order(
                    before=broker_order,
                    after=next_document,
                )
                if saved_broker_order is None:
                    continue
            else:
                saved_broker_order, _ = self.repository.upsert_broker_order(
                    next_document,
                    unique_keys=["broker_order_key"],
                )
            latest_fills = _list_broker_execution_fills(
                self.repository,
                broker_order_key=broker_order_key,
                fallback_fill=execution_fill,
            )
            if _fill_set_fingerprint(latest_fills) == fill_set_fingerprint:
                return saved_broker_order
        raise BrokerIdentityConflict(
            "broker aggregate could not converge after concurrent updates"
        )


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _resolve_broker_order_key(report, *, current_order=None):
    identity = dict(current_order or {})
    identity.update(_non_empty_identity_fields(report))
    broker_order_key = build_broker_order_key(
        account_id=identity.get("account_id"),
        order_sysid=identity.get("order_sysid"),
        trading_day=resolve_trading_day(identity),
        symbol=identity.get("symbol"),
        side=identity.get("side"),
        broker_order_id=identity.get("broker_order_id"),
        strict=False,
    )
    if broker_order_key is not None:
        return broker_order_key
    fallback_key = normalize_identifier(
        (current_order or {}).get("broker_order_key")
        or report.get("broker_order_key")
        or (current_order or {}).get("internal_order_id")
        or report.get("internal_order_id")
    )
    if fallback_key is None:
        raise BrokerIdentityError("broker_order_key is required")
    return fallback_key


def _normalize_trade_report_identity(report):
    normalized = dict(report)
    normalized["account_id"] = normalize_account_id(report.get("account_id"))
    normalized["order_sysid"] = normalize_identifier(report.get("order_sysid"))
    normalized["broker_order_id"] = normalize_identifier(
        report.get("broker_order_id") or report.get("order_id")
    )
    normalized["broker_trade_id"] = normalize_identifier(
        report.get("broker_trade_id") or report.get("traded_id")
    )
    normalized["symbol"] = normalize_symbol(
        report.get("symbol") or report.get("stock_code")
    )
    normalized["side"] = normalize_side(report.get("side"))
    normalized["trading_day"] = resolve_trading_day(report)
    if normalized["account_id"] is None:
        raise BrokerIdentityError("execution report requires account_id")
    if normalized["broker_trade_id"] is None:
        raise BrokerIdentityError("broker_trade_id is required")
    if normalized["symbol"] is None:
        raise BrokerIdentityError("trade symbol is required")
    if normalized["side"] is None:
        raise BrokerIdentityError("unknown broker order side")
    if normalized["trading_day"] is None:
        raise BrokerIdentityError("trade trading_day is required")
    try:
        quantity = int(report.get("quantity"))
    except (TypeError, ValueError, OverflowError):
        raise BrokerIdentityError("execution quantity must be a positive integer")
    if quantity <= 0 or quantity != float(report.get("quantity")):
        raise BrokerIdentityError("execution quantity must be a positive integer")
    normalized["quantity"] = quantity
    internal_order_id = normalize_identifier(report.get("internal_order_id"))
    if internal_order_id is None:
        internal_order_id = build_broker_only_internal_order_id(
            account_id=normalized["account_id"],
            order_sysid=normalized["order_sysid"],
            trading_day=normalized["trading_day"],
            symbol=normalized["symbol"],
            side=normalized["side"],
            broker_order_id=normalized["broker_order_id"],
        )
    normalized["internal_order_id"] = internal_order_id
    return normalized


def _non_empty_identity_fields(payload):
    raw_correlation_token = payload.get("broker_correlation_token") or payload.get(
        "order_remark"
    )
    broker_correlation_token = normalize_broker_correlation_token(raw_correlation_token)
    if broker_correlation_token is None and looks_like_broker_correlation_token(
        raw_correlation_token
    ):
        raise BrokerIdentityConflict("broker correlation token is malformed")
    normalized = {
        "account_id": normalize_account_id(payload.get("account_id")),
        "order_sysid": normalize_identifier(payload.get("order_sysid")),
        "trading_day": resolve_trading_day(payload),
        "symbol": normalize_symbol(payload.get("symbol") or payload.get("stock_code")),
        "side": normalize_side(payload.get("side")),
        "broker_order_id": normalize_identifier(
            payload.get("broker_order_id") or payload.get("order_id")
        ),
        "broker_correlation_token": broker_correlation_token,
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _assert_order_report_identity(current_order, report):
    report_identity = _non_empty_identity_fields(report)
    current_identity = {
        **current_order,
        "trading_day": resolve_trading_day(current_order),
    }
    conflicts = identity_conflicts(current_identity, report_identity)
    current_correlation_token = normalize_broker_correlation_token(
        current_order.get("broker_correlation_token")
    )
    report_correlation_token = normalize_broker_correlation_token(
        report_identity.get("broker_correlation_token")
    )
    if (
        current_correlation_token is not None
        and report_correlation_token is not None
        and current_correlation_token != report_correlation_token
    ):
        conflicts["broker_correlation_token"] = (
            current_correlation_token,
            report_correlation_token,
        )
    if conflicts:
        raise BrokerIdentityConflict(
            "broker report conflicts with internal order: "
            + ", ".join(sorted(conflicts))
        )


def _assert_execution_replay_consistent(existing, incoming):
    conflicts = identity_conflicts(existing, incoming)
    for field in (
        "execution_identity",
        "broker_trade_id",
        "broker_order_key",
        "internal_order_id",
        "quantity",
        "price",
        "trade_time",
    ):
        left = existing.get(field)
        right = incoming.get(field)
        if left is not None and right is not None and left != right:
            conflicts[field] = (left, right)
    if conflicts:
        raise BrokerIdentityConflict(
            "execution replay conflicts with canonical fill: "
            + ", ".join(sorted(conflicts))
        )


def _list_broker_execution_fills(repository, *, broker_order_key, fallback_fill):
    if hasattr(repository, "list_execution_fills"):
        fills = repository.list_execution_fills(broker_order_keys=[broker_order_key])
    elif isinstance(getattr(repository, "execution_fills", None), list):
        fills = [
            fill
            for fill in repository.execution_fills
            if fill.get("broker_order_key") == broker_order_key
        ]
    else:
        fills = [fallback_fill]
    deduplicated = {}
    for fill in fills:
        key = fill.get("execution_identity") or fill.get("execution_fill_id")
        deduplicated[key] = fill
    return list(deduplicated.values())


def _delete_broker_order(repository, broker_order_key):
    if hasattr(repository, "delete_broker_order"):
        repository.delete_broker_order(broker_order_key)
        return
    broker_orders = getattr(repository, "broker_orders", None)
    if isinstance(broker_orders, list):
        repository.broker_orders = [
            order
            for order in broker_orders
            if order.get("broker_order_key") != broker_order_key
        ]
        return
    if hasattr(broker_orders, "delete_one"):
        broker_orders.delete_one({"broker_order_key": broker_order_key})


def _fill_time_bounds(fills):
    values = [
        fill.get("trade_time") for fill in fills if fill.get("trade_time") is not None
    ]
    if not values:
        return None, None
    return min(values), max(values)


def _fill_set_fingerprint(fills):
    payload = sorted(
        (
            str(fill.get("execution_identity") or fill.get("execution_fill_id") or ""),
            int(fill.get("quantity") or 0),
            str(fill.get("price") or ""),
            int(fill.get("trade_time") or 0),
        )
        for fill in fills
    )
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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
