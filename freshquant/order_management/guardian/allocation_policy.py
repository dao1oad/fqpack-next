# -*- coding: utf-8 -*-

from freshquant.order_management.guardian.sell_semantics import (
    normalize_preferred_entry_quantities,
)
from freshquant.order_management.ids import new_allocation_id


def allocate_sell_to_slices(buy_lots, open_slices, sell_trade_fact):
    remaining_sell_quantity = sell_trade_fact["quantity"]
    allocations = []
    buy_lot_by_id = {item["buy_lot_id"]: item for item in buy_lots}

    for slice_document in reversed(open_slices):
        if remaining_sell_quantity <= 0:
            break
        if slice_document["remaining_quantity"] <= 0:
            continue

        allocated_quantity = min(
            slice_document["remaining_quantity"], remaining_sell_quantity
        )
        slice_document["remaining_quantity"] -= allocated_quantity
        slice_document["remaining_amount"] = round(
            slice_document["guardian_price"] * slice_document["remaining_quantity"],
            2,
        )
        if slice_document["remaining_quantity"] == 0:
            slice_document["status"] = "closed"

        buy_lot = buy_lot_by_id[slice_document["buy_lot_id"]]
        buy_lot["remaining_quantity"] -= allocated_quantity
        if buy_lot["remaining_quantity"] == 0:
            buy_lot["status"] = "closed"
        else:
            buy_lot["status"] = "partial"

        allocation = {
            "allocation_id": new_allocation_id(),
            "sell_trade_fact_id": sell_trade_fact["trade_fact_id"],
            "buy_lot_id": slice_document["buy_lot_id"],
            "lot_slice_id": slice_document["lot_slice_id"],
            "guardian_price": slice_document["guardian_price"],
            "allocated_quantity": allocated_quantity,
        }
        allocations.append(allocation)
        buy_lot["sell_history"].append(allocation)
        remaining_sell_quantity -= allocated_quantity

    if remaining_sell_quantity > 0:
        raise ValueError("sell quantity exceeds open guardian slices")

    open_slices.sort(key=lambda item: item["sort_key"], reverse=True)
    return allocations


def allocate_sell_to_entry_slices(
    entries,
    open_slices,
    sell_trade_fact,
    *,
    preferred_entry_quantities=None,
):
    remaining_sell_quantity = sell_trade_fact["quantity"]
    allocations = []
    entry_by_id = {item["entry_id"]: item for item in entries}

    preferred_plan = normalize_preferred_entry_quantities(
        preferred_entry_quantities,
        remaining_quantity=remaining_sell_quantity,
    )
    if preferred_plan:
        remaining_sell_quantity = _allocate_preferred_entry_slices(
            allocations=allocations,
            entry_by_id=entry_by_id,
            open_slices=open_slices,
            remaining_sell_quantity=remaining_sell_quantity,
            preferred_plan=preferred_plan,
            sell_trade_fact=sell_trade_fact,
        )

    for slice_document in reversed(open_slices):
        if remaining_sell_quantity <= 0:
            break
        if slice_document["remaining_quantity"] <= 0:
            continue

        allocated_quantity = min(
            int(slice_document["remaining_quantity"] or 0), remaining_sell_quantity
        )
        slice_document["remaining_quantity"] = (
            int(slice_document["remaining_quantity"] or 0) - allocated_quantity
        )
        slice_document["remaining_amount"] = round(
            slice_document["guardian_price"] * slice_document["remaining_quantity"],
            2,
        )
        if slice_document["remaining_quantity"] == 0:
            slice_document["status"] = "CLOSED"

        entry = entry_by_id[slice_document["entry_id"]]
        entry["remaining_quantity"] -= allocated_quantity
        if entry["remaining_quantity"] == 0:
            entry["status"] = "CLOSED"
        else:
            entry["status"] = "PARTIALLY_EXITED"

        allocation = {
            "allocation_id": new_allocation_id(),
            "exit_trade_fact_id": sell_trade_fact["trade_fact_id"],
            "entry_id": slice_document["entry_id"],
            "entry_slice_id": slice_document["entry_slice_id"],
            "guardian_price": slice_document["guardian_price"],
            "allocated_quantity": allocated_quantity,
        }
        allocations.append(allocation)
        entry.setdefault("sell_history", []).append(allocation)
        remaining_sell_quantity -= allocated_quantity

    if remaining_sell_quantity > 0:
        raise ValueError("sell quantity exceeds open entry slices")

    open_slices.sort(key=lambda item: item["sort_key"], reverse=True)
    return allocations


def _allocate_preferred_entry_slices(
    *,
    allocations,
    entry_by_id,
    open_slices,
    remaining_sell_quantity,
    preferred_plan,
    sell_trade_fact,
):
    remaining = int(remaining_sell_quantity or 0)
    for source_entry in list(preferred_plan or []):
        entry_id = str(source_entry.get("entry_id") or "").strip()
        entry_remaining = int(source_entry.get("quantity") or 0)
        if remaining <= 0 or not entry_id or entry_remaining <= 0:
            continue
        for slice_document in reversed(open_slices):
            if remaining <= 0 or entry_remaining <= 0:
                break
            if str(slice_document.get("entry_id") or "").strip() != entry_id:
                continue
            if int(slice_document.get("remaining_quantity") or 0) <= 0:
                continue
            allocated_quantity = min(
                int(slice_document["remaining_quantity"] or 0),
                remaining,
                entry_remaining,
            )
            if allocated_quantity <= 0:
                continue
            _consume_entry_slice(
                allocations=allocations,
                entry_by_id=entry_by_id,
                slice_document=slice_document,
                sell_trade_fact=sell_trade_fact,
                allocated_quantity=allocated_quantity,
            )
            remaining -= allocated_quantity
            entry_remaining -= allocated_quantity
    return remaining


def _consume_entry_slice(
    *,
    allocations,
    entry_by_id,
    slice_document,
    sell_trade_fact,
    allocated_quantity,
):
    slice_document["remaining_quantity"] = int(
        slice_document.get("remaining_quantity") or 0
    ) - int(allocated_quantity or 0)
    slice_document["remaining_amount"] = round(
        float(slice_document.get("guardian_price") or 0.0)
        * int(slice_document["remaining_quantity"] or 0),
        2,
    )
    if int(slice_document["remaining_quantity"]) == 0:
        slice_document["status"] = "CLOSED"

    entry = entry_by_id[slice_document["entry_id"]]
    entry["remaining_quantity"] = int(entry.get("remaining_quantity") or 0) - int(
        allocated_quantity or 0
    )
    if int(entry["remaining_quantity"]) == 0:
        entry["status"] = "CLOSED"
    else:
        entry["status"] = "PARTIALLY_EXITED"

    allocation = {
        "allocation_id": new_allocation_id(),
        "exit_trade_fact_id": sell_trade_fact["trade_fact_id"],
        "entry_id": slice_document["entry_id"],
        "entry_slice_id": slice_document["entry_slice_id"],
        "guardian_price": slice_document["guardian_price"],
        "allocated_quantity": int(allocated_quantity or 0),
    }
    allocations.append(allocation)
    entry.setdefault("sell_history", []).append(allocation)
