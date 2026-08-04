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


def resolve_takeprofit_sell_quantity(
    *,
    open_slices,
    tier_price,
    level,
    total_position_quantity,
    can_use_volume,
):
    ratio = {1: 1 / 3, 2: 1 / 2, 3: 1}.get(int(level))
    if ratio is None:
        return {
            "quantity": 0,
            "slice_quantities": {},
            "entry_quantities": {},
            "profit_slices": [],
        }
    ratio_target = (
        int(total_position_quantity)
        if ratio == 1
        else int(int(total_position_quantity) * ratio)
    )
    ledger_total = sum(
        max(int(item.get("remaining_quantity") or 0), 0) for item in open_slices or []
    )
    quantity_cap = min(
        max(ratio_target, 0), ledger_total, max(int(can_use_volume or 0), 0)
    )
    profitable_slices = list_profitable_open_slices(open_slices, exit_price=tier_price)
    other_slices = [
        item
        for item in (open_slices or [])
        if item not in profitable_slices
        and int(item.get("remaining_quantity") or 0) > 0
    ]
    other_slices.sort(
        key=lambda item: (
            -int(item.get("remaining_quantity") or 0),
            item.get("sort_key", 0),
            item.get("entry_slice_id") or item.get("lot_slice_id") or "",
        )
    )
    slice_quantities = {}
    entry_quantities = {}
    quantity = 0

    selected = profitable_slices + other_slices
    for slice_document in selected:
        if quantity >= quantity_cap:
            break
        remaining_quantity = int(slice_document.get("remaining_quantity") or 0)
        if remaining_quantity <= 0:
            continue
        slice_id = slice_document.get("entry_slice_id") or slice_document.get(
            "lot_slice_id"
        )
        entry_id = slice_document.get("entry_id") or slice_document.get("buy_lot_id")
        if not slice_id or not entry_id:
            continue
        allocated = min(remaining_quantity, quantity_cap - quantity)
        slice_quantities[slice_id] = allocated
        entry_quantities[entry_id] = entry_quantities.get(entry_id, 0) + allocated
        quantity += allocated

    return {
        "quantity": quantity,
        "slice_quantities": slice_quantities,
        "entry_quantities": entry_quantities,
        "profit_slices": selected,
        "ratio_target": ratio_target,
        "ledger_total_quantity": ledger_total,
        "can_use_volume": int(can_use_volume or 0),
    }
