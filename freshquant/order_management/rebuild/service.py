from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_entry,
    build_position_entry_from_trade_fact,
)

# Rebuild only needs stable Beijing wall-clock derivation, so use a fixed UTC+8
# offset instead of relying on system tzdata availability.
_BEIJING_TIMEZONE = timezone(timedelta(hours=8))
_BUY_ORDER_TYPES = {23, 27, "23", "27", "buy", "BUY"}
_SELL_ORDER_TYPES = {24, 31, "24", "31", "sell", "SELL"}
_DEFAULT_LOT_AMOUNT = 3000
_DEFAULT_GRID_INTERVAL = 1.03


class OrderLedgerV2RebuildService:
    def __init__(
        self,
        repository=None,
        *,
        lot_amount_lookup=None,
        grid_interval_lookup=None,
    ):
        self.repository = repository
        self.lot_amount_lookup = lot_amount_lookup or _default_lot_amount_lookup
        self.grid_interval_lookup = (
            grid_interval_lookup or _default_grid_interval_lookup
        )

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
        (
            position_entry_documents,
            entry_slice_documents,
            exit_allocation_documents,
            unmatched_sell_trade_facts,
            replay_warnings,
        ) = _rebuild_position_entries(
            broker_order_documents=broker_order_documents,
            execution_fill_documents=execution_fill_documents,
            lot_amount_lookup=self.lot_amount_lookup,
            grid_interval_lookup=self.grid_interval_lookup,
        )
        return {
            "broker_orders": len(broker_order_documents),
            "execution_fills": len(execution_fill_documents),
            "position_entries": len(position_entry_documents),
            "entry_slices": len(entry_slice_documents),
            "exit_allocations": len(exit_allocation_documents),
            "broker_order_documents": broker_order_documents,
            "execution_fill_documents": execution_fill_documents,
            "position_entry_documents": position_entry_documents,
            "entry_slice_documents": entry_slice_documents,
            "exit_allocation_documents": exit_allocation_documents,
            "unmatched_sell_trade_facts": unmatched_sell_trade_facts,
            "replay_warnings": replay_warnings,
        }


def _rebuild_position_entries(
    *,
    broker_order_documents,
    execution_fill_documents,
    lot_amount_lookup,
    grid_interval_lookup,
):
    execution_fills = _sort_execution_fills(execution_fill_documents)
    fills_by_broker_order_key = {}
    for execution_fill in execution_fills:
        fills_by_broker_order_key.setdefault(
            execution_fill["broker_order_key"], []
        ).append(execution_fill)

    position_entry_documents = []
    entry_slice_documents = []
    exit_allocation_documents = []
    unmatched_sell_trade_facts = []
    replay_warnings = []

    for broker_order in broker_order_documents:
        if broker_order.get("side") != "buy":
            continue
        broker_order_key = broker_order.get("broker_order_key")
        buy_fills = fills_by_broker_order_key.get(broker_order_key) or []
        if not buy_fills:
            continue

        trade_fact = _build_grouped_trade_fact(broker_order=broker_order, fills=buy_fills)
        position_entry = build_position_entry_from_trade_fact(
            trade_fact,
            source_ref_type="broker_order",
            source_ref_id=broker_order_key,
            entry_type="broker_execution_group",
            original_quantity=trade_fact["quantity"],
            remaining_quantity=trade_fact["quantity"],
            entry_price=trade_fact["price"],
            amount=round(float(trade_fact["price"]) * float(trade_fact["quantity"]), 2),
            source=trade_fact["source"],
            arrange_mode="runtime_grid",
            sell_history=[],
        )
        position_entry_documents.append(position_entry)
        entry_slice_documents.extend(
            arrange_entry(
                position_entry,
                lot_amount=int(lot_amount_lookup(position_entry["symbol"])),
                grid_interval=float(
                    grid_interval_lookup(position_entry["symbol"], trade_fact)
                ),
            )
        )

    for execution_fill in execution_fills:
        if execution_fill.get("side") != "sell":
            continue
        sell_trade_fact = _build_trade_fact_from_execution_fill(execution_fill)
        symbol = sell_trade_fact["symbol"]
        symbol_entries = [
            item
            for item in position_entry_documents
            if item.get("symbol") == symbol
            and int(item.get("remaining_quantity") or 0) > 0
        ]
        symbol_open_slices = [
            item
            for item in entry_slice_documents
            if item.get("symbol") == symbol
            and int(item.get("remaining_quantity") or 0) > 0
        ]
        if not symbol_entries or not symbol_open_slices:
            unmatched_sell_trade_facts.append(sell_trade_fact)
            replay_warnings.append(
                {
                    "code": "unmatched_sell",
                    "broker_order_key": execution_fill.get("broker_order_key"),
                    "execution_fill_id": execution_fill.get("execution_fill_id"),
                    "symbol": symbol,
                    "quantity": sell_trade_fact["quantity"],
                }
            )
            continue
        symbol_open_slices.sort(
            key=lambda item: (
                _coerce_float(item.get("sort_key")) or 0.0,
                _coerce_int(item.get("slice_seq")) or 0,
            ),
            reverse=True,
        )
        exit_allocation_documents.extend(
            allocate_sell_to_entry_slices(
                entries=symbol_entries,
                open_slices=symbol_open_slices,
                sell_trade_fact=sell_trade_fact,
            )
        )

    return (
        position_entry_documents,
        entry_slice_documents,
        exit_allocation_documents,
        unmatched_sell_trade_facts,
        replay_warnings,
    )


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


def _build_grouped_trade_fact(*, broker_order, fills):
    first_fill = fills[0]
    quantity = _coerce_int(broker_order.get("filled_quantity"))
    if quantity in {None, 0}:
        quantity = sum(_coerce_int(item.get("quantity")) or 0 for item in fills)
    price = _coerce_float(broker_order.get("avg_filled_price"))
    if price in {None, 0.0}:
        price = _weighted_average_fill_price(fills)
    trade_time = _coerce_int(broker_order.get("first_fill_time")) or _coerce_int(
        first_fill.get("trade_time")
    )
    date_value, time_value = _resolve_beijing_date_time(
        first_fill.get("date"),
        first_fill.get("time"),
        trade_time,
    )
    return {
        "trade_fact_id": first_fill.get("execution_fill_id")
        or first_fill.get("broker_trade_id")
        or f"rebuild-buy:{broker_order.get('broker_order_key')}",
        "symbol": broker_order.get("symbol") or first_fill.get("symbol"),
        "side": "buy",
        "quantity": quantity or 0,
        "price": price or 0.0,
        "trade_time": trade_time,
        "date": date_value,
        "time": time_value,
        "source": "broker_rebuild",
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


def _build_trade_fact_from_execution_fill(execution_fill):
    trade_time = _coerce_int(execution_fill.get("trade_time"))
    date_value, time_value = _resolve_beijing_date_time(
        execution_fill.get("date"),
        execution_fill.get("time"),
        trade_time,
    )
    return {
        "trade_fact_id": execution_fill.get("execution_fill_id")
        or execution_fill.get("broker_trade_id")
        or execution_fill.get("broker_order_key"),
        "symbol": execution_fill.get("symbol"),
        "side": execution_fill.get("side"),
        "quantity": _coerce_int(execution_fill.get("quantity")) or 0,
        "price": _coerce_float(execution_fill.get("price")) or 0.0,
        "trade_time": trade_time,
        "date": date_value,
        "time": time_value,
        "source": execution_fill.get("source") or "broker_rebuild",
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


def _sort_execution_fills(execution_fills):
    return sorted(
        execution_fills,
        key=lambda item: (
            _coerce_int(item.get("trade_time")) or 0,
            _coerce_int(item.get("date")) or 0,
            str(item.get("time") or ""),
            str(item.get("execution_fill_id") or ""),
        ),
    )


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


def _weighted_average_fill_price(fills):
    total_quantity = 0
    total_notional = 0.0
    for execution_fill in fills:
        quantity = _coerce_int(execution_fill.get("quantity")) or 0
        price = _coerce_float(execution_fill.get("price")) or 0.0
        total_quantity += quantity
        total_notional += quantity * price
    if total_quantity <= 0:
        return 0.0
    return round(total_notional / total_quantity, 6)


def _default_lot_amount_lookup(_symbol):
    return _DEFAULT_LOT_AMOUNT


def _default_grid_interval_lookup(_symbol, _trade_fact):
    return _DEFAULT_GRID_INTERVAL
