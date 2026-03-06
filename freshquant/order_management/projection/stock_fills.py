# -*- coding: utf-8 -*-

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
        fills.append(
            {
                "symbol": trade_fact["symbol"],
                "stock_code": trade_fact.get("stock_code"),
                "name": trade_fact.get("name", ""),
                "date": trade_fact.get("date"),
                "time": trade_fact.get("time"),
                "op": "买" if trade_fact["side"] == "buy" else "卖",
                "quantity": trade_fact["quantity"],
                "price": trade_fact["price"],
                "amount": round(trade_fact["price"] * trade_fact["quantity"], 2),
                "source": trade_fact.get("source", "order_management"),
            }
        )
    return fills


def build_open_buy_fills_view(buy_lots):
    return [
        {
            "symbol": item["symbol"],
            "date": item.get("date"),
            "time": item.get("time"),
            "price": item["buy_price_real"],
            "quantity": item["remaining_quantity"],
            "amount": round(
                float(item.get("amount", item["buy_price_real"] * item["original_quantity"]))
                * float(item["remaining_quantity"])
                / float(item["original_quantity"]),
                2,
            )
            if item.get("original_quantity")
            else 0.0,
            "amount_adjust": float(item.get("amount_adjust", 1.0)),
            "stock_code": item.get("stock_code"),
            "name": item.get("name", ""),
            "source": item.get("source", "order_management"),
        }
        for item in buy_lots
        if item["remaining_quantity"] > 0
    ]


def build_arranged_fills_view(open_slices):
    return build_arranged_fill_read_model(open_slices)


def list_open_buy_fills(symbol, repository=None):
    repository = repository or OrderManagementRepository()
    buy_lots = repository.list_buy_lots(symbol)
    return build_open_buy_fills_view(buy_lots)


def list_arranged_fills(symbol, repository=None):
    repository = repository or OrderManagementRepository()
    open_slices = repository.list_open_slices(symbol)
    return build_arranged_fills_view(open_slices)


def list_stock_positions(repository=None):
    repository = repository or OrderManagementRepository()
    buy_lots = repository.list_buy_lots()
    grouped = {}

    for item in buy_lots:
        if item["remaining_quantity"] <= 0:
            continue
        symbol = item["symbol"]
        position = grouped.setdefault(
            symbol,
            {
                "symbol": fq_util_code_append_market_code(symbol),
                "stock_code": fq_util_code_append_market_code_suffix(
                    symbol,
                    upper_case=True,
                ),
                "name": item.get("name", ""),
                "quantity": 0,
                "amount": 0.0,
                "amount_adjusted": 0.0,
                "date": item.get("date"),
                "time": item.get("time"),
            },
        )
        remaining_amount = (
            round(
                float(item.get("amount", item["buy_price_real"] * item["original_quantity"]))
                * float(item["remaining_quantity"])
                / float(item["original_quantity"])
                * -1,
                2,
            )
            if item.get("original_quantity")
            else 0.0
        )
        position["quantity"] += int(item["remaining_quantity"])
        position["amount"] += remaining_amount
        position["amount_adjusted"] += remaining_amount * float(
            item.get("amount_adjust", 1.0)
        )
        position["date"] = item.get("date", position["date"])
        position["time"] = item.get("time", position["time"])

    positions = list(grouped.values())
    positions.sort(key=lambda item: (item.get("date") or 0, item.get("time") or ""))
    return positions
