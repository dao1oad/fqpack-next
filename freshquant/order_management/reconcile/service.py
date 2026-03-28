# -*- coding: utf-8 -*-

from dataclasses import dataclass
from datetime import datetime, timezone

from freshquant.order_management.ids import (
    new_allocation_id,
    new_event_id,
    new_entry_slice_id,
    new_internal_order_id,
    new_position_entry_id,
    new_reconciliation_gap_id,
    new_reconciliation_resolution_id,
    new_request_id,
)
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
    _default_grid_interval_lookup,
    normalize_xt_trade_report,
)
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_slices,
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
        internal_by_symbol = _build_internal_remaining_by_symbol(self.repository)
        pending_gaps = list(self.repository.list_reconciliation_gaps(state="OPEN"))
        pending_gaps.extend(self.repository.list_reconciliation_gaps(state="REJECTED"))
        pending_index = _index_pending_gaps_by_symbol_side(pending_gaps)
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
            current_deltas.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "quantity_delta": quantity_delta,
                    "price_estimate": position.get("avg_price")
                    or position.get("open_price")
                    or 0.0,
                }
            )

        current_index = {
            (item["symbol"], item["side"]): item for item in current_deltas
        }
        for key, gap in pending_index.items():
            observed = current_index.get(key)
            if observed is None:
                self.repository.update_reconciliation_gap(
                    gap["gap_id"],
                    {
                        "state": "DISMISSED",
                        "dismissed_at": int(detected_at),
                        "dismissed_reason": "position_delta_resolved",
                    },
                )
                continue
            observed_keys.add(key)
            if gap.get("state") == "REJECTED":
                observed_updates = {
                    "quantity_delta": int(observed.get("quantity_delta") or 0),
                    "price_estimate": observed.get("price_estimate") or 0.0,
                    "last_detected_at": int(detected_at),
                    "observed_count": int(gap.get("observed_count") or 1) + 1,
                }
                if _is_board_lot_delta(observed_updates["quantity_delta"]):
                    observed_updates.update(
                        {
                            "state": "OPEN",
                            "pending_until": _pending_until_for_observation(
                                detected_at=int(detected_at),
                                observed_count=1,
                                confirm_interval_seconds=self.external_confirm_interval_seconds,
                                confirm_observations=self.external_confirm_observations,
                            ),
                            "resolution_id": None,
                            "resolution_type": None,
                            "confirmed_at": None,
                        }
                    )
                self.repository.update_reconciliation_gap(
                    gap["gap_id"],
                    observed_updates,
                )
                continue
            updates = _build_gap_observation_updates(
                gap,
                observed=observed,
                detected_at=int(detected_at),
                confirm_interval_seconds=self.external_confirm_interval_seconds,
                confirm_observations=self.external_confirm_observations,
            )
            self.repository.update_reconciliation_gap(
                gap["gap_id"],
                updates,
            )

        for item in current_deltas:
            key = (item["symbol"], item["side"])
            if key in observed_keys:
                continue
            gap = {
                "gap_id": new_reconciliation_gap_id(),
                "symbol": item["symbol"],
                "side": item["side"],
                "quantity_delta": item["quantity_delta"],
                "price_estimate": item["price_estimate"],
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
                "state": "OPEN",
                "source": "position_diff",
                "matched_order_id": None,
                "matched_trade_fact_id": None,
            }
            self.repository.insert_reconciliation_gap(gap)
            created.append(gap)
        return created

    def reconcile_trade_reports(self, trade_reports):
        results = []
        pending_candidates = self.repository.list_reconciliation_gaps(state="OPEN")
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
                pending_candidates = self.repository.list_reconciliation_gaps(
                    state="OPEN"
                )
            candidate = _find_trade_gap(pending_candidates, normalized)
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
                candidate_updates = _build_gap_trade_updates(
                    candidate,
                    normalized_trade=normalized,
                    order=order,
                    trade_fact=result["trade_fact"],
                )
                candidate.update(candidate_updates)
                self.repository.update_reconciliation_gap(
                    candidate["gap_id"],
                    candidate_updates,
                )
                self.repository.insert_reconciliation_resolution(
                    {
                        "resolution_id": new_reconciliation_resolution_id(),
                        "gap_id": candidate["gap_id"],
                        "resolution_type": "matched_execution_fill",
                        "resolved_quantity": int(normalized["quantity"] or 0),
                        "resolved_price": float(normalized["price"] or 0.0),
                        "resolved_at": int(normalized.get("trade_time") or 0),
                        "source_ref_type": "trade_fact",
                        "source_ref_id": result["trade_fact"]["trade_fact_id"],
                        "order_ref_id": order["internal_order_id"],
                    }
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
        for gap in self.repository.list_reconciliation_gaps(state="OPEN"):
            if int(gap.get("observed_count") or 1) < int(
                self.external_confirm_observations
            ):
                continue
            if int(gap["pending_until"]) > int(now):
                continue
            current_node = "reconciliation"
            ids = {"symbol": gap["symbol"]}
            try:
                updated_candidate = self._confirm_gap(gap, now=int(now))
                self._emit_runtime(
                    "reconciliation",
                    ids,
                    payload={
                        "resolution_type": updated_candidate.get("resolution_type"),
                        "gap_state": updated_candidate.get("state"),
                    },
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

    def _confirm_gap(self, gap, *, now):
        if gap.get("side") == "buy":
            return self._confirm_open_gap(gap, now=now)
        return self._confirm_close_gap(gap, now=now)

    def _confirm_open_gap(self, gap, *, now):
        quantity = int(gap.get("quantity_delta") or 0)
        resolution_id = new_reconciliation_resolution_id()
        resolution = {
            "resolution_id": resolution_id,
            "gap_id": gap["gap_id"],
            "resolved_quantity": quantity,
            "resolved_price": float(gap.get("price_estimate") or 0.0),
            "resolved_at": int(now),
            "source_ref_type": "reconciliation_gap",
            "source_ref_id": gap["gap_id"],
        }
        if quantity <= 0 or quantity % 100 != 0:
            resolution["resolution_type"] = "board_lot_rejected"
            self.repository.insert_reconciliation_resolution(resolution)
            return self.repository.update_reconciliation_gap(
                gap["gap_id"],
                {
                    "state": "REJECTED",
                    "confirmed_at": int(now),
                    "resolution_id": resolution_id,
                    "resolution_type": resolution["resolution_type"],
                },
            )

        entry = _build_auto_open_entry(gap, resolution_id=resolution_id, confirmed_at=now)
        entry_slices = _arrange_entry_slices(
            entry,
            lot_amount=_safe_resolve_lot_amount(gap["symbol"]),
            grid_interval=_safe_grid_interval_lookup(
                gap["symbol"],
                {
                    "symbol": gap["symbol"],
                    "trade_time": int(now),
                    "price": entry["entry_price"],
                    "quantity": quantity,
                    "side": "buy",
                },
            ),
        )
        resolution["resolution_type"] = "auto_open_entry"
        resolution["source_ref_type"] = "position_entry"
        resolution["source_ref_id"] = entry["entry_id"]
        self.repository.insert_reconciliation_resolution(resolution)
        self.repository.replace_position_entry(entry)
        self.repository.replace_entry_slices_for_entry(entry["entry_id"], entry_slices)
        return self.repository.update_reconciliation_gap(
            gap["gap_id"],
            {
                "state": "AUTO_OPENED",
                "confirmed_at": int(now),
                "resolution_id": resolution_id,
                "resolution_type": resolution["resolution_type"],
                "entry_id": entry["entry_id"],
            },
        )

    def _confirm_close_gap(self, gap, *, now):
        remaining = int(gap.get("quantity_delta") or 0)
        resolution_id = new_reconciliation_resolution_id()
        if remaining <= 0 or not _is_board_lot_delta(remaining):
            resolution = {
                "resolution_id": resolution_id,
                "gap_id": gap["gap_id"],
                "resolution_type": "board_lot_rejected",
                "resolved_quantity": remaining,
                "resolved_price": float(gap.get("price_estimate") or 0.0),
                "resolved_at": int(now),
                "source_ref_type": "reconciliation_gap",
                "source_ref_id": gap["gap_id"],
            }
            self.repository.insert_reconciliation_resolution(resolution)
            return self.repository.update_reconciliation_gap(
                gap["gap_id"],
                {
                    "state": "REJECTED",
                    "confirmed_at": int(now),
                    "resolution_id": resolution_id,
                    "resolution_type": resolution["resolution_type"],
                },
            )
        entry_allocations = []
        if remaining > 0:
            remaining, entry_allocations = _allocate_gap_to_entry_slices(
                repository=self.repository,
                symbol=gap["symbol"],
                quantity=remaining,
                resolution_id=resolution_id,
            )

        legacy_allocations = []
        if remaining > 0:
            legacy_allocations = _allocate_gap_to_legacy_buy_lots(
                repository=self.repository,
                symbol=gap["symbol"],
                quantity=remaining,
                price=float(gap.get("price_estimate") or 0.0),
                resolution_id=resolution_id,
                trade_time=int(now),
            )
            remaining = 0

        resolution = {
            "resolution_id": resolution_id,
            "gap_id": gap["gap_id"],
            "resolution_type": "auto_close_allocation",
            "resolved_quantity": int(gap.get("quantity_delta") or 0),
            "resolved_price": float(gap.get("price_estimate") or 0.0),
            "resolved_at": int(now),
            "source_ref_type": "reconciliation_gap",
            "source_ref_id": gap["gap_id"],
            "entry_allocation_ids": [
                item["allocation_id"] for item in entry_allocations
            ],
            "legacy_allocation_ids": [
                item["allocation_id"] for item in legacy_allocations
            ],
        }
        self.repository.insert_reconciliation_resolution(resolution)
        return self.repository.update_reconciliation_gap(
            gap["gap_id"],
            {
                "state": "AUTO_CLOSED",
                "confirmed_at": int(now),
                "resolution_id": resolution_id,
                "resolution_type": resolution["resolution_type"],
            },
        )

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


def _build_internal_remaining_by_symbol(repository):
    result = {}
    position_entries = []
    if hasattr(repository, "list_position_entries"):
        position_entries = list(repository.list_position_entries() or [])
    for item in position_entries:
        remaining_quantity = int(item.get("remaining_quantity", 0) or 0)
        if remaining_quantity <= 0:
            continue
        result[item["symbol"]] = result.get(item["symbol"], 0) + remaining_quantity
    for item in repository.list_buy_lots():
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


def _index_pending_gaps_by_symbol_side(candidates):
    indexed = {}
    for item in list(candidates or []):
        key = (item.get("symbol"), item.get("side"))
        if not all(key):
            continue
        indexed[key] = item
    return indexed


def _find_trade_gap(candidates, normalized_trade):
    exact_matches = [
        item
        for item in candidates
        if item.get("state") == "OPEN"
        and match_candidate_to_trade(item, normalized_trade)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    partial_matches = [
        item
        for item in candidates
        if item.get("state") == "OPEN"
        and match_candidate_to_trade(item, normalized_trade, allow_partial=True)
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]
    return None


def _build_gap_trade_updates(candidate, *, normalized_trade, order, trade_fact):
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


def _build_gap_observation_updates(
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
    return {
        "quantity_delta": observed_quantity,
        "price_estimate": observed.get("price_estimate") or 0.0,
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


def _safe_resolve_lot_amount(symbol):
    try:
        from freshquant.order_management.ingest.xt_reports import _resolve_lot_amount

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


def _build_auto_open_entry(gap, *, resolution_id, confirmed_at):
    trade_datetime = datetime.fromtimestamp(int(confirmed_at), tz=timezone.utc)
    date_value = int(trade_datetime.strftime("%Y%m%d"))
    time_value = trade_datetime.strftime("%H:%M:%S")
    quantity = int(gap.get("quantity_delta") or 0)
    price = float(gap.get("price_estimate") or 0.0)
    return {
        "entry_id": new_position_entry_id(),
        "symbol": gap["symbol"],
        "entry_type": "auto_reconciled_open",
        "source_ref_type": "reconciliation_resolution",
        "source_ref_id": resolution_id,
        "entry_price": price,
        "buy_price_real": price,
        "original_quantity": quantity,
        "remaining_quantity": quantity,
        "amount": round(price * quantity, 2),
        "amount_adjust": 1.0,
        "date": date_value,
        "time": time_value,
        "trade_time": int(confirmed_at),
        "source": "external_inferred",
        "arrange_mode": "runtime_grid",
        "status": "OPEN",
        "sell_history": [],
    }


def _arrange_entry_slices(entry, *, lot_amount, grid_interval):
    slices = []
    _arrange_entry_remaining(
        slices=slices,
        entry=entry,
        remaining_quantity=int(entry["original_quantity"]),
        remaining_amount=float(entry["original_quantity"]) * float(entry["entry_price"]),
        current_price=float(entry["entry_price"]),
        lot_amount=lot_amount,
        grid_interval=grid_interval,
        slice_seq=0,
    )
    return slices


def _arrange_entry_remaining(
    *,
    slices,
    entry,
    remaining_quantity,
    remaining_amount,
    current_price,
    lot_amount,
    grid_interval,
    slice_seq,
):
    if remaining_quantity <= 0:
        return

    if remaining_amount > lot_amount:
        quantity = int(lot_amount / current_price / 100) * 100
        if quantity == 0:
            quantity = 100
        quantity = min(quantity, remaining_quantity)
    else:
        quantity = remaining_quantity

    rounded_price = float(f"{current_price:.2f}")
    slices.append(
        {
            "entry_slice_id": new_entry_slice_id(),
            "entry_id": entry["entry_id"],
            "slice_seq": slice_seq,
            "guardian_price": rounded_price,
            "original_quantity": quantity,
            "remaining_quantity": quantity,
            "remaining_amount": round(rounded_price * quantity, 2),
            "sort_key": rounded_price,
            "date": entry.get("date"),
            "time": entry.get("time"),
            "trade_time": entry.get("trade_time"),
            "symbol": entry["symbol"],
            "status": "OPEN",
        }
    )

    next_quantity = remaining_quantity - quantity
    if next_quantity <= 0:
        return

    next_amount = remaining_amount - quantity * rounded_price
    next_price = float(f"{(current_price * grid_interval):.2f}")
    _arrange_entry_remaining(
        slices=slices,
        entry=entry,
        remaining_quantity=next_quantity,
        remaining_amount=next_amount,
        current_price=next_price,
        lot_amount=lot_amount,
        grid_interval=grid_interval,
        slice_seq=slice_seq + 1,
    )


def _allocate_gap_to_entry_slices(*, repository, symbol, quantity, resolution_id):
    remaining = int(quantity or 0)
    if remaining <= 0:
        return 0, []
    entries = {
        item["entry_id"]: dict(item)
        for item in repository.list_position_entries(symbol=symbol)
        if int(item.get("remaining_quantity") or 0) > 0
    }
    if not entries:
        return remaining, []

    open_slices = sorted(
        repository.list_open_entry_slices(symbol=symbol),
        key=lambda item: (
            float(item.get("guardian_price") or 0.0),
            str(item.get("entry_slice_id") or ""),
        ),
        reverse=True,
    )
    allocations = []
    touched_entry_ids = set()
    slices_by_entry = {}
    for slice_document in open_slices:
        slices_by_entry.setdefault(slice_document["entry_id"], []).append(slice_document)
        if remaining <= 0:
            continue
        if int(slice_document.get("remaining_quantity") or 0) <= 0:
            continue
        allocated_quantity = min(int(slice_document["remaining_quantity"]), remaining)
        slice_document["remaining_quantity"] -= allocated_quantity
        slice_document["remaining_amount"] = round(
            float(slice_document.get("guardian_price") or 0.0)
            * int(slice_document["remaining_quantity"]),
            2,
        )
        slice_document["status"] = (
            "CLOSED" if int(slice_document["remaining_quantity"]) == 0 else "OPEN"
        )
        entry = entries[slice_document["entry_id"]]
        entry["remaining_quantity"] = int(entry.get("remaining_quantity") or 0) - allocated_quantity
        entry["status"] = _resolve_entry_status(entry["remaining_quantity"], entry["original_quantity"])
        allocations.append(
            {
                "allocation_id": new_allocation_id(),
                "resolution_id": resolution_id,
                "entry_id": slice_document["entry_id"],
                "entry_slice_id": slice_document["entry_slice_id"],
                "guardian_price": slice_document.get("guardian_price"),
                "allocated_quantity": allocated_quantity,
                "symbol": symbol,
            }
        )
        touched_entry_ids.add(slice_document["entry_id"])
        remaining -= allocated_quantity

    for entry_id in touched_entry_ids:
        repository.replace_position_entry(entries[entry_id])
        repository.replace_entry_slices_for_entry(entry_id, slices_by_entry.get(entry_id, []))
    if allocations:
        repository.insert_exit_allocations(allocations)
    return remaining, allocations


def _allocate_gap_to_legacy_buy_lots(
    *,
    repository,
    symbol,
    quantity,
    price,
    resolution_id,
    trade_time,
):
    remaining = int(quantity or 0)
    if remaining <= 0:
        return []
    buy_lots = repository.list_buy_lots(symbol)
    open_slices = repository.list_open_slices(symbol)
    sell_trade_fact = {
        "trade_fact_id": resolution_id,
        "symbol": symbol,
        "side": "sell",
        "quantity": remaining,
        "price": price,
        "trade_time": trade_time,
    }
    allocations = allocate_sell_to_slices(
        buy_lots=buy_lots,
        open_slices=open_slices,
        sell_trade_fact=sell_trade_fact,
    )
    for item in buy_lots:
        repository.replace_buy_lot(item)
    repository.replace_open_slices(open_slices)
    repository.insert_sell_allocations(allocations)
    return allocations


def _resolve_entry_status(remaining_quantity, original_quantity):
    if int(remaining_quantity or 0) <= 0:
        return "CLOSED"
    if int(remaining_quantity or 0) >= int(original_quantity or 0):
        return "OPEN"
    return "PARTIALLY_EXITED"


def _is_board_lot_delta(quantity):
    return int(quantity or 0) > 0 and int(quantity or 0) % 100 == 0


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("order_reconcile")
    return _runtime_logger
