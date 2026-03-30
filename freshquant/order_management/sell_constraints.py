from __future__ import annotations

from freshquant.util.code import normalize_to_base_code


class PositionVolumeReader:
    def __init__(self, database):
        self.database = database

    def get_can_use_volume(self, symbol):
        base_symbol = _normalize_symbol(symbol)
        for doc in self.database["xt_positions"].find(
            {},
            {
                "stock_code": 1,
                "code": 1,
                "symbol": 1,
                "can_use_volume": 1,
                "volume": 1,
            },
        ):
            raw = doc.get("stock_code") or doc.get("code") or doc.get("symbol") or ""
            if _normalize_symbol(raw) != base_symbol:
                continue

            volume = _parse_non_negative_int(
                doc.get("volume"),
                field_name="xt_positions volume",
                symbol=raw,
                default=0,
            )
            if doc.get("can_use_volume") in (None, ""):
                return volume

            can_use_volume = _parse_non_negative_int(
                doc.get("can_use_volume"),
                field_name="xt_positions can_use_volume",
                symbol=raw,
                default=0,
            )
            if volume > 0:
                return min(can_use_volume, volume)
            return can_use_volume
        return 0


def floor_to_board_lot(quantity):
    value = max(int(quantity or 0), 0)
    return value - (value % 100)


def resolve_sell_submission_quantity(*, requested_quantity, can_use_volume):
    raw_quantity = max(int(requested_quantity or 0), 0)
    sell_cap = max(int(can_use_volume or 0), 0)
    quantity_cap = min(raw_quantity, sell_cap)
    submit_quantity = floor_to_board_lot(quantity_cap)

    if raw_quantity <= 0:
        return {
            "status": "blocked",
            "blocked_reason": "quantity",
            "raw_quantity": raw_quantity,
            "can_use_volume": sell_cap,
            "quantity_cap": quantity_cap,
            "quantity": 0,
        }
    if sell_cap <= 0:
        return {
            "status": "blocked",
            "blocked_reason": "can_use_volume",
            "raw_quantity": raw_quantity,
            "can_use_volume": sell_cap,
            "quantity_cap": quantity_cap,
            "quantity": 0,
        }
    if submit_quantity < 100:
        return {
            "status": "blocked",
            "blocked_reason": "board_lot",
            "raw_quantity": raw_quantity,
            "can_use_volume": sell_cap,
            "quantity_cap": quantity_cap,
            "quantity": 0,
        }
    return {
        "status": "ready",
        "blocked_reason": None,
        "raw_quantity": raw_quantity,
        "can_use_volume": sell_cap,
        "quantity_cap": quantity_cap,
        "quantity": submit_quantity,
    }


def _normalize_symbol(symbol):
    return normalize_to_base_code(str(symbol or ""))


def _parse_non_negative_int(value, *, field_name, symbol, default):
    if value in (None, ""):
        return int(default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} invalid for {symbol or '-'}: {value!r}"
        ) from exc
    if parsed < 0:
        raise ValueError(f"{field_name} invalid for {symbol or '-'}: {value!r}")
    return parsed
