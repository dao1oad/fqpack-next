# -*- coding: utf-8 -*-

from datetime import datetime

from freshquant.order_management.guardian.read_model import (
    build_arranged_fill_read_model,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.util.code import (
    fq_util_code_append_market_code,
    fq_util_code_append_market_code_suffix,
)


def build_raw_fills_view(trade_facts):
    fills = []
    for trade_fact in trade_facts:
        normalized_trade_fact = _with_resolved_date_time(trade_fact)
        fills.append(
            {
                "symbol": normalized_trade_fact["symbol"],
                "stock_code": normalized_trade_fact.get("stock_code"),
                "name": normalized_trade_fact.get("name", ""),
                "date": normalized_trade_fact.get("date"),
                "time": normalized_trade_fact.get("time"),
                "op": "买" if normalized_trade_fact["side"] == "buy" else "卖",
                "quantity": normalized_trade_fact["quantity"],
                "price": normalized_trade_fact["price"],
                "amount": round(
                    normalized_trade_fact["price"] * normalized_trade_fact["quantity"],
                    2,
                ),
                "source": normalized_trade_fact.get("source", "order_management"),
            }
        )
    return fills


def build_open_buy_fills_view(buy_lots):
    results = []
    for item in buy_lots:
        if item["remaining_quantity"] <= 0:
            continue
        normalized_item = _with_resolved_date_time(item)
        results.append(
            {
                "symbol": normalized_item["symbol"],
                "date": normalized_item.get("date"),
                "time": normalized_item.get("time"),
                "price": normalized_item["buy_price_real"],
                "quantity": normalized_item["remaining_quantity"],
                "amount": (
                    round(
                        float(
                            normalized_item.get(
                                "amount",
                                normalized_item["buy_price_real"]
                                * normalized_item["original_quantity"],
                            )
                        )
                        * float(normalized_item["remaining_quantity"])
                        / float(normalized_item["original_quantity"]),
                        2,
                    )
                    if normalized_item.get("original_quantity")
                    else 0.0
                ),
                "amount_adjust": float(normalized_item.get("amount_adjust", 1.0)),
                "stock_code": normalized_item.get("stock_code"),
                "name": normalized_item.get("name", ""),
                "source": normalized_item.get("source", "order_management"),
            }
        )
    return results


def build_arranged_fills_view(open_slices):
    return build_arranged_fill_read_model(open_slices)


def list_open_buy_fills(symbol, repository=None):
    repository = repository or OrderManagementRepository()
    buy_lots = repository.list_buy_lots(symbol)
    return build_open_buy_fills_view(buy_lots)


def list_arranged_fills(symbol, repository=None):
    repository = repository or OrderManagementRepository()
    open_slices = repository.list_open_slices(symbol)
    buy_lots = repository.list_buy_lots(symbol)
    buy_lot_by_id = {
        item.get("buy_lot_id"): item
        for item in buy_lots
        if item.get("buy_lot_id") is not None
    }
    normalized_slices = [
        _with_resolved_date_time(
            item,
            fallback=buy_lot_by_id.get(item.get("buy_lot_id")),
        )
        for item in open_slices
    ]
    return build_arranged_fills_view(normalized_slices)


def list_stock_positions(repository=None):
    repository = repository or OrderManagementRepository()
    buy_lots = repository.list_buy_lots()
    grouped = {}

    for item in buy_lots:
        if item["remaining_quantity"] <= 0:
            continue
        normalized_item = _with_resolved_date_time(item)
        symbol = normalized_item["symbol"]
        position = grouped.setdefault(
            symbol,
            {
                "symbol": fq_util_code_append_market_code(symbol),
                "stock_code": fq_util_code_append_market_code_suffix(
                    symbol,
                    upper_case=True,
                ),
                "name": normalized_item.get("name", ""),
                "quantity": 0,
                "amount": 0.0,
                "amount_adjusted": 0.0,
                "date": normalized_item.get("date"),
                "time": normalized_item.get("time"),
            },
        )
        remaining_amount = (
            round(
                float(
                    normalized_item.get(
                        "amount",
                        normalized_item["buy_price_real"]
                        * normalized_item["original_quantity"],
                    )
                )
                * float(normalized_item["remaining_quantity"])
                / float(normalized_item["original_quantity"])
                * -1,
                2,
            )
            if normalized_item.get("original_quantity")
            else 0.0
        )
        position["quantity"] += int(normalized_item["remaining_quantity"])
        position["amount"] += remaining_amount
        position["amount_adjusted"] += remaining_amount * float(
            normalized_item.get("amount_adjust", 1.0)
        )
        position["date"] = normalized_item.get("date", position["date"])
        position["time"] = normalized_item.get("time", position["time"])

    positions = list(grouped.values())
    positions.sort(key=lambda item: (item.get("date") or 0, item.get("time") or ""))
    return positions


def _with_resolved_date_time(record, *, fallback=None):
    normalized = dict(record)
    resolved_date, resolved_time = _resolve_date_time_fields(
        normalized,
        fallback=fallback,
    )
    normalized["date"] = resolved_date
    normalized["time"] = resolved_time
    return normalized


def _resolve_date_time_fields(record, *, fallback=None):
    date_value = record.get("date")
    time_value = record.get("time")
    if _has_date_time(date_value, time_value):
        return date_value, time_value

    fallback_date = None if fallback is None else fallback.get("date")
    fallback_time = None if fallback is None else fallback.get("time")
    if _has_date_time(fallback_date, fallback_time):
        return fallback_date, fallback_time

    trade_time = record.get("trade_time")
    if trade_time in {None, ""} and fallback is not None:
        trade_time = fallback.get("trade_time")
    if trade_time in {None, ""}:
        return date_value, time_value
    try:
        trade_dt = datetime.fromtimestamp(int(trade_time))
    except (OSError, OverflowError, TypeError, ValueError):
        return date_value, time_value
    return int(trade_dt.strftime("%Y%m%d")), trade_dt.strftime("%H:%M:%S")


def _has_date_time(date_value, time_value):
    return date_value not in {None, ""} and time_value not in {None, ""}
