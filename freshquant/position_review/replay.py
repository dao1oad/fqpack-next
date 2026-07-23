# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import floor
from typing import Any
from zoneinfo import ZoneInfo

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
VERDICTS = (
    "PASS",
    "FAIL",
    "INSUFFICIENT_EVIDENCE",
    "NOT_APPLICABLE",
)


def build_historical_threshold_ratios(events) -> dict[str, dict[str, Any]]:
    """Extract threshold parameters without assuming percent or ATR mode."""

    evidence_by_trace: dict[str, dict[str, Any]] = {}
    for event in events or []:
        if str(event.get("node") or "") != "price_threshold_check":
            continue
        trace_id = str(event.get("trace_id") or "").strip()
        if not trace_id:
            continue
        context_value = event.get("decision_context")
        context: dict[str, Any] = (
            context_value if isinstance(context_value, dict) else {}
        )
        threshold_value = context.get("threshold")
        threshold: dict[str, Any] = (
            threshold_value if isinstance(threshold_value, dict) else {}
        )
        last_price = _positive_float(
            threshold.get("last_fill_price") or threshold.get("base_price")
        )
        top_price = _positive_float(threshold.get("top_river_price"))
        if last_price is None or top_price is None:
            continue
        ratio = top_price / last_price
        delta = top_price - last_price
        mode = _threshold_mode(
            threshold.get("mode")
            or threshold.get("threshold_mode")
            or context.get("threshold_mode")
            or context.get("mode")
        )
        if ratio > 0 and delta > 0:
            evidence_by_trace.setdefault(
                trace_id,
                {
                    "mode": mode,
                    "ratio": ratio,
                    "delta": delta,
                    "observed_base_price": last_price,
                    "observed_top_price": top_price,
                },
            )
    return evidence_by_trace


def build_historical_sell_constraints(events) -> dict[str, dict[str, Any]]:
    constraints: dict[str, dict[str, Any]] = defaultdict(dict)
    for event in events or []:
        trace_id = str(event.get("trace_id") or "").strip()
        if not trace_id:
            continue
        node = str(event.get("node") or "")
        context_value = event.get("decision_context")
        context: dict[str, Any] = (
            context_value if isinstance(context_value, dict) else {}
        )
        quantity_value = context.get("quantity")
        quantity: dict[str, Any] = (
            quantity_value if isinstance(quantity_value, dict) else {}
        )
        if node == "sellable_volume_check":
            for source_key, target_key in (
                ("can_use_volume", "can_use_volume"),
                ("raw_quantity", "traced_raw_quantity"),
                ("submit_quantity", "traced_submit_quantity"),
            ):
                value = quantity.get(source_key)
                if value is not None:
                    constraints[trace_id][target_key] = max(_int(value), 0)
    threshold_evidence = build_historical_threshold_ratios(events)
    for trace_id, evidence in threshold_evidence.items():
        constraints[trace_id]["threshold_evidence"] = evidence
    return dict(constraints)


def reconstruct_inventory(entries, slices, allocations) -> list[dict[str, Any]]:
    """Rebuild the original Guardian slices from mutable remaining state.

    Closed slices can disappear from ``om_entry_slices``. Their immutable exit
    allocations carry enough identity, price and quantity to restore them.
    """

    entry_map = {
        str(item.get("entry_id") or ""): dict(item)
        for item in entries or []
        if str(item.get("entry_id") or "").strip()
    }
    allocated_by_slice: dict[str, int] = defaultdict(int)
    allocation_meta: dict[str, dict[str, Any]] = {}
    for allocation in allocations or []:
        slice_id = str(allocation.get("entry_slice_id") or "").strip()
        entry_id = str(allocation.get("entry_id") or "").strip()
        if not slice_id or entry_id not in entry_map:
            continue
        quantity = max(_int(allocation.get("allocated_quantity")), 0)
        allocated_by_slice[slice_id] += quantity
        allocation_meta.setdefault(slice_id, dict(allocation))

    inventory_by_slice: dict[str, dict[str, Any]] = {}
    for item in slices or []:
        entry_id = str(item.get("entry_id") or "").strip()
        slice_id = str(item.get("entry_slice_id") or "").strip()
        if not slice_id or entry_id not in entry_map:
            continue
        allocated = allocated_by_slice.get(slice_id, 0)
        original = max(
            _int(item.get("original_quantity")),
            _int(item.get("remaining_quantity")) + allocated,
        )
        if original <= 0:
            continue
        inventory_by_slice[slice_id] = _inventory_slice(
            entry_map[entry_id],
            item,
            original_quantity=original,
        )

    for slice_id, allocation in allocation_meta.items():
        if slice_id in inventory_by_slice:
            continue
        entry_id = str(allocation.get("entry_id") or "").strip()
        original = allocated_by_slice.get(slice_id, 0)
        if entry_id not in entry_map or original <= 0:
            continue
        inventory_by_slice[slice_id] = _inventory_slice(
            entry_map[entry_id],
            {
                "entry_slice_id": slice_id,
                "guardian_price": allocation.get("guardian_price"),
                "sort_key": allocation.get("guardian_price"),
            },
            original_quantity=original,
        )

    quantity_by_entry: dict[str, int] = defaultdict(int)
    for item in inventory_by_slice.values():
        quantity_by_entry[item["entry_id"]] += item["initial_quantity"]

    for entry_id, entry in entry_map.items():
        if quantity_by_entry.get(entry_id, 0) > 0:
            continue
        quantity = max(_int(entry.get("original_quantity")), 0)
        price = _positive_float(entry.get("entry_price") or entry.get("buy_price_real"))
        if quantity <= 0 or price is None:
            continue
        slice_id = f"{entry_id}:synthetic"
        inventory_by_slice[slice_id] = _inventory_slice(
            entry,
            {
                "entry_slice_id": slice_id,
                "guardian_price": price,
                "sort_key": price,
            },
            original_quantity=quantity,
            synthetic=True,
        )

    return sorted(
        inventory_by_slice.values(),
        key=lambda item: (
            item["available_at"],
            item["guardian_price"],
            item["entry_slice_id"],
        ),
    )


def review_requests(
    *,
    symbol: str,
    requests: list[dict[str, Any]],
    orders_by_request: dict[str, list[dict[str, Any]]],
    canonical_trades: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    threshold_ratios: dict[str, Any],
    sell_constraints: dict[str, dict[str, Any]] | None = None,
    pm_decisions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Review each request against point-in-time inventory and rule evidence."""

    normalized_requests = [
        dict(item)
        for item in requests or []
        if str(item.get("symbol") or "").strip() == symbol
    ]
    request_by_id = {
        str(item.get("request_id") or ""): item
        for item in normalized_requests
        if str(item.get("request_id") or "").strip()
    }
    actual_by_request: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in canonical_trades or []:
        request_id = str(trade.get("request_id") or "").strip()
        if request_id in request_by_id:
            actual_by_request[request_id].append(dict(trade))

    pm_by_trace, pm_by_intent = _index_pm_decisions(pm_decisions or [])
    source_remaining_by_request = {
        request_id: _source_plan(request)
        for request_id, request in request_by_id.items()
    }
    reviews: list[dict[str, Any]] = []

    events = []
    for request in normalized_requests:
        events.append(
            (
                _timestamp(request.get("created_at")),
                0,
                str(request.get("request_id") or ""),
                "request",
                request,
            )
        )
    for index, trade in enumerate(canonical_trades or []):
        if str(trade.get("side") or "").lower() != "sell":
            continue
        trade_event_time = _timestamp(
            trade.get("trade_time") or trade.get("traded_time")
        )
        linked_request = request_by_id.get(str(trade.get("request_id") or "").strip())
        linked_request_time = _timestamp((linked_request or {}).get("created_at"))
        # XT trade timestamps have one-second precision while request timestamps
        # retain microseconds. Preserve the causal request -> fill order when both
        # records fall in the same broker second.
        if (
            linked_request_time > 0
            and trade_event_time <= linked_request_time
            and linked_request_time - trade_event_time < 5
        ):
            trade_event_time = linked_request_time + 0.001
        events.append(
            (
                trade_event_time,
                1,
                f"{trade.get('broker_trade_id') or trade.get('traded_id') or index}",
                "sell_fill",
                trade,
            )
        )
    events.sort(key=lambda item: (item[0], item[1], item[2]))

    for event_time, _, _, kind, payload in events:
        if kind == "sell_fill":
            request_id = str(payload.get("request_id") or "").strip()
            _consume_inventory(
                inventory,
                quantity=max(_int(payload.get("quantity")), 0),
                at_time=event_time,
                source_remaining=source_remaining_by_request.get(request_id),
            )
            continue

        request = payload
        request_id = str(request.get("request_id") or "")
        actual_trades = actual_by_request.get(request_id, [])
        orders = list(orders_by_request.get(request_id) or [])
        pm_decision = _find_pm_decision(
            request,
            by_trace=pm_by_trace,
            by_intent=pm_by_intent,
        )
        review = _review_one_request(
            symbol=symbol,
            request=request,
            orders=orders,
            actual_trades=actual_trades,
            inventory=inventory,
            request_time=event_time,
            threshold_evidence=threshold_ratios.get(
                str(request.get("trace_id") or "").strip()
            ),
            sell_constraint=(sell_constraints or {}).get(
                str(request.get("trace_id") or "").strip(),
                {},
            ),
            pm_decision=pm_decision,
        )
        reviews.append(review)

    reviews.sort(key=lambda item: (item.get("time") or "", item["review_id"]))
    return reviews


def _review_one_request(
    *,
    symbol,
    request,
    orders,
    actual_trades,
    inventory,
    request_time,
    threshold_evidence,
    sell_constraint,
    pm_decision,
):
    request_id = str(request.get("request_id") or "")
    action = str(request.get("action") or "").strip().lower()
    requested_quantity = max(_int(request.get("quantity")), 0)
    strategy_context = (
        request.get("strategy_context")
        if isinstance(request.get("strategy_context"), dict)
        else {}
    )
    buy_context = (
        strategy_context.get("guardian_buy_grid")
        if isinstance(strategy_context.get("guardian_buy_grid"), dict)
        else None
    )
    sell_context = (
        strategy_context.get("guardian_sell_sources")
        if isinstance(strategy_context.get("guardian_sell_sources"), dict)
        else None
    )
    actual = _actual_summary(actual_trades)
    actual["requested_quantity"] = requested_quantity
    reason_codes: list[str] = []
    expected = {
        "quantity": None,
        "threshold_price": None,
        "lowest_guardian_price": None,
        "formula": None,
        "source_entries": list((sell_context or {}).get("entries") or []),
    }

    if action == "buy" and buy_context is not None:
        verdict = _review_guardian_buy(
            request=request,
            context=buy_context,
            expected=expected,
            reason_codes=reason_codes,
        )
    elif action == "sell" and sell_context is not None:
        verdict = _review_guardian_sell(
            request=request,
            context=sell_context,
            inventory=inventory,
            request_time=request_time,
            threshold_evidence=threshold_evidence,
            sell_constraint=sell_constraint,
            expected=expected,
            reason_codes=reason_codes,
        )
    else:
        verdict = "NOT_APPLICABLE"
        reason_codes.append("non_guardian_request")

    if (
        verdict != "NOT_APPLICABLE"
        and actual["filled_quantity"] > requested_quantity
        and action in {"buy", "sell"}
    ):
        verdict = "FAIL"
        _append_once(reason_codes, "filled_quantity_exceeds_request")

    order_states = {
        str(item.get("state") or "").strip().upper() for item in orders or []
    }
    if (
        verdict == "PASS"
        and any(state in {"FILLED", "PARTIAL_FILLED"} for state in order_states)
        and actual["filled_quantity"] <= 0
    ):
        verdict = "INSUFFICIENT_EVIDENCE"
        _append_once(reason_codes, "canonical_trade_missing")

    confidence = _evidence_confidence(
        verdict=verdict,
        actual_trades=actual_trades,
        formula_evidence_complete=expected["quantity"] is not None,
    )
    trace_id = str(request.get("trace_id") or "").strip() or None
    intent_id = str(request.get("intent_id") or "").strip() or None
    internal_order_ids = [
        str(item.get("internal_order_id") or "")
        for item in orders
        if str(item.get("internal_order_id") or "").strip()
    ]
    entry_ids = [
        str(item.get("entry_id") or "")
        for item in expected.get("source_entries") or []
        if str(item.get("entry_id") or "").strip()
    ]
    execution_status = _execution_status(
        orders=orders,
        requested_quantity=requested_quantity,
        filled_quantity=actual["filled_quantity"],
    )
    expected_quantity = expected.get("quantity")
    quantity_delta = (
        requested_quantity - int(expected_quantity)
        if expected_quantity is not None
        else None
    )
    return {
        "review_id": request_id,
        "request_id": request_id,
        "internal_order_id": internal_order_ids[0] if internal_order_ids else None,
        "trace_id": trace_id,
        "intent_id": intent_id,
        "time": _iso_time(request.get("created_at")),
        "side": action or None,
        "request": {
            "price": _float_or_none(request.get("price")),
            "quantity": requested_quantity,
            "source": request.get("source"),
            "strategy_name": request.get("strategy_name"),
        },
        "expected": expected,
        "actual": actual,
        "execution_status": execution_status,
        "quantities": {
            "requested": requested_quantity,
            "expected": expected_quantity,
            "filled": actual["filled_quantity"],
            "delta": quantity_delta,
        },
        "verdict": verdict,
        "reason_codes": reason_codes,
        "evidence_confidence": confidence,
        "evidence": {
            "xt_trade_ids": [
                str(item.get("broker_trade_id") or item.get("traded_id") or "")
                for item in actual_trades
                if str(
                    item.get("broker_trade_id") or item.get("traded_id") or ""
                ).strip()
            ],
            "execution_fill_ids": [
                str(item.get("execution_fill_id") or "")
                for item in actual_trades
                if str(item.get("execution_fill_id") or "").strip()
            ],
            "entry_ids": entry_ids,
            "association_quality": _association_quality(actual_trades),
            "pm_decision_id": (
                str((pm_decision or {}).get("decision_id") or "").strip() or None
            ),
        },
    }


def _review_guardian_buy(*, request, context, expected, reason_codes):
    source_price = _positive_float(context.get("source_price"))
    path = str(context.get("path") or "").strip().lower()
    if path == "new_open" or (not path and context.get("initial_amount") is not None):
        initial_amount = _positive_float(context.get("initial_amount"))
        if initial_amount is None or source_price is None:
            reason_codes.append("buy_snapshot_incomplete")
            return "INSUFFICIENT_EVIDENCE"
        expected_quantity = floor(initial_amount / source_price / 100) * 100
        expected.update(
            {
                "quantity": int(expected_quantity),
                "formula": "floor(initial_amount / source_price / 100) * 100",
                "initial_amount": initial_amount,
                "source_price": source_price,
                "grid_level": context.get("grid_level"),
                "path": "new_open",
            }
        )
    else:
        base_amount = _positive_float(context.get("base_amount"))
        multiplier = _positive_float(context.get("multiplier"))
        if base_amount is None or multiplier is None or source_price is None:
            reason_codes.append("buy_snapshot_incomplete")
            return "INSUFFICIENT_EVIDENCE"
        expected_quantity = floor((base_amount * multiplier) / source_price / 100) * 100
        expected.update(
            {
                "quantity": int(expected_quantity),
                "formula": (
                    "floor(base_amount * multiplier / source_price / 100) * 100"
                ),
                "base_amount": base_amount,
                "multiplier": multiplier,
                "source_price": source_price,
                "grid_level": context.get("grid_level"),
                "path": path or "holding_add",
            }
        )
    if expected_quantity != _int(request.get("quantity")):
        reason_codes.append("requested_quantity_mismatch")
        return "FAIL"
    return "PASS"


def _threshold_candidates(evidence, guardian_price):
    normalized = _normalize_threshold_evidence(evidence)
    if not normalized:
        return []
    mode = normalized.get("mode")
    ratio = _positive_float(normalized.get("ratio"))
    delta = _positive_float(normalized.get("delta"))
    candidates = []
    if mode == "percent":
        if ratio is not None:
            candidates.append(
                {
                    "mode": "percent",
                    "threshold_price": round(guardian_price * ratio, 4),
                    "ratio": ratio,
                    "delta": None,
                }
            )
        return candidates
    if mode == "atr":
        if delta is not None:
            candidates.append(
                {
                    "mode": "atr",
                    "threshold_price": round(guardian_price + delta, 4),
                    "ratio": None,
                    "delta": delta,
                }
            )
        return candidates
    # Unknown historical mode is reviewable only when both models produce the
    # same requested quantity for the reconstructed inventory.
    if ratio is not None and delta is not None:
        candidates.extend(
            [
                {
                    "mode": "percent",
                    "threshold_price": round(guardian_price * ratio, 4),
                    "ratio": ratio,
                    "delta": None,
                },
                {
                    "mode": "atr",
                    "threshold_price": round(guardian_price + delta, 4),
                    "ratio": None,
                    "delta": delta,
                },
            ]
        )
    return candidates


def _normalize_threshold_evidence(evidence):
    if isinstance(evidence, (int, float)):
        ratio = _positive_float(evidence)
        return {"mode": "percent", "ratio": ratio} if ratio else None
    if not isinstance(evidence, dict):
        return None
    return {
        "mode": _threshold_mode(evidence.get("mode")),
        "ratio": evidence.get("ratio") or evidence.get("threshold_ratio"),
        "delta": evidence.get("delta") or evidence.get("threshold_delta"),
    }


def _threshold_mode(value):
    normalized = str(value or "").strip().lower()
    if normalized in {"percent", "percentage", "ratio", "pct"}:
        return "percent"
    if normalized in {"atr", "absolute", "delta", "fixed"}:
        return "atr"
    return None


def _raw_sell_quantity(active, *, signal_price, threshold_price):
    raw_quantity = 0
    threshold_met = signal_price >= threshold_price
    if threshold_met:
        for item in active:
            if signal_price <= item["guardian_price"]:
                break
            raw_quantity += item["remaining_quantity"]
        raw_quantity = floor(raw_quantity / 100) * 100
    return int(raw_quantity), threshold_met


def _review_guardian_sell(
    *,
    request,
    context,
    inventory,
    request_time,
    threshold_evidence,
    sell_constraint,
    expected,
    reason_codes,
):
    active = _active_inventory(inventory, request_time)
    if not active:
        reason_codes.append("inventory_evidence_missing")
        return "INSUFFICIENT_EVIDENCE"

    signal_price = _positive_float(request.get("price"))
    if signal_price is None:
        reason_codes.append("signal_price_missing")
        return "INSUFFICIENT_EVIDENCE"
    lowest = active[0]
    candidates = _threshold_candidates(
        threshold_evidence,
        lowest["guardian_price"],
    )
    if not candidates:
        reason_codes.append("historical_threshold_unavailable")
        return "INSUFFICIENT_EVIDENCE"
    for candidate in candidates:
        raw_quantity, met = _raw_sell_quantity(
            active,
            signal_price=signal_price,
            threshold_price=candidate["threshold_price"],
        )
        candidate["raw_quantity"] = raw_quantity
        candidate["threshold_met"] = met
    candidate_quantities = {int(item["raw_quantity"]) for item in candidates}
    if len(candidate_quantities) > 1:
        expected.update(
            {
                "quantity": None,
                "lowest_guardian_price": lowest["guardian_price"],
                "threshold_mode": "ambiguous",
                "threshold_candidates": candidates,
                "formula": (
                    "percent and ATR threshold models diverge for reconstructed "
                    "inventory"
                ),
            }
        )
        reason_codes.append("historical_threshold_mode_ambiguous")
        return "INSUFFICIENT_EVIDENCE"
    selected = candidates[0]
    normalized_threshold = _normalize_threshold_evidence(threshold_evidence) or {}
    raw_expected_quantity = int(selected["raw_quantity"])
    threshold_price = selected["threshold_price"]
    threshold_mode = "mode_insensitive" if len(candidates) > 1 else selected["mode"]
    if not any(item["threshold_met"] for item in candidates):
        reason_codes.append("threshold_not_met")
    expected_quantity = raw_expected_quantity
    can_use_volume = (
        max(_int(sell_constraint.get("can_use_volume")), 0)
        if isinstance(sell_constraint, dict)
        and sell_constraint.get("can_use_volume") is not None
        else None
    )
    if can_use_volume is not None:
        expected_quantity = (
            floor(min(raw_expected_quantity, can_use_volume) / 100) * 100
        )
    elif raw_expected_quantity > 0:
        snapshot_raw = _int(context.get("requested_quantity"))
        snapshot_submit = _int(context.get("submit_quantity"))
        if (
            raw_expected_quantity > snapshot_submit > 0
            and snapshot_raw == raw_expected_quantity
            and snapshot_submit == _int(request.get("quantity"))
        ):
            expected_quantity = snapshot_submit
            reason_codes.append("sellable_volume_from_request_snapshot")
        elif raw_expected_quantity != _int(request.get("quantity")):
            expected.update(
                {
                    "quantity": None,
                    "raw_quantity": int(raw_expected_quantity),
                    "threshold_price": threshold_price,
                    "lowest_guardian_price": lowest["guardian_price"],
                    "threshold_ratio": _round_or_none(
                        normalized_threshold.get("ratio")
                    ),
                    "threshold_delta": _round_or_none(
                        normalized_threshold.get("delta")
                    ),
                    "threshold_mode": threshold_mode,
                    "threshold_candidates": candidates,
                    "formula": (
                        "price >= replayed historical threshold; "
                        "sellable-volume cap unavailable"
                    ),
                }
            )
            reason_codes.append("historical_sellable_volume_unavailable")
            return "INSUFFICIENT_EVIDENCE"

    source_available: dict[str, int] = defaultdict(int)
    for item in active:
        source_available[item["entry_id"]] += item["remaining_quantity"]
    duplicate_source = False
    for source in list(context.get("entries") or []):
        entry_id = str(source.get("entry_id") or "").strip()
        planned = max(_int(source.get("quantity")), 0)
        if entry_id and planned > source_available.get(entry_id, 0):
            duplicate_source = True
            break
    if duplicate_source:
        reason_codes.append("duplicate_source_entry")

    traced_raw_quantity = (
        max(_int(sell_constraint.get("traced_raw_quantity")), 0)
        if isinstance(sell_constraint, dict)
        and sell_constraint.get("traced_raw_quantity") is not None
        else None
    )
    replay_diverged = (
        traced_raw_quantity is not None and traced_raw_quantity != raw_expected_quantity
    )
    if replay_diverged:
        reason_codes.append("state_replay_divergence")

    expected.update(
        {
            "quantity": int(expected_quantity),
            "raw_quantity": int(raw_expected_quantity),
            "can_use_volume": can_use_volume,
            "traced_raw_quantity": traced_raw_quantity,
            "threshold_price": threshold_price,
            "lowest_guardian_price": lowest["guardian_price"],
            "threshold_ratio": _round_or_none(normalized_threshold.get("ratio")),
            "threshold_delta": _round_or_none(normalized_threshold.get("delta")),
            "threshold_mode": threshold_mode,
            "threshold_candidates": candidates,
            "formula": (
                "price >= replayed percent/ATR historical threshold; "
                "sum contiguous profitable slices; floor to board lot"
            ),
        }
    )
    requested_quantity = _int(request.get("quantity"))
    if (
        replay_diverged
        and not duplicate_source
        and expected_quantity != requested_quantity
    ):
        expected["replay_quantity"] = expected_quantity
        expected["quantity"] = None
        reason_codes.append("inventory_history_uncertain")
        return "INSUFFICIENT_EVIDENCE"
    if expected_quantity != requested_quantity or duplicate_source:
        if expected_quantity != requested_quantity:
            _append_once(reason_codes, "requested_quantity_mismatch")
        return "FAIL"
    return "PASS"


def _actual_summary(actual_trades):
    filled_quantity = sum(max(_int(item.get("quantity")), 0) for item in actual_trades)
    amount = sum(
        max(_int(item.get("quantity")), 0) * (_positive_float(item.get("price")) or 0.0)
        for item in actual_trades
    )
    return {
        "requested_quantity": None,
        "filled_quantity": filled_quantity,
        "avg_filled_price": (
            round(amount / filled_quantity, 6) if filled_quantity > 0 else None
        ),
        "fill_count": len(actual_trades),
    }


def _execution_status(*, orders, requested_quantity, filled_quantity):
    if not orders:
        return "none"
    if filled_quantity <= 0:
        return "unfilled"
    if filled_quantity < requested_quantity:
        return "partial"
    return "filled"


def _consume_inventory(
    inventory,
    *,
    quantity,
    at_time,
    source_remaining=None,
):
    remaining = max(_int(quantity), 0)
    if remaining <= 0:
        return
    active = _active_inventory(inventory, at_time)
    if source_remaining:
        for source in source_remaining:
            if remaining <= 0:
                break
            entry_id = source["entry_id"]
            planned_remaining = source["remaining_quantity"]
            if planned_remaining <= 0:
                continue
            for item in active:
                if remaining <= 0 or planned_remaining <= 0:
                    break
                if item["entry_id"] != entry_id or item["remaining_quantity"] <= 0:
                    continue
                consumed = min(
                    item["remaining_quantity"],
                    remaining,
                    planned_remaining,
                )
                item["remaining_quantity"] -= consumed
                remaining -= consumed
                planned_remaining -= consumed
            source["remaining_quantity"] = planned_remaining
    if remaining <= 0:
        return
    for item in _active_inventory(inventory, at_time):
        if remaining <= 0:
            break
        consumed = min(item["remaining_quantity"], remaining)
        item["remaining_quantity"] -= consumed
        remaining -= consumed


def _source_plan(request):
    context = request.get("strategy_context")
    guardian = (
        context.get("guardian_sell_sources")
        if isinstance(context, dict)
        and isinstance(context.get("guardian_sell_sources"), dict)
        else {}
    )
    return [
        {
            "entry_id": str(item.get("entry_id") or "").strip(),
            "remaining_quantity": max(_int(item.get("quantity")), 0),
        }
        for item in list(guardian.get("entries") or [])
        if str(item.get("entry_id") or "").strip()
    ]


def _active_inventory(inventory, at_time):
    return sorted(
        [
            item
            for item in inventory
            if item["available_at"] <= at_time and item["remaining_quantity"] > 0
        ],
        key=lambda item: (
            item["guardian_price"],
            item["available_at"],
            item["entry_slice_id"],
        ),
    )


def _inventory_slice(
    entry,
    item,
    *,
    original_quantity,
    synthetic=False,
):
    entry_id = str(entry.get("entry_id") or "").strip()
    price = _positive_float(
        item.get("guardian_price") or item.get("sort_key") or entry.get("entry_price")
    )
    return {
        "entry_id": entry_id,
        "entry_slice_id": str(item.get("entry_slice_id") or "").strip(),
        "guardian_price": price or 0.0,
        "initial_quantity": int(original_quantity),
        "remaining_quantity": int(original_quantity),
        "available_at": _timestamp(
            entry.get("trade_time")
            or _date_time_text(entry.get("date"), entry.get("time"))
        ),
        "synthetic": bool(synthetic),
    }


def _index_pm_decisions(decisions):
    by_trace = {}
    by_intent = {}
    for item in decisions:
        trace_id = str(item.get("trace_id") or "").strip()
        intent_id = str(item.get("intent_id") or "").strip()
        if trace_id:
            by_trace[trace_id] = item
        if intent_id:
            by_intent[intent_id] = item
    return by_trace, by_intent


def _find_pm_decision(request, *, by_trace, by_intent):
    trace_id = str(request.get("trace_id") or "").strip()
    intent_id = str(request.get("intent_id") or "").strip()
    return by_trace.get(trace_id) or by_intent.get(intent_id)


def _association_quality(actual_trades):
    if not actual_trades:
        return "none"
    qualities = {
        str(item.get("association_quality") or "low").lower() for item in actual_trades
    }
    if qualities == {"high"}:
        return "high"
    if "ambiguous" in qualities or "low" in qualities:
        return "low"
    return "medium"


def _evidence_confidence(
    *,
    verdict,
    actual_trades,
    formula_evidence_complete,
):
    if verdict == "NOT_APPLICABLE":
        return "LOW"
    if not formula_evidence_complete:
        return "LOW"
    quality = _association_quality(actual_trades)
    if actual_trades and quality == "high":
        return "HIGH"
    if actual_trades and quality == "medium":
        return "MEDIUM"
    if not actual_trades:
        return "MEDIUM"
    return "LOW"


def _timestamp(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        return float(value)
    else:
        text = str(value).strip()
        if not text:
            return 0.0
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        if " " in text and "T" not in text:
            text = text.replace(" ", "T")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_BEIJING_TZ)
    return dt.astimezone(timezone.utc).timestamp()


def _iso_time(value) -> str | None:
    timestamp = _timestamp(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=_BEIJING_TZ).isoformat()


def _date_time_text(date_value, time_value):
    date_text = str(date_value or "").strip()
    if len(date_text) == 8 and date_text.isdigit():
        date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}"
    time_text = str(time_value or "00:00:00").strip()
    return f"{date_text}T{time_text}" if date_text else None


def _positive_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value, digits=8):
    parsed = _float_or_none(value)
    return round(parsed, digits) if parsed is not None else None


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _append_once(items, value):
    if value not in items:
        items.append(value)


__all__ = [
    "VERDICTS",
    "build_historical_sell_constraints",
    "build_historical_threshold_ratios",
    "reconstruct_inventory",
    "review_requests",
]
