# -*- coding: utf-8 -*-

import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_slices,
)
from freshquant.order_management.ids import (
    new_allocation_id,
    new_entry_slice_id,
    new_event_id,
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
from freshquant.order_management.reconcile.matcher import match_candidate_to_trade
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.time_helpers import (
    beijing_date_time_from_epoch,
    beijing_day_start_from_epoch,
)
from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.runtime_observability.failures import (
    build_exception_payload,
    mark_exception_emitted,
)
from freshquant.runtime_observability.logger import RuntimeEventLogger


_DEFAULT_RECONCILE_LOT_AMOUNT = 3000
_SELL_GAP_FUSE_MIN_SYMBOLS = 3
_SELL_GAP_FUSE_MIN_QUANTITY_RATIO = 0.5
_SELL_GAP_EVIDENCE_WINDOW_SECONDS = 300


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
        self._skip_sell_confirmation = False

    def detect_external_candidates(self, positions, detected_at):
        self._skip_sell_confirmation = False
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

        sell_gap_fuse = _detect_sell_gap_blast(
            current_deltas=current_deltas,
            internal_by_symbol=internal_by_symbol,
            repository=self.repository,
            detected_at=int(detected_at),
        )
        if sell_gap_fuse is not None:
            self._skip_sell_confirmation = True
            self._emit_runtime(
                "snapshot_fuse",
                {},
                status="warning",
                reason_code="sell_gap_blast_fused",
                payload=sell_gap_fuse,
            )

        current_index = {
            (item["symbol"], item["side"]): item for item in current_deltas
        }
        for key, gap in pending_index.items():
            if sell_gap_fuse is not None and key[1] == "sell":
                continue
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
            if sell_gap_fuse is not None and item["side"] == "sell":
                continue
            gap = {
                "gap_id": new_reconciliation_gap_id(),
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
        skip_sell_confirmation = self._skip_sell_confirmation
        try:
            for gap in self.repository.list_reconciliation_gaps(state="OPEN"):
                if skip_sell_confirmation and gap.get("side") == "sell":
                    continue
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
        finally:
            self._skip_sell_confirmation = False
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

        entry = _build_auto_open_entry(
            gap, resolution_id=resolution_id, confirmed_at=now
        )
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
        updated_gap = self.repository.update_reconciliation_gap(
            gap["gap_id"],
            {
                "state": "AUTO_OPENED",
                "confirmed_at": int(now),
                "resolution_id": resolution_id,
                "resolution_type": resolution["resolution_type"],
                "entry_id": entry["entry_id"],
            },
        )
        _after_holdings_reconciled(gap["symbol"], repository=self.repository)
        return updated_gap

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
        updated_gap = self.repository.update_reconciliation_gap(
            gap["gap_id"],
            {
                "state": "AUTO_CLOSED",
                "confirmed_at": int(now),
                "resolution_id": resolution_id,
                "resolution_type": resolution["resolution_type"],
            },
        )
        _after_holdings_reconciled(gap["symbol"], repository=self.repository)
        return updated_gap

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
    symbols_with_open_v2_entries = set()
    position_entries = []
    if hasattr(repository, "list_position_entries"):
        position_entries = list(repository.list_position_entries() or [])
    for item in position_entries:
        remaining_quantity = int(item.get("remaining_quantity", 0) or 0)
        if remaining_quantity <= 0:
            continue
        symbol = item["symbol"]
        symbols_with_open_v2_entries.add(symbol)
        result[symbol] = result.get(symbol, 0) + remaining_quantity
    for item in repository.list_buy_lots():
        symbol = item["symbol"]
        if symbol in symbols_with_open_v2_entries:
            continue
        result[symbol] = result.get(symbol, 0) + int(item.get("remaining_quantity", 0))
    return result


def _detect_sell_gap_blast(*, current_deltas, internal_by_symbol, repository, detected_at):
    sell_deltas = [
        item
        for item in list(current_deltas or [])
        if item.get("side") == "sell" and int(item.get("quantity_delta") or 0) > 0
    ]
    if len(sell_deltas) < _SELL_GAP_FUSE_MIN_SYMBOLS:
        return None
    if any(item.get("side") == "buy" for item in list(current_deltas or [])):
        return None

    internal_total_quantity = sum(max(int(value or 0), 0) for value in internal_by_symbol.values())
    if internal_total_quantity <= 0:
        return None
    sell_quantity_total = sum(int(item.get("quantity_delta") or 0) for item in sell_deltas)
    sell_quantity_ratio = sell_quantity_total / internal_total_quantity
    if sell_quantity_ratio < _SELL_GAP_FUSE_MIN_QUANTITY_RATIO:
        return None

    evidence = _collect_recent_sell_evidence(
        repository=repository,
        detected_at=int(detected_at),
        symbols={item["symbol"] for item in sell_deltas},
    )
    required_symbol_evidence = max(1, (len(sell_deltas) + 1) // 2)
    if (
        evidence["symbol_count"] >= required_symbol_evidence
        or evidence["quantity_total"] >= sell_quantity_total * 0.5
    ):
        return None

    return {
        "sell_symbol_count": len(sell_deltas),
        "sell_quantity_total": sell_quantity_total,
        "internal_total_quantity": internal_total_quantity,
        "sell_quantity_ratio": round(sell_quantity_ratio, 6),
        "recent_sell_evidence_symbol_count": evidence["symbol_count"],
        "recent_sell_evidence_quantity_total": evidence["quantity_total"],
    }


def _collect_recent_sell_evidence(*, repository, detected_at, symbols):
    tracked_symbols = {str(item or "").strip() for item in set(symbols or []) if str(item or "").strip()}
    if not tracked_symbols:
        return {"symbol_count": 0, "quantity_total": 0}

    lower_bound = int(detected_at) - _SELL_GAP_EVIDENCE_WINDOW_SECONDS
    evidence_symbols = set()
    quantity_total = 0

    if hasattr(repository, "list_trade_facts"):
        for symbol in tracked_symbols:
            for item in repository.list_trade_facts(symbol=symbol) or []:
                if str(item.get("side") or "").lower() != "sell":
                    continue
                trade_time = int(item.get("trade_time") or 0)
                if trade_time < lower_bound:
                    continue
                evidence_symbols.add(symbol)
                quantity_total += int(item.get("quantity") or 0)

    if hasattr(repository, "list_execution_fills"):
        for symbol in tracked_symbols:
            for item in repository.list_execution_fills(symbol=symbol) or []:
                if str(item.get("side") or "").lower() != "sell":
                    continue
                trade_time = int(item.get("trade_time") or 0)
                if trade_time < lower_bound:
                    continue
                evidence_symbols.add(symbol)
                quantity_total += int(item.get("quantity") or 0)

    return {
        "symbol_count": len(evidence_symbols),
        "quantity_total": quantity_total,
    }


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
    date_value, time_value = beijing_date_time_from_epoch(trade_time)
    return {
        "internal_order_id": internal_order_id,
        "broker_order_id": None,
        "broker_trade_id": f"inferred::{candidate['candidate_id']}",
        "symbol": candidate["symbol"],
        "side": candidate["side"],
        "quantity": candidate["quantity_delta"],
        "price": candidate.get("price_estimate") or 0.0,
        "trade_time": trade_time,
        "date": date_value,
        "time": time_value,
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

        day_start = beijing_day_start_from_epoch(detected_at)
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
        from freshquant.order_management.ingest.xt_reports import _resolve_lot_amount

        return _resolve_lot_amount(symbol)
    except Exception:
        # External reconcile should prefer converging broker truth over blocking on
        # optional lot-amount metadata lookups.
        return _DEFAULT_RECONCILE_LOT_AMOUNT


def _safe_grid_interval_lookup(symbol, trade_fact):
    try:
        return _default_grid_interval_lookup(symbol, trade_fact)
    except Exception:
        # External reconcile should converge broker truth even when the optional
        # market-data-based grid lookup is temporarily unavailable.
        return 1.03


def _build_auto_open_entry(gap, *, resolution_id, confirmed_at):
    date_value, time_value = beijing_date_time_from_epoch(confirmed_at)
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
        remaining_amount=float(entry["original_quantity"])
        * float(entry["entry_price"]),
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
        slices_by_entry.setdefault(slice_document["entry_id"], []).append(
            slice_document
        )
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
        entry["remaining_quantity"] = (
            int(entry.get("remaining_quantity") or 0) - allocated_quantity
        )
        entry["status"] = _resolve_entry_status(
            entry["remaining_quantity"], entry["original_quantity"]
        )
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
        repository.replace_entry_slices_for_entry(
            entry_id, slices_by_entry.get(entry_id, [])
        )
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


def _after_holdings_reconciled(symbol, *, repository):
    _mark_stock_holdings_projection_updated()
    _sync_stock_fills_compat(symbol, repository=repository)


def _mark_stock_holdings_projection_updated():
    from freshquant.order_management.ingest.xt_reports import (
        mark_stock_holdings_projection_updated,
    )

    return mark_stock_holdings_projection_updated()


def _sync_stock_fills_compat(symbol, *, repository):
    from freshquant.order_management.projection.stock_fills_compat import (
        sync_symbol,
    )

    return sync_symbol(symbol, repository=repository)


_runtime_logger = None


def _get_runtime_logger():
    global _runtime_logger
    if _runtime_logger is None:
        _runtime_logger = RuntimeEventLogger("order_reconcile")
    return _runtime_logger
