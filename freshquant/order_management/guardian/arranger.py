# -*- coding: utf-8 -*-

from freshquant.order_management.ids import new_buy_lot_id, new_lot_slice_id


def build_buy_lot_from_trade_fact(trade_fact):
    if trade_fact["side"] != "buy":
        raise ValueError("buy lot can only be built from buy trade fact")
    return {
        "buy_lot_id": new_buy_lot_id(),
        "origin_trade_fact_id": trade_fact["trade_fact_id"],
        "symbol": trade_fact["symbol"],
        "buy_price_real": trade_fact["price"],
        "original_quantity": trade_fact["quantity"],
        "remaining_quantity": trade_fact["quantity"],
        "amount": trade_fact.get(
            "amount",
            round(float(trade_fact["price"]) * float(trade_fact["quantity"]), 2),
        ),
        "amount_adjust": float(trade_fact.get("amount_adjust", 1.0)),
        "date": trade_fact.get("date"),
        "time": trade_fact.get("time"),
        "trade_time": trade_fact.get("trade_time"),
        "name": trade_fact.get("name", ""),
        "stock_code": trade_fact.get("stock_code"),
        "source": trade_fact.get("source", "order_management"),
        "arrange_mode": trade_fact.get("arrange_mode", "runtime_grid"),
        "sell_history": [],
        "status": "open",
    }


def arrange_buy_lot(buy_lot, lot_amount, grid_interval):
    slices = []
    _arrange_remaining(
        slices=slices,
        buy_lot=buy_lot,
        remaining_quantity=buy_lot["original_quantity"],
        remaining_amount=buy_lot["original_quantity"] * buy_lot["buy_price_real"],
        current_price=buy_lot["buy_price_real"],
        lot_amount=lot_amount,
        grid_interval=grid_interval,
        slice_seq=0,
    )
    return slices


def rebuild_guardian_position(trade_facts, lot_amount, grid_interval_lookup):
    buy_lots = []
    open_slices = []
    sell_allocations = []

    ordered_trade_facts = sorted(
        trade_facts,
        key=lambda item: (
            item.get("trade_time", 0),
            item.get("date", 0),
            item.get("time", ""),
        ),
    )

    for trade_fact in ordered_trade_facts:
        if trade_fact["side"] == "buy":
            buy_lot = build_buy_lot_from_trade_fact(trade_fact)
            buy_lots.append(buy_lot)
            slices = arrange_buy_lot(
                buy_lot,
                lot_amount=lot_amount,
                grid_interval=grid_interval_lookup(trade_fact["symbol"], trade_fact),
            )
            open_slices.extend(slices)
            open_slices.sort(key=lambda item: item["sort_key"], reverse=True)
        elif trade_fact["side"] == "sell":
            from freshquant.order_management.guardian.allocation_policy import (
                allocate_sell_to_slices,
            )

            sell_allocations.extend(
                allocate_sell_to_slices(
                    buy_lots=buy_lots,
                    open_slices=open_slices,
                    sell_trade_fact=trade_fact,
                )
            )

    return {
        "buy_lots": buy_lots,
        "open_slices": [item for item in open_slices if item["remaining_quantity"] > 0],
        "sell_allocations": sell_allocations,
    }


def _arrange_remaining(
    slices,
    buy_lot,
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

    slice_document = {
        "lot_slice_id": new_lot_slice_id(),
        "buy_lot_id": buy_lot["buy_lot_id"],
        "slice_seq": slice_seq,
        "guardian_price": float(f"{current_price:.2f}"),
        "original_quantity": quantity,
        "remaining_quantity": quantity,
        "remaining_amount": round(float(f"{current_price:.2f}") * quantity, 2),
        "sort_key": float(f"{current_price:.2f}"),
        "date": buy_lot.get("date"),
        "time": buy_lot.get("time"),
        "symbol": buy_lot["symbol"],
        "status": "open",
    }
    _insert_slice_desc(slices, slice_document)

    next_quantity = remaining_quantity - quantity
    if next_quantity <= 0:
        return

    next_amount = remaining_amount - quantity * float(f"{current_price:.2f}")
    next_price = float(f"{(current_price * grid_interval):.2f}")
    _arrange_remaining(
        slices=slices,
        buy_lot=buy_lot,
        remaining_quantity=next_quantity,
        remaining_amount=next_amount,
        current_price=next_price,
        lot_amount=lot_amount,
        grid_interval=grid_interval,
        slice_seq=slice_seq + 1,
    )


def _insert_slice_desc(slices, slice_document):
    for index, current in enumerate(slices):
        if current["guardian_price"] < slice_document["guardian_price"]:
            slices.insert(index, slice_document)
            return
    slices.append(slice_document)
