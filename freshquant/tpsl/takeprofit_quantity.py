# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.order_management.guardian.read_model import list_profitable_open_slices


def choose_takeprofit_level(*, ask1, tiers, armed_levels):
    try:
        ask_price = float(ask1 or 0.0)
    except Exception:
        return None
    if ask_price <= 0:
        return None

    eligible = []
    for raw in tiers or []:
        level = int(raw["level"])
        try:
            tier_price = float(raw["price"])
        except Exception:
            continue
        if tier_price <= 0:
            continue
        if not bool(raw.get("manual_enabled", True)):
            continue
        armed = (armed_levels or {}).get(level)
        if armed is None:
            armed = (armed_levels or {}).get(str(level))
        if not bool(armed):
            continue
        if ask_price >= tier_price:
            eligible.append(
                {
                    "level": level,
                    "price": tier_price,
                    "manual_enabled": bool(raw.get("manual_enabled", True)),
                }
            )

    if not eligible:
        return None
    return max(eligible, key=lambda item: (item["price"], item["level"]))


def resolve_takeprofit_sell_quantity(*, open_slices, tier_price):
    profitable_slices = list_profitable_open_slices(open_slices, exit_price=tier_price)
    slice_quantities = {}
    entry_quantities = {}
    quantity = 0

    for slice_document in profitable_slices:
        remaining_quantity = int(slice_document.get("remaining_quantity") or 0)
        if remaining_quantity <= 0:
            continue
        slice_id = slice_document.get("entry_slice_id") or slice_document.get(
            "lot_slice_id"
        )
        entry_id = slice_document.get("entry_id") or slice_document.get("buy_lot_id")
        if not slice_id or not entry_id:
            continue
        slice_quantities[slice_id] = remaining_quantity
        entry_quantities[entry_id] = (
            entry_quantities.get(entry_id, 0) + remaining_quantity
        )
        quantity += remaining_quantity

    return {
        "quantity": quantity,
        "slice_quantities": slice_quantities,
        "entry_quantities": entry_quantities,
        "profit_slices": profitable_slices,
    }
