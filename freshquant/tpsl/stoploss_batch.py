# -*- coding: utf-8 -*-

from __future__ import annotations

from uuid import uuid4

from freshquant.order_management.entry_adapter import list_open_entry_slices_compat


def build_stoploss_batch(
    *,
    repository,
    symbol,
    bid1,
    triggered_bindings,
    can_use_volume,
):
    normalized_symbol = _normalize_symbol(symbol)
    binding_map = {
        item["entry_id"]: item
        for item in (triggered_bindings or [])
        if item.get("entry_id")
    }
    if not binding_map:
        return _blocked_batch(normalized_symbol, "no_triggered_bindings")

    open_slices = list_open_entry_slices_compat(
        normalized_symbol,
        entry_ids=list(binding_map),
        repository=repository,
    )
    active_slices = [
        item
        for item in open_slices
        if int(item.get("remaining_quantity") or 0) > 0
        and item.get("entry_id") in binding_map
    ]
    if not active_slices:
        return _blocked_batch(normalized_symbol, "no_remaining_quantity")

    active_slices.sort(
        key=lambda item: (
            float(item.get("guardian_price") or 0.0),
            int(item.get("sort_key") or 0),
        ),
        reverse=True,
    )

    raw_cap = min(
        sum(int(item.get("remaining_quantity") or 0) for item in active_slices),
        max(int(can_use_volume or 0), 0),
    )
    order_quantity = _floor_to_board_lot(raw_cap)
    if order_quantity < 100:
        return _blocked_batch(normalized_symbol, "board_lot")

    remaining = order_quantity
    slice_quantities = {}
    entry_quantities = {}
    slice_details = []

    for slice_document in reversed(active_slices):
        if remaining <= 0:
            break
        allocatable = min(int(slice_document.get("remaining_quantity") or 0), remaining)
        if allocatable <= 0:
            continue
        slice_id = slice_document["entry_slice_id"]
        entry_id = slice_document["entry_id"]
        slice_quantities[slice_id] = allocatable
        entry_quantities[entry_id] = entry_quantities.get(entry_id, 0) + allocatable
        slice_details.append(
            {
                "entry_slice_id": slice_id,
                "entry_id": entry_id,
                "allocated_quantity": allocatable,
                "guardian_price": float(slice_document.get("guardian_price") or 0.0),
            }
        )
        remaining -= allocatable

    batch_id = _new_stoploss_batch_id()
    price = min(
        float(binding_map[entry_id]["stop_price"])
        for entry_id in entry_quantities
        if binding_map[entry_id].get("stop_price") is not None
    )
    return {
        "batch_id": batch_id,
        "status": "ready",
        "symbol": normalized_symbol,
        "bid1": float(bid1 or 0.0),
        "price": price,
        "quantity": order_quantity,
        "scope_type": "stoploss_batch",
        "scope_ref_id": batch_id,
        "source": "stoploss",
        "strategy_name": "PerEntryStoplossBatch",
        "remark": f"stoploss_batch:{normalized_symbol}",
        "entry_quantities": entry_quantities,
        "slice_quantities": slice_quantities,
        "slice_details": slice_details,
    }


def _new_stoploss_batch_id():
    return f"stoploss_batch_{uuid4().hex}"


def _normalize_symbol(symbol):
    text = str(symbol or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return text


def _floor_to_board_lot(quantity):
    value = max(int(quantity or 0), 0)
    return value - (value % 100)


def _blocked_batch(symbol, reason):
    return {
        "status": "blocked",
        "symbol": symbol,
        "blocked_reason": reason,
        "quantity": 0,
        "entry_quantities": {},
        "slice_quantities": {},
        "slice_details": [],
    }
