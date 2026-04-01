# -*- coding: utf-8 -*-


def build_arranged_fill_read_model(open_slices):
    active_slices = list_active_open_slices(open_slices)
    rows = []
    for item in active_slices:
        row = {
            "symbol": item["symbol"],
            "date": item.get("date"),
            "time": item.get("time"),
            "price": item["guardian_price"],
            "quantity": item["remaining_quantity"],
            "amount": round(item["guardian_price"] * item["remaining_quantity"], 2),
        }
        entry_id = str(item.get("entry_id") or "").strip()
        if entry_id:
            row["entry_id"] = entry_id
        entry_slice_id = str(item.get("entry_slice_id") or "").strip()
        if entry_slice_id:
            row["entry_slice_id"] = entry_slice_id
        rows.append(row)
    return rows


def list_active_open_slices(open_slices):
    active_slices = [item for item in open_slices if item["remaining_quantity"] > 0]
    active_slices.sort(key=lambda item: item["sort_key"], reverse=True)
    return active_slices


def list_profitable_open_slices(open_slices, *, exit_price):
    active_slices = list_active_open_slices(open_slices)
    profitable_slices = [
        item
        for item in active_slices
        if float(item["guardian_price"]) < float(exit_price)
    ]
    profitable_slices.sort(
        key=lambda item: (float(item["guardian_price"]), item.get("sort_key", 0))
    )
    return profitable_slices
