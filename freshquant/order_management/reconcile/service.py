# -*- coding: utf-8 -*-

import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from freshquant.order_management.ids import (
    new_candidate_id,
    new_event_id,
    new_internal_order_id,
    new_request_id,
)
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
    _default_grid_interval_lookup,
    _resolve_lot_amount,
    normalize_xt_trade_report,
)
from freshquant.order_management.reconcile.matcher import match_candidate_to_trade
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    mark_exception_emitted,
)
from freshquant.runtime_observability.logger import RuntimeEventLogger


@dataclass
class TradeReportReconcileOutcome:
    handled: bool
    action: str
    result: dict | None = None
    normalized: dict | None = None


class ExternalOrderReconcileService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        ingest_service=None,
        external_confirm_interval_seconds=15,
        external_confirm_observations=3,
        runtime_logger=None,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.ingest_service = ingest_service or OrderManagementXtIngestService(
            repository=self.repository,
            tracking_service=self.tracking_service,
        )
        self.external_confirm_interval_seconds = max(
            int(external_confirm_interval_seconds or 15), 1
        )
        self.external_confirm_observations = max(
            int(external_confirm_observations or 3), 1
        )
        self.runtime_logger = runtime_logger or _get_runtime_logger()

    def detect_external_candidates(self, positions, detected_at):
        positions_by_symbol = _build_positions_by_symbol(positions)
        internal_by_symbol = _build_internal_remaining_by_symbol(
            self.repository.list_buy_lots()
        )
        pending_candidates = self.repository.list_external_candidates(
            "INFERRED_PENDING"
        )
        pending_index = _index_pending_candidates_by_symbol_side(pending_candidates)
        created = []
        observed_keys = set()
        current_deltas = []

        for symbol in sorted(set(positions_by_symbol) | set(internal_by_symbol)):
            position = positions_by_symbol.get(symbol, {})
            external_quantity = int(position.get("volume", 0) or 0)
            internal_quantity = int(internal_by_symbol.get(symbol, 0))
            delta = external_quantity - internal_quantity
            if delta == 0:
                continue
            side = "buy" if delta > 0 else "sell"
            quantity_delta = abs(delta)
            price_snapshot = _resolve_inferred_price_snapshot(
                symbol,
                position,
                detected_at=int(detected_at),
            )
            current_deltas.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "quantity_delta": quantity_delta,
                    **price_snapshot,
                }
            )

        current_index = {
            (item["symbol"], item["side"]): item for item in current_deltas
        }
        for key, candidate in pending_index.items():
            observed = current_index.get(key)
            if observed is None:
                self.repository.update_external_candidate(
                    candidate["candidate_id"],
                    {
                        "state": "INFERRED_DISMISSED",
                        "dismissed_at": int(detected_at),
                        "dismissed_reason": "position_delta_resolved",
                    },
                )
                continue
            observed_keys.add(key)
            updates = _build_candidate_observation_updates(
                candidate,
                observed=observed,
                detected_at=int(detected_at),
                confirm_interval_seconds=self.external_confirm_interval_seconds,
                confirm_observations=self.external_confirm_observations,
            )
            self.repository.update_external_candidate(
                candidate["candidate_id"],
                updates,
            )

        for item in current_deltas:
            key = (item["symbol"], item["side"])
            if key in observed_keys:
                continue
            candidate = {
                "candidate_id": new_candidate_id(),
                "symbol": item["symbol"],
                "side": item["side"],
                "quantity_delta": item["quantity_delta"],
                "price_estimate": item["price_estimate"],
                "price_source": item.get("price_source"),
                "price_asof": item.get("price_asof"),
                "detected_at": int(detected_at),
                "first_detected_at": int(detected_at),
                "last_detected_at": int(detected_at),
                "observed_count": 1,
                "pending_until": _pending_until_for_observation(
                    detected_at=int(detected_at),
                    observed_count=1,
                    confirm_interval_seconds=self.external_confirm_interval_seconds,
                    confirm_observations=self.external_confirm_observations,
                ),
                "state": "INFERRED_PENDING",
                "source": "position_diff",
                "matched_order_id": None,
                "matched_trade_fact_id": None,
            }
            self.repository.insert_external_candidate(candidate)
            created.append(candidate)
        return created

    def reconcile_trade_reports(self, trade_reports):
        results = []
        pending_candidates = self.repository.list_external_candidates(
            "INFERRED_PENDING"
        )
        for report in trade_reports:
            outcome = self.reconcile_trade_report(
                report,
                pending_candidates=pending_candidates,
            )
            if outcome.result is not None:
                results.append(outcome.result)
        return results

    def reconcile_trade_report(self, report, pending_candidates=None):
        current_node = "internal_match"
        ids = {
            "trace_id": report.get("trace_id"),
            "intent_id": report.get("intent_id"),
            "request_id": report.get("request_id"),
            "internal_order_id": report.get("internal_order_id"),
            "symbol": report.get("symbol"),
        }
        try:
            normalized = normalize_xt_trade_report(
                report,
                repository=self.repository,
            )
            ids["symbol"] = normalized.get("symbol")
            if self.repository.find_order_by_broker_order_id(
                normalized.get("broker_order_id")
            ):
                return TradeReportReconcileOutcome(
                    handled=True,
                    action="already_known_internal_order",
                    normalized=normalized,
                )

            match_status, matched_order = self._match_inflight_internal_order(
                normalized
            )
            if match_status == "matched":
                ids.update(
                    {
                        "trace_id": matched_order.get("trace_id"),
                        "intent_id": matched_order.get("intent_id"),
                        "request_id": matched_order.get("request_id"),
                        "internal_order_id": matched_order["internal_order_id"],
                        "symbol": normalized["symbol"],
                    }
                )
                self._emit_runtime(
                    "internal_match",
                    ids,
                    payload={"broker_order_id": normalized.get("broker_order_id")},
                )
                normalized["internal_order_id"] = matched_order["internal_order_id"]
                if normalized.get("broker_order_id") and not matched_order.get(
                    "broker_order_id"
                ):
                    self.repository.update_order(
                        matched_order["internal_order_id"],
                        {
                            "broker_order_id": normalized.get("broker_order_id"),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                current_node = "projection_update"
                result = self.ingest_service.ingest_trade_report(
                    normalized,
                    lot_amount=_safe_resolve_lot_amount(normalized["symbol"]),
                    grid_interval_lookup=_safe_grid_interval_lookup,
                )
                self._emit_runtime(
                    "projection_update",
                    ids,
                    payload={"source": "internal_match"},
                )
                return TradeReportReconcileOutcome(
                    handled=True,
                    action="matched_internal_order",
                    result=result,
                    normalized=normalized,
                )
            if match_status == "defer":
                return TradeReportReconcileOutcome(
                    handled=True,
                    action="deferred_ambiguous_internal_match",
                    normalized=normalized,
                )

            if pending_candidates is None:
                pending_candidates = self.repository.list_external_candidates(
                    "INFERRED_PENDING"
                )
            candidate = _find_trade_candidate(pending_candidates, normalized)
            current_node = "externalize"
            order = self._create_external_order(
                symbol=normalized["symbol"],
                side=normalized["side"],
                quantity=normalized["quantity"],
                price=normalized["price"],
                source_type="external_reported",
                state="FILLED",
                broker_order_id=normalized.get("broker_order_id"),
            )
            ids = {
                "request_id": order["request_id"],
                "internal_order_id": order["internal_order_id"],
                "symbol": normalized["symbol"],
            }
            self._emit_runtime(
                "externalize",
                ids,
                payload={"source_type": "external_reported"},
            )
            normalized["internal_order_id"] = order["internal_order_id"]
            normalized["source"] = "external_reported"
            current_node = "projection_update"
            result = self.ingest_service.ingest_trade_report(
                normalized,
                lot_amount=_safe_resolve_lot_amount(normalized["symbol"]),
                grid_interval_lookup=_safe_grid_interval_lookup,
            )
            if candidate is not None:
                candidate_updates = _build_candidate_trade_updates(
                    candidate,
                    normalized_trade=normalized,
                    order=order,
                    trade_fact=result["trade_fact"],
                )
                candidate.update(candidate_updates)
                self.repository.update_external_candidate(
                    candidate["candidate_id"],
                    candidate_updates,
                )
            self._emit_runtime(
                "projection_update",
                ids,
                payload={"source": "external_reported"},
            )
            return TradeReportReconcileOutcome(
                handled=True,
                action="externalized_report",
                result=result,
                normalized=normalized,
            )
        except Exception as exc:
            self._emit_runtime(
                current_node,
                ids,
                status="error",
                reason_code="unexpected_exception",
                payload=build_exception_payload(exc),
            )
            mark_exception_emitted(exc)
            raise

    def _match_inflight_internal_order(self, normalized_trade):
        candidates = []
        for order in self.repository.list_orders(
            symbol=normalized_trade["symbol"],
            states={"ACCEPTED", "QUEUED", "SUBMITTING"},
            missing_broker_only=True,
        ):
            if order.get("side") != normalized_trade["side"]:
                continue
            if order.get("source_type") in {"external_reported", "external_inferred"}:
                continue
            request = self.repository.find_order_request(order["request_id"])
            if request is None:
                continue
            if int(request.get("quantity") or 0) != int(normalized_trade["quantity"]):
                continue
            request_price = request.get("price")
            if (
                request_price is not None
                and abs(float(request_price) - float(normalized_trade["price"])) > 1e-6
            ):
                continue
            candidates.append(order)

        if len(candidates) == 1:
            return "matched", candidates[0]
        if len(candidates) > 1:
            return "defer", None
        return "missing", None

    def confirm_expired_candidates(self, now):
        confirmed = []
        for candidate in self.repository.list_external_candidates("INFERRED_PENDING"):
            if int(candidate.get("observed_count") or 1) < int(
                self.external_confirm_observations
            ):
                continue
            if int(candidate["pending_until"]) > int(now):
                continue
            current_node = "externalize"
            ids = {"symbol": candidate["symbol"]}
            try:
                order = self._create_external_order(
                    symbol=candidate["symbol"],
                    side=candidate["side"],
                    quantity=candidate["quantity_delta"],
                    price=candidate.get("price_estimate") or 0.0,
                    source_type="external_inferred",
                    state="INFERRED_CONFIRMED",
                    broker_order_id=None,
                )
                ids = {
                    "request_id": order["request_id"],
                    "internal_order_id": order["internal_order_id"],
                    "symbol": candidate["symbol"],
                }
                self._emit_runtime(
                    "externalize",
                    ids,
                    payload={"source_type": "external_inferred"},
                )
                trade_report = _build_inferred_trade_report(
                    candidate, order["internal_order_id"]
                )
                current_node = "projection_update"
                result = self.ingest_service.ingest_trade_report(
                    trade_report,
                    lot_amount=_safe_resolve_lot_amount(candidate["symbol"]),
                    grid_interval_lookup=_safe_grid_interval_lookup,
                )
                updated_candidate = self.repository.update_external_candidate(
                    candidate["candidate_id"],
                    {
                        "state": "INFERRED_CONFIRMED",
                        "matched_order_id": order["internal_order_id"],
                        "matched_trade_fact_id": result["trade_fact"]["trade_fact_id"],
                        "confirmed_at": int(now),
                    },
                )
                self._emit_runtime(
                    "projection_update",
                    ids,
                    payload={"source": "external_inferred"},
                )
                confirmed.append(updated_candidate)
            except Exception as exc:
                self._emit_runtime(
                    current_node,
                    ids,
                    status="error",
                    reason_code="unexpected_exception",
                    payload=build_exception_payload(exc),
                )
                mark_exception_emitted(exc)
                raise
        return confirmed

    def reconcile_account(self, account_id, positions=None, xt_trades=None, now=None):
        detected = []
        matched = []
        confirmed = []
        if positions is not None and now is not None:
            detected = self.detect_external_candidates(positions, detected_at=now)
        if xt_trades:
            matched = self.reconcile_trade_reports(xt_trades)
        if now is not None:
            confirmed = self.confirm_expired_candidates(now=now)
        return {
            "account_id": account_id,
            "detected_candidates": detected,
            "matched_reports": matched,
            "confirmed_candidates": confirmed,
        }

    def _create_external_order(
        self,
        symbol,
        side,
        quantity,
        price,
        source_type,
        state,
        broker_order_id,
    ):
        request_id = new_request_id()
        internal_order_id = new_internal_order_id()
        now_iso = datetime.now(timezone.utc).isoformat()
        self.repository.insert_order_request(
            {
                "request_id": request_id,
                "action": side,
                "source": source_type,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "strategy_name": None,
                "remark": source_type,
                "scope_type": None,
                "scope_ref_id": None,
                "req_id": request_id,
                "state": state,
                "created_at": now_iso,
            }
        )
        order = {
            "internal_order_id": internal_order_id,
            "request_id": request_id,
            "broker_order_id": (
                str(broker_order_id) if broker_order_id is not None else None
            ),
            "symbol": symbol,
            "side": side,
            "state": state,
            "source_type": source_type,
            "submitted_at": now_iso,
            "filled_quantity": quantity,
            "avg_filled_price": price,
            "updated_at": now_iso,
        }
        self.repository.insert_order(order)
        self.repository.insert_order_event(
            {
                "event_id": new_event_id(),
                "request_id": request_id,
                "internal_order_id": internal_order_id,
                "event_type": "external_reconciled",
                "state": state,
                "created_at": now_iso,
            }
        )
        return order

    def _emit_runtime(self, node, ids, *, status="info", reason_code="", payload=None):
        event = {
            "component": "order_reconcile",
            "node": node,
            "trace_id": ids.get("trace_id"),
            "intent_id": ids.get("intent_id"),
            "request_id": ids.get("request_id"),
            "internal_order_id": ids.get("internal_order_id"),
            "symbol": ids.get("symbol"),
            "status": status,
            "reason_code": reason_code,
            "payload": dict(payload or {}),
        }
        try:
            self.runtime_logger.emit(event)
        except Exception:
            return


def _build_positions_by_symbol(positions):
    result = {}
    for item in positions:
        stock_code = item.get("stock_code", "")
        symbol = item.get("symbol") or stock_code[:6]
        result[symbol] = item
    return result


def _build_internal_remaining_by_symbol(buy_lots):
    result = {}
    for item in buy_lots:
        result[item["symbol"]] = result.get(item["symbol"], 0) + int(
            item.get("remaining_quantity", 0)
        )
    return result


def _find_pending_candidate(candidates, symbol, side, quantity_delta):
    for item in candidates:
        if (
            item["symbol"] == symbol
            and item["side"] == side
            and int(item["quantity_delta"]) == int(quantity_delta)
        ):
            return item
    return None


def _index_pending_candidates_by_symbol_side(candidates):
    indexed = {}
    for item in list(candidates or []):
        key = (item.get("symbol"), item.get("side"))
        if not all(key):
            continue
        indexed[key] = item
    return indexed


def _find_trade_candidate(candidates, normalized_trade):
    exact_matches = [
        item
        for item in candidates
        if item.get("state") == "INFERRED_PENDING"
        and match_candidate_to_trade(item, normalized_trade)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    partial_matches = [
        item
        for item in candidates
        if item.get("state") == "INFERRED_PENDING"
        and match_candidate_to_trade(item, normalized_trade, allow_partial=True)
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]
    return None


def _build_candidate_trade_updates(candidate, *, normalized_trade, order, trade_fact):
    remaining_quantity = int(candidate.get("quantity_delta") or 0) - int(
        normalized_trade["quantity"]
    )
    if remaining_quantity <= 0:
        return {
            "state": "MATCHED",
            "quantity_delta": 0,
            "matched_order_id": order["internal_order_id"],
            "matched_trade_fact_id": trade_fact["trade_fact_id"],
        }
    return {
        "quantity_delta": remaining_quantity,
    }


def _build_candidate_observation_updates(
    candidate,
    *,
    observed,
    detected_at,
    confirm_interval_seconds,
    confirm_observations,
):
    current_quantity = int(candidate.get("quantity_delta") or 0)
    observed_quantity = int(observed.get("quantity_delta") or 0)
    last_detected_at = int(
        candidate.get("last_detected_at") or candidate.get("detected_at") or 0
    )
    observed_count = int(candidate.get("observed_count") or 1)
    if observed_quantity != current_quantity:
        observed_count = 1
    elif int(detected_at) > last_detected_at:
        observed_count += 1
    first_detected_at = int(
        candidate.get("first_detected_at")
        or candidate.get("detected_at")
        or detected_at
    )
    if observed_quantity != current_quantity:
        resolved_price = _select_preferred_price_snapshot(None, observed)
    else:
        resolved_price = _select_preferred_price_snapshot(candidate, observed)
    return {
        "quantity_delta": observed_quantity,
        **resolved_price,
        "first_detected_at": first_detected_at,
        "last_detected_at": int(detected_at),
        "observed_count": observed_count,
        "pending_until": _pending_until_for_observation(
            detected_at=int(detected_at),
            observed_count=observed_count,
            confirm_interval_seconds=confirm_interval_seconds,
            confirm_observations=confirm_observations,
        ),
    }


def _pending_until_for_observation(
    *,
    detected_at,
    observed_count,
    confirm_interval_seconds,
    confirm_observations,
):
    remaining_observations = max(
        int(confirm_observations) - int(observed_count),
        0,
    )
    return int(detected_at) + remaining_observations * int(confirm_interval_seconds)


def _build_inferred_trade_report(candidate, internal_order_id):
    trade_time = int(candidate["pending_until"])
    trade_datetime = datetime.fromtimestamp(trade_time)
    return {
        "internal_order_id": internal_order_id,
        "broker_order_id": None,
        "broker_trade_id": f"inferred::{candidate['candidate_id']}",
        "symbol": candidate["symbol"],
        "side": candidate["side"],
        "quantity": candidate["quantity_delta"],
        "price": candidate.get("price_estimate") or 0.0,
        "trade_time": trade_time,
        "date": int(trade_datetime.strftime("%Y%m%d")),
        "time": trade_datetime.strftime("%H:%M:%S"),
        "source": "external_inferred",
        "provisional": True,
    }


_PRICE_SOURCE_PRIORITY = {
    "position_last_price": 10,
    "position_market_value": 20,
    "realtime_bar_close": 30,
    "previous_close": 40,
    "position_avg_price": 50,
    "position_open_price": 60,
    "missing": 999,
}
_MONGO_PROBE_TTL_SECONDS = 5.0
_mongo_probe_cache: dict[tuple[str, int], tuple[float, bool]] = {}


def _resolve_inferred_price_snapshot(symbol, position, *, detected_at):
    detected_at = int(detected_at or 0)

    snapshot = _build_position_price_snapshot(position, detected_at)
    if snapshot is not None:
        return snapshot

    snapshot = _load_latest_realtime_price_snapshot(symbol, position)
    if snapshot is not None:
        return snapshot

    snapshot = _load_previous_close_price_snapshot(symbol, detected_at)
    if snapshot is not None:
        return snapshot

    snapshot = _build_legacy_position_price_snapshot(position, detected_at)
    if snapshot is not None:
        return snapshot

    return {
        "price_estimate": 0.0,
        "price_source": "missing",
        "price_asof": detected_at or None,
    }


def _build_position_price_snapshot(position, detected_at):
    price = _safe_positive_float(position.get("last_price"))
    if price is not None:
        return _make_price_snapshot(
            price,
            source="position_last_price",
            asof=detected_at,
        )

    volume = int(position.get("volume") or 0)
    market_value = _safe_positive_float(position.get("market_value"))
    if market_value is not None and volume > 0:
        return _make_price_snapshot(
            market_value / volume,
            source="position_market_value",
            asof=detected_at,
        )
    return None


def _build_legacy_position_price_snapshot(position, detected_at):
    price = _safe_positive_float(position.get("avg_price"))
    if price is not None:
        return _make_price_snapshot(
            price,
            source="position_avg_price",
            asof=detected_at,
        )

    price = _safe_positive_float(position.get("open_price"))
    if price is not None:
        return _make_price_snapshot(
            price,
            source="position_open_price",
            asof=detected_at,
        )
    return None


def _load_latest_realtime_price_snapshot(symbol, position):
    try:
        import pymongo
        from fqxtrade.database.mongodb import DBfreshquant

        from freshquant.market_data.xtdata.schema import normalize_prefixed_code
    except Exception:
        return None

    try:
        client = getattr(DBfreshquant, "client", None)
        if client is None or not _can_query_mongo(client):
            return None
        raw_code = position.get("stock_code") or position.get("symbol") or symbol
        code = normalize_prefixed_code(raw_code)
        if not code:
            return None

        intraday_freqs = ["1min", "5min", "15min", "30min", "60min"]
        for collection_name in ("stock_realtime", "index_realtime"):
            document = DBfreshquant[collection_name].find_one(
                {
                    "code": code,
                    "frequence": {"$in": intraday_freqs},
                    "close": {"$gt": 0},
                },
                sort=[("datetime", pymongo.DESCENDING)],
            )
            if document is not None:
                return _make_price_snapshot(
                    document.get("close"),
                    source="realtime_bar_close",
                    asof=_coerce_timestamp(document.get("datetime")),
                )
    except Exception:
        return None
    return None


def _load_previous_close_price_snapshot(symbol, detected_at):
    return _load_previous_close_from_realtime(symbol, detected_at)


def _load_previous_close_from_realtime(symbol, detected_at):
    try:
        import pymongo
        from fqxtrade.database.mongodb import DBfreshquant

        from freshquant.market_data.xtdata.schema import normalize_prefixed_code
    except Exception:
        return None

    try:
        client = getattr(DBfreshquant, "client", None)
        if client is None or not _can_query_mongo(client):
            return None
        code = normalize_prefixed_code(symbol)
        if not code:
            return None

        day_start = datetime.fromtimestamp(int(detected_at)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        for collection_name in ("stock_realtime", "index_realtime"):
            document = DBfreshquant[collection_name].find_one(
                {
                    "code": code,
                    "frequence": "1d",
                    "datetime": {"$lt": day_start},
                    "close": {"$gt": 0},
                },
                sort=[("datetime", pymongo.DESCENDING)],
            )
            if document is not None:
                return _make_price_snapshot(
                    document.get("close"),
                    source="previous_close",
                    asof=_coerce_timestamp(document.get("datetime")),
                )
    except Exception:
        return None
    return None


def _select_preferred_price_snapshot(current, observed):
    observed_snapshot = _normalize_price_snapshot(observed)
    current_snapshot = _normalize_price_snapshot(current)
    if observed_snapshot is None:
        return current_snapshot or {
            "price_estimate": 0.0,
            "price_source": "missing",
            "price_asof": None,
        }
    if current_snapshot is None:
        return observed_snapshot

    current_priority = _PRICE_SOURCE_PRIORITY.get(
        current_snapshot.get("price_source") or "missing",
        999,
    )
    observed_priority = _PRICE_SOURCE_PRIORITY.get(
        observed_snapshot.get("price_source") or "missing",
        999,
    )
    if observed_priority < current_priority:
        return observed_snapshot
    if observed_priority > current_priority:
        return current_snapshot

    current_asof = int(current_snapshot.get("price_asof") or 0)
    observed_asof = int(observed_snapshot.get("price_asof") or 0)
    if observed_asof >= current_asof:
        return observed_snapshot
    return current_snapshot


def _normalize_price_snapshot(payload):
    if payload is None:
        return None
    return _make_price_snapshot(
        payload.get("price_estimate"),
        source=payload.get("price_source"),
        asof=payload.get("price_asof"),
    )


def _make_price_snapshot(price, *, source, asof):
    parsed_price = _safe_positive_float(price)
    if parsed_price is None:
        return None
    return {
        "price_estimate": parsed_price,
        "price_source": str(source or "").strip() or "missing",
        "price_asof": _coerce_timestamp(asof),
    }


def _safe_positive_float(value):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _coerce_timestamp(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    return None


def _can_query_mongo(client):
    try:
        seeds = list(getattr(client, "_topology_settings").seeds or [])
    except Exception:
        return True
    if not seeds:
        return True

    now = time.time()
    any_reachable = False
    for host, port in seeds:
        cache_key = (host, int(port))
        cached = _mongo_probe_cache.get(cache_key)
        if cached is not None and (now - cached[0]) < _MONGO_PROBE_TTL_SECONDS:
            if cached[1]:
                return True
            continue
        reachable = _probe_socket(host, int(port))
        _mongo_probe_cache[cache_key] = (now, reachable)
        any_reachable = any_reachable or reachable
    return any_reachable


def _probe_socket(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False


def _safe_resolve_lot_amount(symbol):
    try:
        return _resolve_lot_amount(symbol)
    except Exception as exc:
        raise RuntimeError(
            f"lot amount unavailable for external reconcile: {symbol}"
        ) from exc


def _safe_grid_interval_lookup(symbol, trade_fact):
    try:
        return _default_grid_interval_lookup(symbol, trade_fact)
    except Exception as exc:
        raise RuntimeError(
            f"grid interval unavailable for external reconcile: {symbol}"
        ) from exc


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("order_reconcile")
    return _runtime_logger
