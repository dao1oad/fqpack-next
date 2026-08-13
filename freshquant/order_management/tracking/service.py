# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

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
from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    LEDGER_T,
    InvalidLedgerIntentError,
    LedgerIntentMissingError,
    normalize_ledger_intent,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.order_state import (
    LATE_ORDER_REPORT_EVENT_TYPE,
    LATE_TRADE_EVENT_TYPE,
    OrderStateService,
)
from freshquant.order_management.tracking.state_machine import OrderStateMachine


class OrderTrackingService:
    def __init__(self, repository=None, state_machine=None, order_state=None):
        self.repository = repository or OrderManagementRepository()
        self.state_machine = state_machine or OrderStateMachine()
        self.order_state = order_state or OrderStateService(
            state_machine=self.state_machine
        )

    def submit_order(self, payload):
        request_id = payload.get("request_id") or new_request_id()
        internal_order_id = payload.get("internal_order_id") or new_internal_order_id()
        action = str(payload.get("action") or "").strip().lower()
        # #571：ledger_intent 必填 fail-closed；buy 只允许 base/t。
        ledger_intent = normalize_ledger_intent(payload.get("ledger_intent"))
        if action in {"buy", "sell"}:
            if ledger_intent is None:
                raise LedgerIntentMissingError(
                    "ledger_intent is required for buy/sell orders (fail-closed); "
                    "TPSL/Guardian/manual writers must declare base/t/-"
                )
            if action == "buy" and ledger_intent not in {LEDGER_BASE, LEDGER_T}:
                raise InvalidLedgerIntentError(
                    f"buy ledger_intent must be base or t, got {ledger_intent!r}"
                )
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
        broker_order_key = _resolve_broker_order_key(
            {
                **payload,
                "internal_order_id": internal_order_id,
                "broker_correlation_token": broker_correlation_token,
                "trading_day": trading_day,
            }
        )

        request_document = {
            "request_id": request_id,
            "action": action,
            "source": payload.get("source", "unknown"),
            "trace_id": payload.get("trace_id"),
            "intent_id": payload.get("intent_id"),
            "account_type": payload.get("account_type"),
            "account_id": normalize_account_id(payload.get("account_id")),
            "trading_day": trading_day,
            "symbol": payload.get("symbol"),
            "price": payload.get("price"),
            "quantity": payload.get("quantity"),
            "ledger_intent": ledger_intent,
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
            "broker_order_key": broker_order_key,
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
        self.repository.claim_broker_order_owner(
            _broker_order_owner_claim(order_document)
        )
        self.repository.update_broker_order_fields(
            broker_order_key,
            {
                "broker_order_type": payload.get("broker_order_type"),
                "broker_price_type": payload.get("broker_price_type"),
                "account_type": payload.get("account_type"),
                "trace_id": payload.get("trace_id"),
                "intent_id": payload.get("intent_id"),
                "credit_trade_mode_requested": payload.get("credit_trade_mode"),
                "credit_trade_mode_resolved": payload.get("credit_trade_mode_resolved"),
                "price_mode_requested": payload.get("price_mode"),
                "price_mode_resolved": payload.get("price_mode_resolved"),
                "state": "ACCEPTED",
                "submitted_at": None,
                "requested_quantity": payload.get("quantity"),
                "updated_at": now,
            },
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
            current_order.get("broker_order_key") or internal_order_id,
            {
                "state": next_state,
            },
            current_order=current_order,
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
            order.get("broker_order_key") or internal_order_id,
            {
                "state": next_state,
            },
            current_order=order,
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
        created_broker_only = current_order is None
        if current_order is None:
            current_order = self._build_broker_only_order(report)
            internal_order_id = current_order["internal_order_id"]
            report["internal_order_id"] = internal_order_id
            self.repository.insert_order(current_order)
        else:
            _assert_order_report_identity(current_order, report)

        placeholder_key = (
            current_order.get("broker_order_key") or current_order["internal_order_id"]
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
        if created_broker_only:
            self._sync_broker_order_report(
                broker_order_key,
                report,
                current_order=effective_order,
                placeholder_key=placeholder_key,
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

        current_state = current_order["state"]
        updates = {}
        updates.update(identity_updates)
        if report.get("submitted_at") and not current_order.get("submitted_at"):
            updates["submitted_at"] = report.get("submitted_at")
        # #571 OrderStateService：终态门禁（FILLED/CANCELED 不回退、迟到回报告警）。
        next_state, absorbed, late_alert = self.order_state.apply_order_report(
            current_state,
            report["state"],
        )

        self._sync_broker_order_report(
            broker_order_key,
            {**report, "state": next_state},
            current_order=effective_order,
            placeholder_key=placeholder_key,
        )
        if late_alert and absorbed and next_state in {"FILLED", "CANCELED"}:
            self.repository.insert_order_event(
                {
                    "event_id": new_event_id(),
                    "request_id": current_order.get("request_id"),
                    "internal_order_id": internal_order_id,
                    "event_type": LATE_ORDER_REPORT_EVENT_TYPE,
                    "state": next_state,
                    "payload": {
                        "incoming_state": report["state"],
                        "broker_order_id": report.get("broker_order_id"),
                    },
                    "created_at": _utc_now_iso(),
                }
            )
        if current_state == report["state"]:
            if updates:
                updates["updated_at"] = _utc_now_iso()
                updated_order = self.repository.update_order(internal_order_id, updates)
                return {
                    "order": updated_order,
                    "changed": True,
                    "absorbed": False,
                }
            return {"order": current_order, "changed": False, "absorbed": False}
        if absorbed:
            if updates:
                updates["updated_at"] = _utc_now_iso()
                current_order = self.repository.update_order(internal_order_id, updates)
            return {"order": current_order, "changed": False, "absorbed": True}
        now = _utc_now_iso()

        updated_order = self.repository.update_order(
            internal_order_id,
            {
                "state": next_state,
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
        return {"order": updated_order, "changed": True, "absorbed": False}

    def ingest_trade_report(self, report):
        return self.ingest_trade_report_with_meta(report)["trade_fact"]

    def ingest_trade_report_with_meta(self, report):
        report = _normalize_trade_report_identity(report)
        current_order = self.repository.find_order(report["internal_order_id"])
        created_broker_only = current_order is None
        if current_order is None:
            current_order = self._build_broker_only_order(report)
        else:
            _assert_order_report_identity(current_order, report)

        placeholder_key = (
            current_order.get("broker_order_key") or current_order["internal_order_id"]
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
        execution_identity = _resolve_execution_identity(
            report, current_order=effective_order
        )
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
        }
        if created_broker_only:
            self.repository.insert_order(effective_order)
        # #571：broker 聚合占位状态不再无条件 PARTIAL_FILLED —— 终态内部订单
        # 保持终态，避免卡死单永久占用买入容量；成交事实仍照常落账。
        placeholder_state, _ = self.order_state.apply_fill_aggregate_state(
            current_order["state"],
            next_quantity=0,
            requested_quantity=None,
        )
        self._sync_broker_order_report(
            broker_order_key,
            {**report, "state": placeholder_state},
            current_order=effective_order,
            placeholder_key=placeholder_key,
        )
        self.repository.fence_broker_order_execution(execution_fill)
        saved_trade_fact, created = self.repository.upsert_trade_fact(
            trade_fact,
            unique_keys=["execution_identity"],
        )
        saved_execution_fill, created_execution_fill = (
            self.repository.upsert_execution_fill(
                execution_fill,
                unique_keys=["execution_identity"],
            )
        )
        _assert_execution_replay_consistent(saved_trade_fact, trade_fact)
        _assert_execution_replay_consistent(saved_execution_fill, execution_fill)
        if not created_broker_only and identity_updates:
            current_order = self.repository.update_order(
                report["internal_order_id"],
                {**identity_updates, "updated_at": _utc_now_iso()},
            )
        else:
            current_order = effective_order
        created = bool(created_execution_fill)
        broker_order = None
        late_trade_alert = False
        if created:
            broker_order, late_trade_alert = self._apply_fill_to_broker_order(
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
                    "state": (broker_order or {}).get("state", placeholder_state),
                    "created_at": _utc_now_iso(),
                }
            )
            if late_trade_alert:
                self.repository.insert_order_event(
                    {
                        "event_id": new_event_id(),
                        "request_id": current_order.get("request_id"),
                        "internal_order_id": report["internal_order_id"],
                        "event_type": LATE_TRADE_EVENT_TYPE,
                        "state": current_order.get("state"),
                        "payload": {
                            "broker_trade_id": report.get("broker_trade_id"),
                            "quantity": report.get("quantity"),
                            "price": report.get("price"),
                        },
                        "created_at": _utc_now_iso(),
                    }
                )
        return {
            "trade_fact": saved_trade_fact,
            "execution_fill": saved_execution_fill,
            "created": created,
            "late_trade_alert": late_trade_alert,
        }

    def _build_broker_only_order(self, report):
        expected_internal_order_id = build_broker_only_internal_order_id(
            account_id=report.get("account_id"),
            order_sysid=report.get("order_sysid"),
            trading_day=resolve_trading_day(report),
            symbol=report.get("symbol"),
            side=report.get("side"),
            broker_order_id=report.get("broker_order_id"),
        )
        reported_internal_order_id = normalize_identifier(
            report.get("internal_order_id")
        )
        if (
            reported_internal_order_id is not None
            and reported_internal_order_id != expected_internal_order_id
        ):
            raise BrokerIdentityConflict(
                "broker-only internal_order_id is not deterministic"
            )
        now = _utc_now_iso()
        reported_state = str(report.get("state") or "").strip().upper()
        if reported_state:
            initial_state = reported_state
        else:
            # #571：trade-only broker-only 单无显式状态时，初始状态由
            # OrderStateService 推导（非终态 + 无 request 基数 → PARTIAL_FILLED），
            # 不再字面硬编码。
            initial_state = self.order_state.apply_fill_aggregate_state(
                None,
                next_quantity=0,
                requested_quantity=report.get("requested_quantity")
                or report.get("order_volume"),
            )[0]
        return {
            "internal_order_id": expected_internal_order_id,
            "request_id": None,
            "broker_order_key": _resolve_broker_order_key(report),
            "broker_order_id": normalize_identifier(report.get("broker_order_id")),
            "broker_order_type": report.get("broker_order_type")
            or report.get("order_type"),
            "account_type": report.get("account_type"),
            "account_id": normalize_account_id(report.get("account_id")),
            "order_sysid": normalize_identifier(report.get("order_sysid")),
            "trading_day": resolve_trading_day(report),
            "trace_id": report.get("trace_id"),
            "intent_id": report.get("intent_id"),
            "symbol": normalize_symbol(report.get("symbol")),
            "side": normalize_side(report.get("side")),
            "state": initial_state,
            "source_type": "broker_only",
            "submitted_at": report.get("submitted_at"),
            "requested_quantity": report.get("requested_quantity")
            or report.get("order_volume"),
            "avg_filled_price": None,
            "created_at": now,
            "updated_at": now,
        }

    def _sync_broker_order_report(
        self,
        broker_order_key,
        report,
        *,
        current_order=None,
        placeholder_key=None,
    ):
        current_order = current_order or self.repository.find_order(
            report.get("internal_order_id") or broker_order_key
        )
        if current_order is None:
            raise BrokerIdentityConflict("broker order owner is required")
        claim = _broker_order_owner_claim(
            {**current_order, "broker_order_key": broker_order_key}
        )
        placeholder_key = normalize_identifier(
            placeholder_key
            or current_order.get("broker_order_key")
            or current_order.get("internal_order_id")
        )
        if placeholder_key and placeholder_key != broker_order_key:
            self.repository.move_broker_order_key(
                placeholder_key,
                broker_order_key,
                claim,
            )
        else:
            self.repository.claim_broker_order_owner(claim)
        broker_order = self.repository.find_broker_order(broker_order_key)
        if broker_order is None:
            raise BrokerIdentityConflict("broker order claim did not persist")
        updates = {
            "state": report.get("state") or broker_order.get("state"),
            "broker_order_id": report.get("broker_order_id")
            or broker_order.get("broker_order_id"),
            # #597：submitted_at 统一归一为 UTC ISO 后再比较/写入。XT 回调路径
            # （_xt_timestamp_to_datetime）产出北京时间无时区字符串，place_order
            # 路径产出 UTC ISO（+00:00），同一时刻两种格式会在终态订单重复回报
            # 时产生伪差异，触发 om_broker_orders.updated_at 无痕刷新。
            "submitted_at": _normalize_submitted_at(
                report.get("submitted_at") or broker_order.get("submitted_at")
            ),
            "requested_quantity": report.get("requested_quantity")
            or report.get("order_volume")
            or broker_order.get("requested_quantity"),
        }
        update_fields = {}
        for key, value in updates.items():
            if value is None:
                continue
            current_value = broker_order.get(key)
            if key == "submitted_at":
                # #597：submitted_at 用时刻比较（归秒，忽略微秒/时区字符串差异）
                if not _same_submitted_at_instant(current_value, value):
                    update_fields[key] = value
            elif current_value != value:
                update_fields[key] = value
        if not update_fields:
            return broker_order
        update_fields["updated_at"] = _utc_now_iso()
        return self.repository.update_broker_order_fields(
            broker_order_key,
            update_fields,
        )

    def _apply_fill_to_broker_order(
        self, broker_order_key, execution_fill, *, current_order
    ):
        for _attempt in range(8):
            broker_order = self.repository.find_broker_order(broker_order_key)
            if broker_order is None:
                raise BrokerIdentityConflict("execution fence has no broker order")
            conflicts = identity_conflicts(broker_order, execution_fill)
            if conflicts:
                raise BrokerIdentityConflict(
                    "execution fill conflicts with broker aggregate: "
                    + ", ".join(sorted(conflicts))
                )
            fills = _list_broker_execution_fills(
                self.repository,
                broker_order_key=broker_order_key,
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
            # #571 OrderStateService：终态订单成交不回退状态（事实照落+告警）。
            next_state, late_trade_alert = self.order_state.apply_fill_aggregate_state(
                current_order.get("state"),
                next_quantity=next_quantity,
                requested_quantity=requested_quantity,
            )
            next_document = {
                **broker_order,
                "filled_quantity": next_quantity,
                "avg_filled_price": next_avg_price,
                "fill_count": next_fill_count,
                "aggregate_revision": int(broker_order.get("aggregate_revision") or 0)
                + 1,
                "first_fill_time": first_fill_time,
                "last_fill_time": last_fill_time,
                "state": next_state,
                "updated_at": _utc_now_iso(),
            }
            saved_broker_order = self.repository.compare_and_set_broker_order(
                before=broker_order,
                after=next_document,
            )
            if saved_broker_order is not None:
                return saved_broker_order, late_trade_alert
        raise BrokerIdentityConflict(
            "broker aggregate could not converge after concurrent updates"
        )


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_submitted_at(value):
    """把 submitted_at 归一为 UTC ISO，用于跨路径一致比较与写入（#597）。

    - 带时区 ISO：转为 UTC ISO；
    - 无时区 ISO：按 Asia/Shanghai（XT 回报语义）解释后转 UTC ISO；
    - 无法解析：保留原样（不猜测）。
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(timezone.utc).isoformat()


def _submitted_at_instant(value):
    """把 submitted_at 解析为 aware UTC datetime 用于同一时刻比较（#597）。

    与 ``_normalize_submitted_at`` 的区别：比较语义忽略字符串表示差异
    （如微秒有无、时区写法），只比时刻；无法解析返回 None。
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(timezone.utc)


def _same_submitted_at_instant(left, right):
    """submitted_at 是否同一时刻（归秒比较，忽略微秒与时区字符串差异）。"""

    left_instant = _submitted_at_instant(left)
    right_instant = _submitted_at_instant(right)
    if left_instant is None or right_instant is None:
        return False
    return left_instant.replace(microsecond=0) == right_instant.replace(microsecond=0)


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
    if normalized["broker_trade_id"] is None:
        raise BrokerIdentityError("broker_trade_id is required")
    if normalized["symbol"] is None:
        raise BrokerIdentityError("trade symbol is required")
    if normalized["side"] is None:
        raise BrokerIdentityError("unknown broker order side")
    try:
        quantity = int(report.get("quantity"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise BrokerIdentityError(
            "execution quantity must be a positive integer"
        ) from exc
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
    normalized["broker_order_key"] = _resolve_broker_order_key(normalized)
    return normalized


def _resolve_execution_identity(report, *, current_order):
    existing = normalize_identifier(report.get("execution_identity"))
    if existing is not None:
        return existing
    try:
        return build_execution_identity(report)
    except BrokerIdentityError:
        internal_order_id = normalize_identifier(
            (current_order or {}).get("internal_order_id")
            or report.get("internal_order_id")
        )
        broker_trade_id = normalize_identifier(report.get("broker_trade_id"))
        if (
            internal_order_id is None
            or broker_trade_id is None
            or str((current_order or {}).get("source_type") or "").lower()
            == "broker_only"
        ):
            raise
        raw = f"{internal_order_id}|{broker_trade_id}"
        return f"internal-execution:{sha256(raw.encode('utf-8')).hexdigest()}"


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


def _broker_order_owner_claim(order):
    source_type = str(order.get("source_type") or "").strip() or "unknown"
    broker_only = source_type.lower() == "broker_only"
    return {
        "broker_order_key": normalize_identifier(order.get("broker_order_key")),
        "internal_order_id": normalize_identifier(order.get("internal_order_id")),
        "request_id": (
            None if broker_only else normalize_identifier(order.get("request_id"))
        ),
        "broker_correlation_token": (
            None
            if broker_only
            else normalize_broker_correlation_token(
                order.get("broker_correlation_token")
            )
        ),
        "account_id": normalize_account_id(order.get("account_id")),
        "trading_day": resolve_trading_day(order),
        "order_sysid": normalize_identifier(order.get("order_sysid")),
        "broker_order_id": normalize_identifier(order.get("broker_order_id")),
        "symbol": normalize_symbol(order.get("symbol")),
        "side": normalize_side(order.get("side")),
        "source_type": source_type,
    }


def _assert_order_report_identity(current_order, report):
    report_identity = _non_empty_identity_fields(report)
    conflicts = identity_conflicts(current_order, report_identity)
    current_token = normalize_broker_correlation_token(
        current_order.get("broker_correlation_token")
    )
    report_token = normalize_broker_correlation_token(
        report_identity.get("broker_correlation_token")
    )
    if current_token and report_token and current_token != report_token:
        conflicts["broker_correlation_token"] = (current_token, report_token)
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


def _list_broker_execution_fills(repository, *, broker_order_key):
    fills = repository.list_execution_fills(broker_order_keys=[broker_order_key])
    deduplicated = {}
    for fill in fills:
        key = fill.get("execution_identity") or fill.get("execution_fill_id")
        deduplicated[key] = fill
    return list(deduplicated.values())


def _fill_time_bounds(fills):
    values = [
        fill.get("trade_time") for fill in fills if fill.get("trade_time") is not None
    ]
    if not values:
        return None, None
    return min(values), max(values)
