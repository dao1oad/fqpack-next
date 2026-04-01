from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freshquant.order_management.entry_aggregation import (
    build_clustered_position_entry,
    count_clustered_entries,
    count_non_default_lot_slices,
    entry_requires_slice_rebuild,
    select_cluster_entry,
    summarize_mergeable_gap,
)
from freshquant.order_management.guardian.allocation_policy import (
    allocate_sell_to_entry_slices,
)
from freshquant.order_management.guardian.arranger import (
    arrange_entry,
    build_position_entry_from_trade_fact,
)
from freshquant.order_management.ids import (
    new_reconciliation_gap_id,
    new_reconciliation_resolution_id,
    new_trade_fact_id,
)

# Rebuild only needs stable Beijing wall-clock derivation, so use a fixed UTC+8
# offset instead of relying on system tzdata availability.
_BEIJING_TIMEZONE = timezone(timedelta(hours=8))
_BUY_ORDER_TYPES = {23, 27, "23", "27", "buy", "BUY"}
_SELL_ORDER_TYPES = {24, 31, "24", "31", "sell", "SELL"}
_DEFAULT_LOT_AMOUNT = 50000
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
        allow_empty_xt_positions_flatten=False,
    ):
        rebuild_ts = _resolve_rebuild_timestamp(now_ts)
        xt_orders = list(xt_orders or [])
        xt_trades = list(xt_trades or [])
        xt_positions = list(xt_positions or []) if xt_positions is not None else None

        broker_orders_by_key = {}
        broker_order_keys = []
        order_match_to_broker_order_key = {}

        for raw_order in xt_orders:
            broker_order = _normalize_broker_order(raw_order)
            broker_order_key = broker_order["broker_order_key"]
            if broker_order_key not in broker_orders_by_key:
                broker_order_keys.append(broker_order_key)
            broker_orders_by_key[broker_order_key] = broker_order
            match_key = _build_broker_order_match_key(
                symbol=broker_order.get("symbol"),
                side=broker_order.get("side"),
                order_id=raw_order.get("order_id"),
            )
            if match_key:
                order_match_to_broker_order_key[match_key] = broker_order_key

        execution_fill_documents = []
        for raw_trade in xt_trades:
            order_id = _normalize_identifier(raw_trade.get("order_id"))
            trade_symbol = _normalize_symbol(raw_trade)
            trade_side = _normalize_side(
                raw_trade.get("order_type") or raw_trade.get("side")
            )
            match_key = _build_broker_order_match_key(
                symbol=trade_symbol,
                side=trade_side,
                order_id=order_id,
            )
            broker_order_key = order_match_to_broker_order_key.get(match_key)
            if not broker_order_key:
                broker_order_key = _build_trade_only_broker_order_key(
                    symbol=trade_symbol,
                    side=trade_side,
                    order_id=order_id,
                    traded_id=raw_trade.get("traded_id"),
                )

            broker_order = broker_orders_by_key.get(broker_order_key)
            if broker_order is None:
                broker_order = _build_trade_only_broker_order(
                    raw_trade, broker_order_key
                )
                broker_orders_by_key[broker_order_key] = broker_order
                broker_order_keys.append(broker_order_key)
                if match_key:
                    order_match_to_broker_order_key[match_key] = broker_order_key

            execution_fill = _normalize_execution_fill(raw_trade, broker_order)
            execution_fill_documents.append(execution_fill)
            _apply_execution_fill_to_broker_order(broker_order, execution_fill)

        broker_order_documents = [
            broker_orders_by_key[broker_order_key]
            for broker_order_key in broker_order_keys
        ]
        (
            position_entry_documents,
            entry_slice_documents,
            exit_allocation_documents,
            unmatched_sell_trade_facts,
            replay_warnings,
            ingest_rejection_documents,
        ) = _rebuild_position_entries(
            broker_order_documents=broker_order_documents,
            execution_fill_documents=execution_fill_documents,
            lot_amount_lookup=self.lot_amount_lookup,
            grid_interval_lookup=self.grid_interval_lookup,
        )
        (
            reconciliation_gap_documents,
            reconciliation_resolution_documents,
            auto_open_entries,
            auto_close_allocations,
            reconciliation_ingest_rejections,
        ) = _reconcile_positions_against_xt_positions(
            xt_positions=xt_positions,
            now_ts=rebuild_ts,
            position_entry_documents=position_entry_documents,
            entry_slice_documents=entry_slice_documents,
            exit_allocation_documents=exit_allocation_documents,
            lot_amount_lookup=self.lot_amount_lookup,
            grid_interval_lookup=self.grid_interval_lookup,
            allow_empty_xt_positions_flatten=allow_empty_xt_positions_flatten,
        )
        ingest_rejection_documents.extend(reconciliation_ingest_rejections)
        return {
            "broker_orders": len(broker_order_documents),
            "execution_fills": len(execution_fill_documents),
            "position_entries": len(position_entry_documents),
            "entry_slices": len(entry_slice_documents),
            "exit_allocations": len(exit_allocation_documents),
            "reconciliation_gaps": len(reconciliation_gap_documents),
            "reconciliation_resolutions": len(reconciliation_resolution_documents),
            "auto_open_entries": auto_open_entries,
            "auto_close_allocations": auto_close_allocations,
            "ingest_rejections": len(ingest_rejection_documents),
            "broker_order_documents": broker_order_documents,
            "execution_fill_documents": execution_fill_documents,
            "position_entry_documents": position_entry_documents,
            "entry_slice_documents": entry_slice_documents,
            "exit_allocation_documents": exit_allocation_documents,
            "reconciliation_gap_documents": reconciliation_gap_documents,
            "reconciliation_resolution_documents": reconciliation_resolution_documents,
            "ingest_rejection_documents": ingest_rejection_documents,
            "unmatched_sell_trade_facts": unmatched_sell_trade_facts,
            "replay_warnings": replay_warnings,
            "clustered_entries": count_clustered_entries(position_entry_documents),
            "mergeable_entry_gap": summarize_mergeable_gap(position_entry_documents),
            "non_default_lot_slices": _count_non_default_lot_slices_with_lookup(
                entry_slice_documents,
                lot_amount_lookup=self.lot_amount_lookup,
            ),
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
    ingest_rejection_documents = []

    replay_events = []
    for broker_order in broker_order_documents:
        if broker_order.get("side") != "buy":
            continue
        broker_order_key = broker_order.get("broker_order_key")
        accepted_buy_fills = []
        for execution_fill in fills_by_broker_order_key.get(broker_order_key) or []:
            if not _is_board_lot_quantity(execution_fill.get("quantity")):
                ingest_rejection_documents.append(
                    _build_ingest_rejection_from_execution_fill(execution_fill)
                )
                continue
            accepted_buy_fills.append(execution_fill)
        if not accepted_buy_fills:
            continue

        trade_fact = _build_grouped_trade_fact(
            broker_order=_build_entry_broker_order(
                broker_order=broker_order,
                fills=accepted_buy_fills,
            ),
            fills=accepted_buy_fills,
        )
        replay_events.append(
            {
                "kind": "buy_group",
                "trade_time": trade_fact.get("trade_time"),
                "date": trade_fact.get("date"),
                "time": trade_fact.get("time"),
                "sort_id": trade_fact.get("trade_fact_id"),
                "broker_order_key": broker_order_key,
                "trade_fact": trade_fact,
            }
        )

    for execution_fill in execution_fills:
        if execution_fill.get("side") != "sell":
            continue
        if not _is_board_lot_quantity(execution_fill.get("quantity")):
            ingest_rejection_documents.append(
                _build_ingest_rejection_from_execution_fill(execution_fill)
            )
            continue
        sell_trade_fact = _build_trade_fact_from_execution_fill(execution_fill)
        replay_events.append(
            {
                "kind": "sell_fill",
                "trade_time": sell_trade_fact.get("trade_time"),
                "date": sell_trade_fact.get("date"),
                "time": sell_trade_fact.get("time"),
                "sort_id": sell_trade_fact.get("trade_fact_id"),
                "execution_fill": execution_fill,
                "trade_fact": sell_trade_fact,
            }
        )

    replay_events.sort(
        key=lambda item: (
            _coerce_int(item.get("trade_time")) or 0,
            _coerce_int(item.get("date")) or 0,
            str(item.get("time") or ""),
            0 if item.get("kind") == "buy_group" else 1,
            str(item.get("sort_id") or ""),
        )
    )

    for replay_event in replay_events:
        if replay_event.get("kind") == "buy_group":
            trade_fact = dict(replay_event["trade_fact"])
            existing_entry = select_cluster_entry(
                position_entry_documents,
                trade_fact,
                replay_event.get("broker_order_key"),
            )
            position_entry = build_clustered_position_entry(
                group_trade_fact=trade_fact,
                broker_order_key=replay_event.get("broker_order_key"),
                existing_entry=existing_entry,
            )
            _replace_entry_document(position_entry_documents, position_entry)
            if entry_requires_slice_rebuild(existing_entry):
                _replace_entry_slices(
                    entry_slice_documents,
                    entry_id=position_entry["entry_id"],
                    slices=arrange_entry(
                        position_entry,
                        lot_amount=int(lot_amount_lookup(position_entry["symbol"])),
                        grid_interval=float(
                            grid_interval_lookup(position_entry["symbol"], trade_fact)
                        ),
                    ),
                )
            continue

        execution_fill = replay_event["execution_fill"]
        sell_trade_fact = dict(replay_event["trade_fact"])
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
        available_quantity = sum(
            _coerce_int(item.get("remaining_quantity")) or 0
            for item in symbol_open_slices
        )
        if available_quantity < sell_trade_fact["quantity"]:
            if available_quantity > 0:
                allocatable_trade_fact = dict(sell_trade_fact)
                allocatable_trade_fact["quantity"] = available_quantity
                exit_allocation_documents.extend(
                    allocate_sell_to_entry_slices(
                        entries=symbol_entries,
                        open_slices=symbol_open_slices,
                        sell_trade_fact=allocatable_trade_fact,
                    )
                )
            unmatched_quantity = sell_trade_fact["quantity"] - available_quantity
            unmatched_trade_fact = dict(sell_trade_fact)
            unmatched_trade_fact["trade_fact_id"] = (
                f"{sell_trade_fact['trade_fact_id']}:unmatched"
            )
            unmatched_trade_fact["quantity"] = unmatched_quantity
            unmatched_sell_trade_facts.append(unmatched_trade_fact)
            replay_warnings.append(
                {
                    "code": "sell_exceeds_known_inventory",
                    "broker_order_key": execution_fill.get("broker_order_key"),
                    "execution_fill_id": execution_fill.get("execution_fill_id"),
                    "symbol": symbol,
                    "allocated_quantity": available_quantity,
                    "unmatched_quantity": unmatched_quantity,
                }
            )
            continue
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
        ingest_rejection_documents,
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
    broker_order_id = (
        _normalize_identifier(raw_trade.get("order_id")) or broker_order_key
    )
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
    trade_time = _coerce_int(
        raw_trade.get("traded_time") or raw_trade.get("trade_time")
    )
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


def _build_broker_order_match_key(*, symbol, side, order_id):
    normalized_symbol = str(symbol or "").strip()
    normalized_side = str(side or "").strip().lower()
    normalized_order_id = _normalize_identifier(order_id)
    if not normalized_symbol or not normalized_side or not normalized_order_id:
        return None
    return f"{normalized_symbol}:{normalized_side}:{normalized_order_id}"


def _build_trade_only_broker_order_key(*, symbol, side, order_id, traded_id):
    match_key = _build_broker_order_match_key(
        symbol=symbol,
        side=side,
        order_id=order_id,
    )
    if match_key:
        return f"trade_only:{match_key}"
    normalized_traded_id = _normalize_identifier(traded_id)
    if normalized_traded_id:
        return f"trade_only:{normalized_traded_id}"
    return "trade_only:unknown"


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


def _replace_entry_document(position_entry_documents, position_entry):
    entry_id = position_entry.get("entry_id")
    for index, current in enumerate(position_entry_documents):
        if current.get("entry_id") == entry_id:
            position_entry_documents[index] = position_entry
            return position_entry
    position_entry_documents.append(position_entry)
    return position_entry


def _replace_entry_slices(entry_slice_documents, *, entry_id, slices):
    entry_slice_documents[:] = [
        item for item in entry_slice_documents if item.get("entry_id") != entry_id
    ]
    entry_slice_documents.extend(list(slices or []))
    return entry_slice_documents


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


def _resolve_rebuild_timestamp(now_ts):
    normalized = _coerce_int(now_ts)
    if normalized is not None:
        return normalized
    return int(datetime.now(tz=timezone.utc).timestamp())


def _is_board_lot_quantity(quantity):
    normalized = _coerce_int(quantity) or 0
    return normalized > 0 and normalized % 100 == 0


def _build_entry_broker_order(*, broker_order, fills):
    filled_quantity = sum(_coerce_int(item.get("quantity")) or 0 for item in fills)
    return {
        **broker_order,
        "filled_quantity": filled_quantity,
        "avg_filled_price": _weighted_average_fill_price(fills),
        "first_fill_time": min(
            (
                _coerce_int(item.get("trade_time"))
                for item in fills
                if _coerce_int(item.get("trade_time")) is not None
            ),
            default=None,
        ),
        "last_fill_time": max(
            (
                _coerce_int(item.get("trade_time"))
                for item in fills
                if _coerce_int(item.get("trade_time")) is not None
            ),
            default=None,
        ),
    }


def _build_ingest_rejection_from_execution_fill(execution_fill):
    return {
        "rejection_id": f"reject_{new_reconciliation_resolution_id()}",
        "symbol": execution_fill.get("symbol"),
        "broker_trade_id": execution_fill.get("broker_trade_id"),
        "internal_order_id": None,
        "reason_code": "non_board_lot_quantity",
        "quantity": _coerce_int(execution_fill.get("quantity")) or 0,
        "trade_time": execution_fill.get("trade_time"),
        "date": execution_fill.get("date"),
        "time": execution_fill.get("time"),
        "source": execution_fill.get("source") or "broker_rebuild",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _build_ingest_rejection_from_gap(gap):
    return {
        "rejection_id": f"reject_{new_reconciliation_resolution_id()}",
        "symbol": gap.get("symbol"),
        "broker_trade_id": None,
        "internal_order_id": None,
        "reason_code": "non_board_lot_quantity",
        "quantity": _coerce_int(gap.get("quantity_delta")) or 0,
        "trade_time": gap.get("detected_at"),
        "date": gap.get("date"),
        "time": gap.get("time"),
        "source": "rebuild_reconciliation",
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def _normalize_xt_positions(xt_positions):
    positions_by_symbol = {}
    for raw_position in list(xt_positions or []):
        symbol = _normalize_symbol(raw_position)
        if not symbol:
            continue
        position = positions_by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "volume": 0,
                "price_notional": 0.0,
                "priced_volume": 0,
            },
        )
        volume = _coerce_int(raw_position.get("volume")) or 0
        avg_price = _coerce_float(raw_position.get("avg_price"))
        position["volume"] += volume
        if avg_price is not None and volume > 0:
            position["price_notional"] += volume * avg_price
            position["priced_volume"] += volume
    normalized = {}
    for symbol, position in positions_by_symbol.items():
        priced_volume = position["priced_volume"]
        avg_price = None
        if priced_volume > 0:
            avg_price = round(position["price_notional"] / priced_volume, 6)
        normalized[symbol] = {
            "symbol": symbol,
            "volume": int(position["volume"]),
            "avg_price": avg_price,
        }
    return normalized


def _estimate_ledger_price(symbol, position_entry_documents):
    symbol_entries = [
        item
        for item in position_entry_documents
        if item.get("symbol") == symbol
        and (_coerce_int(item.get("remaining_quantity")) or 0) > 0
    ]
    total_quantity = 0
    total_notional = 0.0
    for item in symbol_entries:
        quantity = _coerce_int(item.get("remaining_quantity")) or 0
        price = _coerce_float(item.get("entry_price")) or 0.0
        total_quantity += quantity
        total_notional += quantity * price
    if total_quantity <= 0:
        return None
    return round(total_notional / total_quantity, 6)


def _reconcile_positions_against_xt_positions(
    *,
    xt_positions,
    now_ts,
    position_entry_documents,
    entry_slice_documents,
    exit_allocation_documents,
    lot_amount_lookup,
    grid_interval_lookup,
    allow_empty_xt_positions_flatten,
):
    reconciliation_gap_documents = []
    reconciliation_resolution_documents = []
    ingest_rejection_documents = []
    auto_open_entries = 0
    auto_close_allocations = 0

    if xt_positions is None:
        return (
            reconciliation_gap_documents,
            reconciliation_resolution_documents,
            auto_open_entries,
            auto_close_allocations,
            ingest_rejection_documents,
        )

    positions_by_symbol = _normalize_xt_positions(xt_positions)
    ledger_remaining_by_symbol = {}
    for entry in position_entry_documents:
        symbol = entry.get("symbol")
        if not symbol:
            continue
        ledger_remaining_by_symbol[symbol] = ledger_remaining_by_symbol.get(
            symbol, 0
        ) + (_coerce_int(entry.get("remaining_quantity")) or 0)

    if (
        xt_positions == []
        and any(quantity > 0 for quantity in ledger_remaining_by_symbol.values())
        and not allow_empty_xt_positions_flatten
    ):
        raise ValueError(
            "empty xt_positions snapshot cannot flatten non-empty ledger; "
            "pass allow_empty_xt_positions_flatten=True to override"
        )

    date_value, time_value = _resolve_beijing_date_time(None, None, now_ts)
    for symbol in sorted(set(positions_by_symbol) | set(ledger_remaining_by_symbol)):
        ledger_quantity = int(ledger_remaining_by_symbol.get(symbol) or 0)
        broker_position = positions_by_symbol.get(symbol) or {
            "symbol": symbol,
            "volume": 0,
            "avg_price": None,
        }
        broker_quantity = _coerce_int(broker_position.get("volume")) or 0
        delta = broker_quantity - ledger_quantity
        if delta == 0:
            continue

        quantity_delta = abs(delta)
        gap_id = new_reconciliation_gap_id()
        resolution_id = new_reconciliation_resolution_id()
        side = "buy" if delta > 0 else "sell"
        price_estimate = _coerce_float(broker_position.get("avg_price"))
        if price_estimate is None:
            price_estimate = _estimate_ledger_price(symbol, position_entry_documents)
        gap = {
            "gap_id": gap_id,
            "symbol": symbol,
            "side": side,
            "quantity_delta": quantity_delta,
            "price_estimate": price_estimate,
            "detected_at": now_ts,
            "first_detected_at": now_ts,
            "last_detected_at": now_ts,
            "observed_count": 1,
            "pending_until": now_ts,
            "state": "OPEN",
            "source": "position_diff",
            "matched_order_id": None,
            "matched_trade_fact_id": None,
            "date": date_value,
            "time": time_value,
        }
        resolution = {
            "resolution_id": resolution_id,
            "gap_id": gap_id,
            "resolved_quantity": quantity_delta,
            "resolved_price": float(price_estimate or 0.0),
            "resolved_at": now_ts,
            "source_ref_type": "reconciliation_gap",
            "source_ref_id": gap_id,
        }

        if not _is_board_lot_quantity(quantity_delta):
            gap["state"] = "REJECTED"
            gap["resolution_id"] = resolution_id
            gap["resolution_type"] = "board_lot_rejected"
            resolution["resolution_type"] = "board_lot_rejected"
            reconciliation_gap_documents.append(gap)
            reconciliation_resolution_documents.append(resolution)
            ingest_rejection_documents.append(_build_ingest_rejection_from_gap(gap))
            continue

        if delta > 0:
            trade_fact = {
                "trade_fact_id": new_trade_fact_id(),
                "symbol": symbol,
                "side": "buy",
                "quantity": quantity_delta,
                "price": float(price_estimate or 0.0),
                "trade_time": now_ts,
                "date": date_value,
                "time": time_value,
                "source": "external_inferred",
            }
            position_entry = build_position_entry_from_trade_fact(
                trade_fact,
                source_ref_type="reconciliation_resolution",
                source_ref_id=resolution_id,
                entry_type="auto_reconciled_open",
                original_quantity=quantity_delta,
                remaining_quantity=quantity_delta,
                entry_price=float(price_estimate or 0.0),
                amount=round(float(price_estimate or 0.0) * quantity_delta, 2),
                source="external_inferred",
                arrange_mode="runtime_grid",
                sell_history=[],
            )
            entry_slices = arrange_entry(
                position_entry,
                lot_amount=int(lot_amount_lookup(symbol)),
                grid_interval=float(grid_interval_lookup(symbol, trade_fact)),
            )
            position_entry_documents.append(position_entry)
            entry_slice_documents.extend(entry_slices)

            gap["state"] = "AUTO_OPENED"
            gap["resolution_id"] = resolution_id
            gap["resolution_type"] = "auto_open_entry"
            gap["entry_id"] = position_entry["entry_id"]
            resolution["resolution_type"] = "auto_open_entry"
            resolution["source_ref_type"] = "position_entry"
            resolution["source_ref_id"] = position_entry["entry_id"]
            auto_open_entries += 1
        else:
            sell_trade_fact = {
                "trade_fact_id": new_trade_fact_id(),
                "symbol": symbol,
                "side": "sell",
                "quantity": quantity_delta,
                "price": float(price_estimate or 0.0),
                "trade_time": now_ts,
                "date": date_value,
                "time": time_value,
                "source": "external_inferred",
            }
            symbol_entries = [
                item
                for item in position_entry_documents
                if item.get("symbol") == symbol
                and (_coerce_int(item.get("remaining_quantity")) or 0) > 0
            ]
            symbol_open_slices = [
                item
                for item in entry_slice_documents
                if item.get("symbol") == symbol
                and (_coerce_int(item.get("remaining_quantity")) or 0) > 0
            ]
            symbol_open_slices.sort(
                key=lambda item: (
                    _coerce_float(item.get("sort_key")) or 0.0,
                    _coerce_int(item.get("slice_seq")) or 0,
                ),
                reverse=True,
            )
            allocations = allocate_sell_to_entry_slices(
                entries=symbol_entries,
                open_slices=symbol_open_slices,
                sell_trade_fact=sell_trade_fact,
            )
            exit_allocation_documents.extend(allocations)

            gap["state"] = "AUTO_CLOSED"
            gap["resolution_id"] = resolution_id
            gap["resolution_type"] = "auto_close_allocation"
            resolution["resolution_type"] = "auto_close_allocation"
            resolution["entry_allocation_ids"] = [
                item["allocation_id"] for item in allocations
            ]
            auto_close_allocations += len(allocations)

        reconciliation_gap_documents.append(gap)
        reconciliation_resolution_documents.append(resolution)

    return (
        reconciliation_gap_documents,
        reconciliation_resolution_documents,
        auto_open_entries,
        auto_close_allocations,
        ingest_rejection_documents,
    )


def _default_lot_amount_lookup(_symbol):
    return _DEFAULT_LOT_AMOUNT


def _default_grid_interval_lookup(_symbol, _trade_fact):
    return _DEFAULT_GRID_INTERVAL


def _count_non_default_lot_slices_with_lookup(
    entry_slice_documents, *, lot_amount_lookup
):
    lot_amount_by_symbol = {}
    count = 0
    for item in list(entry_slice_documents or []):
        symbol = _normalize_identifier(item.get("symbol"))
        if symbol not in lot_amount_by_symbol:
            lot_amount_by_symbol[symbol] = (
                lot_amount_lookup(symbol) if symbol else _DEFAULT_LOT_AMOUNT
            )
        count += count_non_default_lot_slices(
            [item],
            lot_amount=lot_amount_by_symbol[symbol],
        )
    return count
