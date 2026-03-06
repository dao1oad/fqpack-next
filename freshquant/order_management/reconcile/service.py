# -*- coding: utf-8 -*-

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


class ExternalOrderReconcileService:
    def __init__(
        self,
        repository=None,
        tracking_service=None,
        ingest_service=None,
        external_confirm_seconds=120,
    ):
        self.repository = repository or OrderManagementRepository()
        self.tracking_service = tracking_service or OrderTrackingService(
            repository=self.repository
        )
        self.ingest_service = ingest_service or OrderManagementXtIngestService(
            repository=self.repository,
            tracking_service=self.tracking_service,
        )
        self.external_confirm_seconds = external_confirm_seconds

    def detect_external_candidates(self, positions, detected_at):
        positions_by_symbol = _build_positions_by_symbol(positions)
        internal_by_symbol = _build_internal_remaining_by_symbol(
            self.repository.list_buy_lots()
        )
        created = []

        for symbol in sorted(set(positions_by_symbol) | set(internal_by_symbol)):
            position = positions_by_symbol.get(symbol, {})
            external_quantity = int(position.get("volume", 0) or 0)
            internal_quantity = int(internal_by_symbol.get(symbol, 0))
            delta = external_quantity - internal_quantity
            if delta == 0:
                continue
            side = "buy" if delta > 0 else "sell"
            quantity_delta = abs(delta)
            existing = _find_pending_candidate(
                self.repository.list_external_candidates("INFERRED_PENDING"),
                symbol=symbol,
                side=side,
                quantity_delta=quantity_delta,
            )
            if existing is not None:
                continue

            candidate = {
                "candidate_id": new_candidate_id(),
                "symbol": symbol,
                "side": side,
                "quantity_delta": quantity_delta,
                "price_estimate": position.get("avg_price")
                or position.get("open_price")
                or 0.0,
                "detected_at": int(detected_at),
                "pending_until": int(detected_at) + int(self.external_confirm_seconds),
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
            normalized = normalize_xt_trade_report(report, repository=self.repository)
            if self.repository.find_order_by_broker_order_id(
                normalized.get("broker_order_id")
            ):
                continue

            match_status, matched_order = self._match_inflight_internal_order(
                normalized
            )
            if match_status == "matched":
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
                result = self.ingest_service.ingest_trade_report(
                    normalized,
                    lot_amount=_safe_resolve_lot_amount(normalized["symbol"]),
                    grid_interval_lookup=_safe_grid_interval_lookup,
                )
                results.append(result)
                continue
            if match_status == "defer":
                continue

            candidate = next(
                (
                    item
                    for item in pending_candidates
                    if match_candidate_to_trade(item, normalized)
                ),
                None,
            )
            order = self._create_external_order(
                symbol=normalized["symbol"],
                side=normalized["side"],
                quantity=normalized["quantity"],
                price=normalized["price"],
                source_type="external_reported",
                state="FILLED",
                broker_order_id=normalized.get("broker_order_id"),
            )
            normalized["internal_order_id"] = order["internal_order_id"]
            normalized["source"] = "external_reported"
            result = self.ingest_service.ingest_trade_report(
                normalized,
                lot_amount=_safe_resolve_lot_amount(normalized["symbol"]),
                grid_interval_lookup=_safe_grid_interval_lookup,
            )
            if candidate is not None:
                self.repository.update_external_candidate(
                    candidate["candidate_id"],
                    {
                        "state": "MATCHED",
                        "matched_order_id": order["internal_order_id"],
                        "matched_trade_fact_id": result["trade_fact"]["trade_fact_id"],
                    },
                )
            results.append(result)
        return results

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
            if int(candidate["pending_until"]) > int(now):
                continue

            order = self._create_external_order(
                symbol=candidate["symbol"],
                side=candidate["side"],
                quantity=candidate["quantity_delta"],
                price=candidate.get("price_estimate") or 0.0,
                source_type="external_inferred",
                state="INFERRED_CONFIRMED",
                broker_order_id=None,
            )
            trade_report = _build_inferred_trade_report(
                candidate, order["internal_order_id"]
            )
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
            confirmed.append(updated_candidate)
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


def _safe_resolve_lot_amount(symbol):
    try:
        return _resolve_lot_amount(symbol)
    except Exception:
        return 3000


def _safe_grid_interval_lookup(symbol, trade_fact):
    try:
        return _default_grid_interval_lookup(symbol, trade_fact)
    except Exception:
        return 1.03
