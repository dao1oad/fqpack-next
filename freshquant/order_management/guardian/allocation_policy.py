# -*- coding: utf-8 -*-

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

        allocated_quantity = min(slice_document["remaining_quantity"], remaining_sell_quantity)
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
