from __future__ import annotations

from datetime import datetime, timedelta, timezone


# Rebuild only needs stable Beijing wall-clock derivation, so use a fixed UTC+8
# offset instead of relying on system tzdata availability.
_BEIJING_TIMEZONE = timezone(timedelta(hours=8))
_BUY_ORDER_TYPES = {23, 27, "23", "27", "buy", "BUY"}
_SELL_ORDER_TYPES = {24, 31, "24", "31", "sell", "SELL"}


class OrderLedgerV2RebuildService:
    def __init__(self, repository=None):
        self.repository = repository

    def build_from_truth(
        self,
        *,
        xt_orders=None,
        xt_trades=None,
        xt_positions=None,
        now_ts=None,
    ):
        del xt_positions, now_ts

        broker_orders_by_key = {}
        broker_order_keys = []
        order_id_to_broker_order_key = {}

        for raw_order in list(xt_orders or []):
            broker_order = _normalize_broker_order(raw_order)
            broker_order_key = broker_order["broker_order_key"]
            if broker_order_key not in broker_orders_by_key:
                broker_order_keys.append(broker_order_key)
            broker_orders_by_key[broker_order_key] = broker_order
            order_id = _normalize_identifier(raw_order.get("order_id"))
            if order_id:
                order_id_to_broker_order_key[order_id] = broker_order_key

        execution_fill_documents = []
        for raw_trade in list(xt_trades or []):
            order_id = _normalize_identifier(raw_trade.get("order_id"))
            broker_order_key = order_id_to_broker_order_key.get(order_id) or order_id
            if not broker_order_key:
                broker_order_key = f"trade_only:{_normalize_identifier(raw_trade.get('traded_id'))}"

            broker_order = broker_orders_by_key.get(broker_order_key)
            if broker_order is None:
                broker_order = _build_trade_only_broker_order(raw_trade, broker_order_key)
                broker_orders_by_key[broker_order_key] = broker_order
                broker_order_keys.append(broker_order_key)
                if order_id:
                    order_id_to_broker_order_key[order_id] = broker_order_key

            execution_fill = _normalize_execution_fill(raw_trade, broker_order)
            execution_fill_documents.append(execution_fill)
            _apply_execution_fill_to_broker_order(broker_order, execution_fill)

        broker_order_documents = [
            broker_orders_by_key[broker_order_key] for broker_order_key in broker_order_keys
        ]
        return {
            "broker_orders": len(broker_order_documents),
            "execution_fills": len(execution_fill_documents),
            "broker_order_documents": broker_order_documents,
            "execution_fill_documents": execution_fill_documents,
        }


def _normalize_broker_order(raw_order):
    broker_order_id = _normalize_identifier(raw_order.get("order_id"))
    requested_quantity = _coerce_int(
        raw_order.get("order_volume") or raw_order.get("quantity")
    )
    return {
        "broker_order_key": broker_order_id,
        "broker_order_id": broker_order_id,
        "broker_order_type": raw_order.get("order_type"),
        "symbol": _normalize_symbol(raw_order),
        "side": _normalize_side(raw_order.get("order_type") or raw_order.get("side")),
        "state": _normalize_broker_order_state(raw_order.get("order_status")),
        "source_type": "broker_rebuild",
        "requested_quantity": requested_quantity,
        "filled_quantity": 0,
        "avg_filled_price": None,
        "fill_count": 0,
        "first_fill_time": None,
        "last_fill_time": None,
    }


def _build_trade_only_broker_order(raw_trade, broker_order_key):
    broker_order_id = _normalize_identifier(raw_trade.get("order_id")) or broker_order_key
    return {
        "broker_order_key": broker_order_key,
        "broker_order_id": broker_order_id,
        "broker_order_type": raw_trade.get("order_type"),
        "symbol": _normalize_symbol(raw_trade),
        "side": _normalize_side(raw_trade.get("order_type") or raw_trade.get("side")),
        "state": "PARTIAL_FILLED",
        "source_type": "trade_only",
        "requested_quantity": None,
        "filled_quantity": 0,
        "avg_filled_price": None,
        "fill_count": 0,
        "first_fill_time": None,
        "last_fill_time": None,
    }


def _normalize_execution_fill(raw_trade, broker_order):
    trade_time = _coerce_int(raw_trade.get("traded_time") or raw_trade.get("trade_time"))
    date_value, time_value = _resolve_beijing_date_time(
        raw_trade.get("date"),
        raw_trade.get("time"),
        trade_time,
    )
    return {
        "execution_fill_id": _normalize_identifier(raw_trade.get("traded_id")),
        "broker_trade_id": _normalize_identifier(raw_trade.get("traded_id")),
        "broker_order_key": broker_order["broker_order_key"],
        "broker_order_id": broker_order.get("broker_order_id"),
        "symbol": broker_order.get("symbol") or _normalize_symbol(raw_trade),
        "side": broker_order.get("side")
        or _normalize_side(raw_trade.get("order_type") or raw_trade.get("side")),
        "quantity": _coerce_int(
            raw_trade.get("traded_volume") or raw_trade.get("quantity")
        ),
        "price": _coerce_float(raw_trade.get("traded_price") or raw_trade.get("price")),
        "trade_time": trade_time,
        "date": date_value,
        "time": time_value,
        "source": "broker_rebuild",
    }


def _apply_execution_fill_to_broker_order(broker_order, execution_fill):
    previous_quantity = _coerce_int(broker_order.get("filled_quantity")) or 0
    previous_fill_count = _coerce_int(broker_order.get("fill_count")) or 0
    previous_avg_price = _coerce_float(broker_order.get("avg_filled_price")) or 0.0
    fill_quantity = _coerce_int(execution_fill.get("quantity")) or 0
    fill_price = _coerce_float(execution_fill.get("price")) or 0.0

    next_quantity = previous_quantity + fill_quantity
    next_fill_count = previous_fill_count + 1
    previous_notional = previous_quantity * previous_avg_price
    next_avg_price = None
    if next_quantity > 0:
        next_avg_price = round(
            (previous_notional + fill_quantity * fill_price) / next_quantity,
            6,
        )

    broker_order["filled_quantity"] = next_quantity
    broker_order["avg_filled_price"] = next_avg_price
    broker_order["fill_count"] = next_fill_count
    broker_order["first_fill_time"] = _pick_first_time(
        broker_order.get("first_fill_time"),
        execution_fill.get("trade_time"),
    )
    broker_order["last_fill_time"] = _pick_last_time(
        broker_order.get("last_fill_time"),
        execution_fill.get("trade_time"),
    )
    broker_order["state"] = _resolve_fill_state(
        requested_quantity=broker_order.get("requested_quantity"),
        filled_quantity=next_quantity,
    )


def _normalize_symbol(payload):
    symbol = str(payload.get("symbol") or "").strip()
    if symbol:
        return symbol
    stock_code = str(payload.get("stock_code") or "").strip()
    if "." in stock_code:
        return stock_code.split(".", 1)[0]
    return stock_code


def _normalize_side(order_type):
    if order_type in _BUY_ORDER_TYPES:
        return "buy"
    if order_type in _SELL_ORDER_TYPES:
        return "sell"
    return str(order_type or "").strip().lower() or None


def _normalize_broker_order_state(order_status):
    state_value = str(order_status or "").strip().lower()
    if state_value in {"filled", "alltraded"}:
        return "FILLED"
    if state_value in {"partfilled", "partial_filled", "partial-filled"}:
        return "PARTIAL_FILLED"
    if state_value in {"canceled", "cancelled"}:
        return "CANCELED"
    return "OPEN"


def _resolve_fill_state(*, requested_quantity, filled_quantity):
    requested_quantity = _coerce_int(requested_quantity)
    filled_quantity = _coerce_int(filled_quantity) or 0
    if requested_quantity not in {None, 0} and filled_quantity >= requested_quantity:
        return "FILLED"
    return "PARTIAL_FILLED" if filled_quantity > 0 else "OPEN"


def _resolve_beijing_date_time(date_value, time_value, trade_time):
    if date_value not in {None, ""} and time_value not in {None, ""}:
        return date_value, time_value
    if trade_time in {None, ""}:
        return date_value, time_value
    trade_datetime = datetime.fromtimestamp(int(trade_time), tz=_BEIJING_TIMEZONE)
    return int(trade_datetime.strftime("%Y%m%d")), trade_datetime.strftime("%H:%M:%S")


def _normalize_identifier(value):
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_int(value):
    if value in {None, ""}:
        return None
    return int(value)


def _coerce_float(value):
    if value in {None, ""}:
        return None
    return float(value)


def _pick_first_time(previous, current):
    if previous in {None, ""}:
        return current
    if current in {None, ""}:
        return previous
    return min(previous, current)


def _pick_last_time(previous, current):
    if previous in {None, ""}:
        return current
    if current in {None, ""}:
        return previous
    return max(previous, current)
