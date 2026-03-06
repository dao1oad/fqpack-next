# -*- coding: utf-8 -*-


def build_arranged_fill_read_model(open_slices):
    active_slices = [item for item in open_slices if item["remaining_quantity"] > 0]
    active_slices.sort(key=lambda item: item["sort_key"], reverse=True)
    return [
        {
            "symbol": item["symbol"],
            "date": item.get("date"),
            "time": item.get("time"),
            "price": item["guardian_price"],
            "quantity": item["remaining_quantity"],
            "amount": round(item["guardian_price"] * item["remaining_quantity"], 2),
        }
        for item in active_slices
    ]
