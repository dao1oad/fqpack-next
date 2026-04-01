# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freshquant.order_management.guardian.arranger import (
    build_position_entry_from_trade_fact,
)

_BEIJING_TIMEZONE = timezone(timedelta(hours=8))

BUY_CLUSTER_SOURCE_REF_TYPE = "buy_cluster"
BUY_CLUSTER_ENTRY_TYPE = "broker_execution_cluster"
BUY_CLUSTER_MAX_TIME_WINDOW_SECONDS = 5 * 60
BUY_CLUSTER_MAX_PRICE_DEVIATION_RATIO = 0.003


def find_entry_for_broker_order(entries, broker_order_key):
    normalized_key = _normalize_text(broker_order_key)
    if not normalized_key:
        return None
    for entry in list(entries or []):
        member_keys = _entry_member_keys(entry)
        if normalized_key in member_keys:
            return entry
    return None


def select_cluster_entry(entries, group_trade_fact, broker_order_key):
    exact_match = find_entry_for_broker_order(entries, broker_order_key)
    if exact_match is not None:
        return exact_match

    symbol = _normalize_text(group_trade_fact.get("symbol"))
    group_trade_time = _coerce_int(group_trade_fact.get("trade_time"))
    group_trading_day = _resolve_trading_day(group_trade_fact)
    group_price = _coerce_float(group_trade_fact.get("price"))
    candidates = []

    for entry in list(entries or []):
        if _normalize_text(entry.get("symbol")) != symbol:
            continue
        if (_coerce_int(entry.get("remaining_quantity")) or 0) <= 0:
            continue
        if _entry_is_sell_touched(entry):
            continue

        members = list_aggregation_members(entry)
        if not members:
            continue
        first_member = members[0]
        if group_trading_day and first_member.get("trading_day") != group_trading_day:
            continue
        anchor_trade_time = _coerce_int(first_member.get("trade_time"))
        if anchor_trade_time is None or group_trade_time is None:
            continue
        # Anchor the cluster to its first member so the window cannot chain-grow.
        if (
            abs(group_trade_time - anchor_trade_time)
            > BUY_CLUSTER_MAX_TIME_WINDOW_SECONDS
        ):
            continue
        base_price = _coerce_float(entry.get("entry_price")) or _coerce_float(
            first_member.get("entry_price")
        )
        if not _price_deviation_within(group_price, base_price):
            continue
        candidates.append((anchor_trade_time, entry))

    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item[0], _normalize_text(item[1].get("entry_id"))),
        reverse=True,
    )
    return candidates[0][1]


def build_clustered_position_entry(
    *,
    group_trade_fact,
    broker_order_key,
    existing_entry=None,
):
    normalized_broker_order_key = _normalize_text(broker_order_key)
    base_members = list_aggregation_members(existing_entry)
    group_member = build_buy_group_member(
        group_trade_fact,
        broker_order_key=normalized_broker_order_key,
    )

    members_by_key = {
        _normalize_text(item.get("broker_order_key")): dict(item)
        for item in base_members
        if _normalize_text(item.get("broker_order_key"))
    }
    members_by_key[normalized_broker_order_key] = group_member
    members = sorted(
        members_by_key.values(),
        key=lambda item: (
            _coerce_int(item.get("trade_time")) or 0,
            int(item.get("trading_day") or 0),
            str(item.get("time") or ""),
            _normalize_text(item.get("broker_order_key")),
        ),
    )

    total_quantity = sum(_coerce_int(item.get("quantity")) or 0 for item in members)
    total_notional = sum(
        (_coerce_int(item.get("quantity")) or 0)
        * (_coerce_float(item.get("entry_price")) or 0.0)
        for item in members
    )
    entry_price = (
        round(total_notional / total_quantity, 6) if total_quantity > 0 else 0.0
    )

    original_quantity = (
        _coerce_int((existing_entry or {}).get("original_quantity")) or 0
    )
    remaining_quantity = (
        _coerce_int((existing_entry or {}).get("remaining_quantity")) or 0
    )
    exited_quantity = max(original_quantity - remaining_quantity, 0)
    merged_remaining_quantity = max(total_quantity - exited_quantity, 0)

    first_member = members[0]
    last_member = members[-1]
    source_ref_id = _normalize_text((existing_entry or {}).get("source_ref_id"))
    if (
        _normalize_text((existing_entry or {}).get("source_ref_type"))
        != BUY_CLUSTER_SOURCE_REF_TYPE
    ):
        source_ref_id = None
    if not source_ref_id:
        source_ref_id = _build_cluster_source_ref_id(
            symbol=group_trade_fact.get("symbol"),
            trading_day=first_member.get("trading_day"),
            anchor_trade_time=first_member.get("trade_time"),
            broker_order_key=first_member.get("broker_order_key"),
        )

    trade_payload = {
        **dict(group_trade_fact),
        "trade_fact_id": first_member.get("trade_fact_id")
        or group_trade_fact.get("trade_fact_id"),
        "quantity": total_quantity,
        "price": entry_price,
        "trade_time": first_member.get("trade_time"),
        "date": first_member.get("date"),
        "time": first_member.get("time"),
        "source": group_trade_fact.get("source")
        or (existing_entry or {}).get("source")
        or "order_management",
    }
    entry = build_position_entry_from_trade_fact(
        trade_payload,
        entry_id=(existing_entry or {}).get("entry_id"),
        source_ref_type=BUY_CLUSTER_SOURCE_REF_TYPE,
        source_ref_id=source_ref_id,
        entry_type=BUY_CLUSTER_ENTRY_TYPE,
        original_quantity=total_quantity,
        remaining_quantity=merged_remaining_quantity,
        entry_price=entry_price,
        amount=round(entry_price * total_quantity, 2),
        source=trade_payload["source"],
        arrange_mode=(existing_entry or {}).get("arrange_mode") or "runtime_grid",
        sell_history=(existing_entry or {}).get("sell_history") or [],
    )
    entry["aggregation_members"] = members
    entry["aggregation_member_keys"] = [
        _normalize_text(item.get("broker_order_key")) for item in members
    ]
    entry["aggregation_window"] = {
        "start_trade_time": first_member.get("trade_time"),
        "end_trade_time": last_member.get("trade_time"),
        "trading_day": first_member.get("trading_day"),
        "member_count": len(members),
    }
    return entry


def build_buy_group_member(group_trade_fact, *, broker_order_key):
    trading_day = _resolve_trading_day(group_trade_fact)
    return {
        "broker_order_key": _normalize_text(broker_order_key),
        "trade_fact_id": _normalize_text(group_trade_fact.get("trade_fact_id")),
        "quantity": _coerce_int(group_trade_fact.get("quantity")) or 0,
        "entry_price": _coerce_float(group_trade_fact.get("price")) or 0.0,
        "trade_time": _coerce_int(group_trade_fact.get("trade_time")),
        "date": _resolve_date(group_trade_fact),
        "time": _resolve_time(group_trade_fact),
        "trading_day": trading_day,
    }


def list_aggregation_members(entry):
    normalized_entry = dict(entry or {})
    members = [
        _normalize_member(item)
        for item in list(normalized_entry.get("aggregation_members") or [])
        if _normalize_member(item) is not None
    ]
    if members:
        return sorted(
            members,
            key=lambda item: (
                _coerce_int(item.get("trade_time")) or 0,
                int(item.get("trading_day") or 0),
                str(item.get("time") or ""),
                _normalize_text(item.get("broker_order_key")),
            ),
        )

    source_ref_type = _normalize_text(normalized_entry.get("source_ref_type"))
    source_ref_id = _normalize_text(normalized_entry.get("source_ref_id"))
    if source_ref_type != "broker_order" or not source_ref_id:
        return []
    legacy_member = _normalize_member(
        {
            "broker_order_key": source_ref_id,
            "trade_fact_id": source_ref_id,
            "quantity": normalized_entry.get("original_quantity"),
            "entry_price": normalized_entry.get("entry_price")
            or normalized_entry.get("buy_price_real"),
            "trade_time": normalized_entry.get("trade_time"),
            "date": normalized_entry.get("date"),
            "time": normalized_entry.get("time"),
        }
    )
    return [legacy_member] if legacy_member is not None else []


def entry_requires_slice_rebuild(existing_entry):
    return not _entry_is_sell_touched(existing_entry)


def count_non_default_lot_slices(entry_slice_documents, *, lot_amount):
    threshold = _coerce_float(lot_amount)
    if threshold in {None, 0.0}:
        return 0
    count = 0
    for item in list(entry_slice_documents or []):
        slice_amount = (_coerce_int(item.get("original_quantity")) or 0) * (
            _coerce_float(item.get("guardian_price")) or 0.0
        )
        if slice_amount > threshold + 1e-6:
            count += 1
    return count


def count_clustered_entries(entries):
    return sum(
        1
        for entry in list(entries or [])
        if _normalize_text(entry.get("source_ref_type")) == BUY_CLUSTER_SOURCE_REF_TYPE
    )


def summarize_mergeable_gap(entries):
    count = 0
    previous = None
    for entry in sorted(
        list(entries or []),
        key=lambda item: (
            _normalize_text(item.get("symbol")),
            int(_resolve_trading_day(item) or 0),
            _coerce_int(item.get("trade_time")) or 0,
            _normalize_text(item.get("entry_id")),
        ),
    ):
        if previous is None:
            previous = entry
            continue
        if _entries_mergeable(previous, entry):
            count += 1
        previous = entry
    return count


def _entries_mergeable(left, right):
    if _normalize_text(left.get("symbol")) != _normalize_text(right.get("symbol")):
        return False
    if _entry_is_sell_touched(left) or _entry_is_sell_touched(right):
        return False
    left_members = list_aggregation_members(left)
    right_members = list_aggregation_members(right)
    if not left_members or not right_members:
        return False
    left_first = left_members[0]
    right_first = right_members[0]
    if left_first.get("trading_day") != right_first.get("trading_day"):
        return False
    left_anchor = _coerce_int(left_first.get("trade_time"))
    right_anchor = _coerce_int(right_first.get("trade_time"))
    if left_anchor is None or right_anchor is None:
        return False
    if abs(right_anchor - left_anchor) > BUY_CLUSTER_MAX_TIME_WINDOW_SECONDS:
        return False
    return _price_deviation_within(
        _coerce_float(right.get("entry_price")),
        _coerce_float(left.get("entry_price")),
    )


def _entry_member_keys(entry):
    keys = [
        _normalize_text(item)
        for item in list((entry or {}).get("aggregation_member_keys") or [])
        if _normalize_text(item)
    ]
    if keys:
        return keys
    return [
        _normalize_text(item.get("broker_order_key"))
        for item in list_aggregation_members(entry)
        if _normalize_text(item.get("broker_order_key"))
    ]


def _entry_is_sell_touched(entry):
    normalized_entry = dict(entry or {})
    if list(normalized_entry.get("sell_history") or []):
        return True
    original_quantity = _coerce_int(normalized_entry.get("original_quantity")) or 0
    remaining_quantity = _coerce_int(normalized_entry.get("remaining_quantity")) or 0
    return original_quantity > remaining_quantity


def _price_deviation_within(left_price, right_price):
    left_price = _coerce_float(left_price)
    right_price = _coerce_float(right_price)
    if left_price in {None, 0.0} or right_price in {None, 0.0}:
        return False
    return (
        abs(left_price - right_price) / right_price
        <= BUY_CLUSTER_MAX_PRICE_DEVIATION_RATIO
    )


def _normalize_member(member):
    if member is None or member == "":
        return None
    normalized = dict(member)
    broker_order_key = _normalize_text(normalized.get("broker_order_key"))
    if not broker_order_key:
        return None
    trade_time = _coerce_int(normalized.get("trade_time"))
    date_value = normalized.get("date")
    time_value = normalized.get("time")
    if trade_time is not None and (
        date_value in {None, ""} or time_value in {None, ""}
    ):
        date_value, time_value = _resolve_beijing_date_time(
            date_value,
            time_value,
            trade_time,
        )
    trading_day = (
        int(date_value)
        if date_value not in {None, ""}
        else _resolve_trading_day({"trade_time": trade_time})
    )
    return {
        "broker_order_key": broker_order_key,
        "trade_fact_id": _normalize_text(normalized.get("trade_fact_id"))
        or broker_order_key,
        "quantity": _coerce_int(normalized.get("quantity")) or 0,
        "entry_price": _coerce_float(normalized.get("entry_price")) or 0.0,
        "trade_time": trade_time,
        "date": int(date_value) if date_value not in {None, ""} else trading_day,
        "time": str(time_value or "").strip() or "00:00:00",
        "trading_day": trading_day,
    }


def _build_cluster_source_ref_id(
    *, symbol, trading_day, anchor_trade_time, broker_order_key
):
    return ":".join(
        [
            "buy_cluster",
            _normalize_text(symbol) or "unknown",
            str(trading_day or "unknown"),
            str(anchor_trade_time or "unknown"),
            _normalize_text(broker_order_key) or "unknown",
        ]
    )


def _resolve_trading_day(payload):
    date_value = _resolve_date(payload)
    if date_value not in {None, ""}:
        return int(date_value)
    trade_time = _coerce_int((payload or {}).get("trade_time"))
    if trade_time is None:
        return None
    return _resolve_beijing_date_time(None, None, trade_time)[0]


def _resolve_date(payload):
    date_value = (payload or {}).get("date")
    if date_value not in {None, ""}:
        return int(date_value)
    trade_time = _coerce_int((payload or {}).get("trade_time"))
    if trade_time is None:
        return None
    return _resolve_beijing_date_time(None, None, trade_time)[0]


def _resolve_time(payload):
    time_value = str((payload or {}).get("time") or "").strip()
    if time_value:
        return time_value
    trade_time = _coerce_int((payload or {}).get("trade_time"))
    if trade_time is None:
        return "00:00:00"
    return _resolve_beijing_date_time(None, None, trade_time)[1]


def _resolve_beijing_date_time(date_value, time_value, trade_time):
    if date_value not in {None, ""} and time_value not in {None, ""}:
        return int(date_value), str(time_value)
    if trade_time in {None, ""}:
        resolved_date = int(date_value) if date_value not in {None, ""} else None
        resolved_time = str(time_value or "").strip() or None
        return resolved_date, resolved_time
    trade_datetime = datetime.fromtimestamp(int(trade_time), tz=_BEIJING_TIMEZONE)
    return int(trade_datetime.strftime("%Y%m%d")), trade_datetime.strftime("%H:%M:%S")


def _coerce_int(value):
    if value in {None, ""}:
        return None
    return int(value)


def _coerce_float(value):
    if value in {None, ""}:
        return None
    return float(value)


def _normalize_text(value):
    normalized = str(value or "").strip()
    return normalized or None
