# -*- coding: utf-8 -*-

from __future__ import annotations


def build_reconciliation_summary_map(
    gap_rows,
    *,
    rejection_rows=None,
    normalize_symbol=None,
):
    symbol_normalizer = normalize_symbol or (lambda value: value)
    grouped = {}

    for gap in list(gap_rows or []):
        symbol = symbol_normalizer(gap.get("symbol"))
        if not symbol:
            continue
        grouped.setdefault(symbol, {"gap_rows": [], "rejection_count": 0})[
            "gap_rows"
        ].append(dict(gap))

    for rejection in list(rejection_rows or []):
        symbol = symbol_normalizer(rejection.get("symbol"))
        if not symbol:
            continue
        grouped.setdefault(symbol, {"gap_rows": [], "rejection_count": 0})[
            "rejection_count"
        ] += 1

    return {
        symbol: summarize_symbol_reconciliation(
            symbol=symbol,
            gap_rows=payload["gap_rows"],
            rejection_count=payload["rejection_count"],
        )
        for symbol, payload in grouped.items()
    }


def summarize_symbol_reconciliation(
    *,
    symbol,
    gap_rows,
    rejection_count=0,
    broker_quantity=None,
    ledger_quantity=None,
    include_rows=False,
):
    normalized_rows = list(gap_rows or [])
    signed_gap_quantity = 0
    open_gap_count = 0
    rejected_gap_count = 0
    latest_gap_state = ""
    latest_resolution_type = None
    latest_sort_value = -1
    rows = []

    for item in normalized_rows:
        side = str(item.get("side") or "").strip().lower()
        state = str(item.get("state") or "").strip().upper()
        quantity_delta = int(item.get("quantity_delta") or 0)
        if state in {"OPEN", "REJECTED"}:
            open_gap_count += 1
            signed_gap_quantity += quantity_delta if side == "buy" else -quantity_delta
        if state == "REJECTED":
            rejected_gap_count += 1
        sort_value = int(
            item.get("confirmed_at")
            or item.get("dismissed_at")
            or item.get("pending_until")
            or item.get("detected_at")
            or 0
        )
        if sort_value >= latest_sort_value:
            latest_sort_value = sort_value
            latest_gap_state = state
            latest_resolution_type = _normalize_optional_text(
                item.get("resolution_type")
            )
        if include_rows:
            rows.append(
                {
                    "gap_id": item.get("gap_id"),
                    "side": side,
                    "state": str(item.get("state") or ""),
                    "quantity_delta": quantity_delta,
                    "pending_until": item.get("pending_until"),
                    "resolution_type": item.get("resolution_type"),
                }
            )

    derived_signed_gap = None
    if broker_quantity is not None or ledger_quantity is not None:
        derived_signed_gap = int(broker_quantity or 0) - int(ledger_quantity or 0)
    effective_signed_gap = (
        signed_gap_quantity
        if normalized_rows
        else (derived_signed_gap if derived_signed_gap is not None else 0)
    )

    if open_gap_count > 0:
        summary_state = (
            "BROKEN"
            if latest_gap_state == "REJECTED" or int(rejection_count or 0) > 0
            else "OBSERVING"
        )
    elif latest_gap_state in {"AUTO_OPENED", "AUTO_CLOSED", "MATCHED"}:
        summary_state = "AUTO_RECONCILED"
    elif effective_signed_gap == 0:
        summary_state = "ALIGNED"
    else:
        summary_state = "DRIFT"

    result = {
        "symbol": symbol,
        "state": summary_state,
        "latest_gap_state": latest_gap_state or summary_state,
        "signed_gap_quantity": effective_signed_gap,
        "open_gap_count": open_gap_count,
        "latest_resolution_type": latest_resolution_type,
        "ingest_rejection_count": int(rejection_count or 0),
    }
    if broker_quantity is not None or ledger_quantity is not None:
        result.update(
            {
                "broker_quantity": int(broker_quantity or 0),
                "ledger_quantity": int(ledger_quantity or 0),
                "rejected_gap_count": rejected_gap_count,
            }
        )
    if include_rows:
        result["rows"] = rows
    return result


def _normalize_optional_text(value):
    text = str(value or "").strip()
    return text or None
