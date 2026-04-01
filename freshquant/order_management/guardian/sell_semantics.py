# -*- coding: utf-8 -*-

from freshquant.order_management.guardian.read_model import (
    build_arranged_fill_read_model,
)


def build_guardian_sell_source_entries(fill_list, *, quantity):
    remaining = int(quantity or 0)
    if remaining <= 0:
        return []

    source_entries = []
    for item in reversed(list(fill_list or [])):
        if remaining <= 0:
            break
        entry_id = str(item.get("entry_id") or "").strip()
        if not entry_id:
            continue
        available_quantity = int(item.get("quantity") or 0)
        if available_quantity <= 0:
            continue
        allocated_quantity = min(available_quantity, remaining)
        source_entries.append(
            {
                "entry_id": entry_id,
                "quantity": allocated_quantity,
            }
        )
        remaining -= allocated_quantity
    return source_entries


def resolve_guardian_sell_source_entries_from_open_slices(
    open_slices,
    *,
    exit_price,
    quantity,
):
    target_quantity = int(quantity or 0)
    try:
        target_price = float(exit_price or 0.0)
    except (TypeError, ValueError):
        return []
    if target_quantity <= 0 or target_price <= 0:
        return []

    fill_list = build_arranged_fill_read_model(open_slices or [])
    profitable_quantity = 0
    for item in reversed(fill_list):
        try:
            fill_price = float(item.get("price") or 0.0)
        except (TypeError, ValueError):
            break
        if target_price > fill_price:
            profitable_quantity += int(item.get("quantity") or 0)
            continue
        break

    if profitable_quantity < target_quantity:
        return []
    return build_guardian_sell_source_entries(fill_list, quantity=target_quantity)


def normalize_preferred_entry_quantities(
    preferred_entry_quantities,
    *,
    remaining_quantity,
):
    remaining = int(remaining_quantity or 0)
    if remaining <= 0:
        return []

    normalized = []
    for item in list(preferred_entry_quantities or []):
        if remaining <= 0:
            break
        entry_id = str((item or {}).get("entry_id") or "").strip()
        quantity = int((item or {}).get("quantity") or 0)
        if not entry_id or quantity <= 0:
            continue
        allocated_quantity = min(quantity, remaining)
        normalized.append(
            {
                "entry_id": entry_id,
                "quantity": allocated_quantity,
            }
        )
        remaining -= allocated_quantity
    return normalized
