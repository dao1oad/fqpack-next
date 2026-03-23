# -*- coding: utf-8 -*-

from freshquant.db import DBfreshquant
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.util.code import fq_util_code_append_market_code_suffix
from freshquant.util.code import normalize_to_base_code


def sync_symbol(symbol, repository=None, database=None):
    normalized_symbol = normalize_to_base_code(symbol)
    if not normalized_symbol:
        return []

    repository = repository or OrderManagementRepository()
    collection = _get_stock_fills_collection(database)
    rows = _build_symbol_rows(
        normalized_symbol,
        repository=repository,
    )

    collection.delete_many({"symbol": normalized_symbol})
    if rows:
        collection.insert_many(rows)
    return rows


def list_compat_stock_positions(symbol=None, repository=None, database=None):
    collection = _get_stock_fills_collection(database)
    query = {}
    normalized_symbol = normalize_to_base_code(symbol)
    if normalized_symbol:
        query["symbol"] = normalized_symbol
    rows = list(collection.find(query))
    grouped = {}
    for item in rows:
        normalized_item_symbol = normalize_to_base_code(
            item.get("symbol") or item.get("stock_code") or item.get("code")
        )
        if not normalized_item_symbol:
            continue
        current = grouped.setdefault(
            normalized_item_symbol,
            {
                "symbol": normalized_item_symbol,
                "name": "",
                "quantity": 0,
                "amount": 0.0,
                "amount_adjusted": 0.0,
            },
        )
        current["name"] = current["name"] or _normalize_text(item.get("name"))
        direction = -1 if "买" in str(item.get("op") or "") else 1
        quantity_delta = _coerce_int(item.get("quantity"), 0) * direction * -1
        amount = _coerce_float(item.get("amount"), 0.0)
        amount_adjust = _coerce_float(item.get("amount_adjust"), 1.0)
        amount_delta = amount * direction
        current["quantity"] += quantity_delta
        current["amount"] += amount_delta
        current["amount_adjusted"] += amount_delta * amount_adjust

    positions = [
        item
        for item in grouped.values()
        if item["amount_adjusted"] < 0 or item["quantity"] > 0
    ]
    positions.sort(key=lambda item: item["symbol"])
    return positions


def _build_symbol_rows(symbol, *, repository):
    buy_lots = list(repository.list_buy_lots(symbol) or [])
    rows = []
    for buy_lot in buy_lots:
        remaining_quantity = _coerce_int(buy_lot.get("remaining_quantity"), 0)
        if remaining_quantity <= 0:
            continue
        original_quantity = _coerce_int(
            buy_lot.get("original_quantity") or buy_lot.get("quantity"),
            0,
        )
        amount = buy_lot.get("remaining_amount")
        if amount is None:
            base_amount = _coerce_float(buy_lot.get("amount"), 0.0)
            if original_quantity > 0:
                amount = round(
                    base_amount * remaining_quantity / original_quantity,
                    2,
                )
            else:
                amount = 0.0
        row = {
            "symbol": symbol,
            "op": "买",
            "quantity": remaining_quantity,
            "price": _coerce_float(
                buy_lot.get("buy_price_real") or buy_lot.get("price"),
                0.0,
            ),
            "amount": _coerce_float(amount, 0.0),
            "amount_adjust": _coerce_float(buy_lot.get("amount_adjust"), 1.0),
            "date": buy_lot.get("date"),
            "time": buy_lot.get("time"),
            "name": _normalize_text(buy_lot.get("name")),
            "stock_code": _normalize_text(
                buy_lot.get("stock_code")
            )
            or fq_util_code_append_market_code_suffix(symbol, upper_case=True),
            "source": _normalize_text(buy_lot.get("source")) or "order_management",
        }
        rows.append(row)
    rows.sort(key=lambda item: (item.get("date") or 0, item.get("time") or ""))
    return rows


def _get_stock_fills_collection(database):
    target = database or DBfreshquant
    if hasattr(target, "stock_fills"):
        return target.stock_fills
    return target["stock_fills"]


def _normalize_text(value):
    text = str(value or "").strip()
    return text


def _coerce_float(value, default):
    if value is None:
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_int(value, default):
    if value is None:
        return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
