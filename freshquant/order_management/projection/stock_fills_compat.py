# -*- coding: utf-8 -*-

from freshquant.db import DBfreshquant
from freshquant.order_management.entry_adapter import list_open_entry_views
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.util.code import normalize_to_base_code


def sync_symbol(symbol, repository=None, database=None):
    service = StockFillsCompatibilityService(
        repository=repository,
        database=database,
    )
    return service.sync_symbol(symbol)


def sync_symbols(symbols=None, repository=None, database=None):
    service = StockFillsCompatibilityService(
        repository=repository,
        database=database,
    )
    return service.sync_symbols(symbols)


def compare_symbol(symbol, repository=None, database=None):
    service = StockFillsCompatibilityService(
        repository=repository,
        database=database,
    )
    return service.compare_symbol(symbol)


def list_compat_stock_positions(symbol=None, repository=None, database=None):
    rows = list_compat_stock_fill_rows(symbol=symbol, database=database)
    return _aggregate_position_rows(rows)


def list_compat_stock_fill_rows(symbol=None, database=None):
    collection = _get_stock_fills_compat_collection(database)
    query = {}
    normalized_symbol = _normalize_optional_symbol(symbol)
    if normalized_symbol:
        query["symbol"] = normalized_symbol
    return list(collection.find(query))


def build_compat_stock_fill_records(entries):
    rows = []
    for buy_lot in entries or []:
        symbol = _normalize_optional_symbol(
            buy_lot.get("symbol") or buy_lot.get("stock_code") or buy_lot.get("code")
        )
        if not symbol:
            continue
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
            "stock_code": _resolve_stock_code(symbol, buy_lot),
            "source": "om_projection_mirror",
        }
        rows.append(row)
    rows.sort(key=lambda item: (item.get("date") or 0, item.get("time") or ""))
    return rows


class StockFillsCompatibilityService:
    def __init__(self, repository=None, database=None):
        self.repository = repository or OrderManagementRepository()
        self.database = database

    def sync_symbol(self, symbol: str):
        normalized_symbol = _normalize_optional_symbol(symbol)
        if not normalized_symbol:
            return []

        collection = _get_stock_fills_compat_collection(self.database)
        rows = build_compat_stock_fill_records(
            list_open_entry_views(
                symbol=normalized_symbol,
                repository=self.repository,
            )
            or []
        )
        collection.delete_many({"symbol": normalized_symbol})
        if rows:
            collection.insert_many(rows)
        return rows

    def sync_symbols(self, symbols=None):
        normalized_symbols = _collect_sync_symbols(
            symbols,
            repository=self.repository,
            database=self.database,
        )
        rows_by_symbol = {}
        for symbol in normalized_symbols:
            rows_by_symbol[symbol] = len(self.sync_symbol(symbol))
        return {
            "synced_symbols": normalized_symbols,
            "rows_by_symbol": rows_by_symbol,
        }

    def compare_symbol(self, symbol: str):
        normalized_symbol = _normalize_optional_symbol(symbol)
        if not normalized_symbol:
            return {
                "symbol": "",
                "projected_quantity": 0,
                "compat_quantity": 0,
                "projected_amount_adjusted": 0.0,
                "compat_amount_adjusted": 0.0,
                "quantity_consistent": True,
                "amount_adjusted_consistent": True,
            }

        projected_rows = build_compat_stock_fill_records(
            list_open_entry_views(
                symbol=normalized_symbol,
                repository=self.repository,
            )
            or []
        )
        compat_rows = list_compat_stock_fill_rows(
            symbol=normalized_symbol,
            database=self.database,
        )
        projected_position = _position_for_symbol(projected_rows, normalized_symbol)
        compat_position = _position_for_symbol(compat_rows, normalized_symbol)
        return {
            "symbol": normalized_symbol,
            "projected_quantity": projected_position["quantity"],
            "compat_quantity": compat_position["quantity"],
            "projected_amount_adjusted": projected_position["amount_adjusted"],
            "compat_amount_adjusted": compat_position["amount_adjusted"],
            "quantity_consistent": projected_position["quantity"]
            == compat_position["quantity"],
            "amount_adjusted_consistent": projected_position["amount_adjusted"]
            == compat_position["amount_adjusted"],
        }


def _get_stock_fills_compat_collection(database):
    target = DBfreshquant if database is None else database
    if hasattr(target, "stock_fills_compat"):
        return target.stock_fills_compat
    return target["stock_fills_compat"]


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


def _normalize_optional_symbol(symbol):
    if symbol in {None, ""}:
        return ""
    return normalize_to_base_code(symbol)


def _resolve_stock_code(symbol, buy_lot):
    raw_stock_code = _normalize_text(buy_lot.get("stock_code"))
    if raw_stock_code:
        return raw_stock_code

    raw_symbol = _normalize_text(
        buy_lot.get("symbol") or buy_lot.get("stock_code") or buy_lot.get("code")
    ).upper()
    if "." in raw_symbol:
        return raw_symbol
    if len(raw_symbol) >= 8 and raw_symbol[:2] in {"SH", "SZ", "BJ"}:
        return f"{raw_symbol[2:]}.{raw_symbol[:2]}"

    market = _guess_symbol_market(symbol)
    return f"{symbol}.{market}" if market else symbol


def _guess_symbol_market(symbol):
    normalized_symbol = _normalize_optional_symbol(symbol)
    if len(normalized_symbol) != 6 or not normalized_symbol.isdigit():
        return ""
    if normalized_symbol.startswith(("4", "8")):
        return "BJ"
    if normalized_symbol.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _aggregate_position_rows(rows):
    grouped = {}
    for item in rows or []:
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
    for item in positions:
        item["amount"] = round(float(item["amount"]), 2)
        item["amount_adjusted"] = round(float(item["amount_adjusted"]), 2)
    positions.sort(key=lambda item: item["symbol"])
    return positions


def _position_for_symbol(rows, symbol):
    for item in _aggregate_position_rows(rows):
        if item["symbol"] == symbol:
            return item
    return {
        "symbol": symbol,
        "name": "",
        "quantity": 0,
        "amount": 0.0,
        "amount_adjusted": 0.0,
    }


def _collect_sync_symbols(symbols, *, repository, database):
    normalized_symbols = set()
    if symbols:
        for item in symbols:
            normalized_symbol = _normalize_optional_symbol(item)
            if normalized_symbol:
                normalized_symbols.add(normalized_symbol)
    else:
        for buy_lot in list_open_entry_views(repository=repository) or []:
            normalized_symbol = _normalize_optional_symbol(
                buy_lot.get("symbol")
                or buy_lot.get("stock_code")
                or buy_lot.get("code")
            )
            if normalized_symbol:
                normalized_symbols.add(normalized_symbol)

    for row in list_compat_stock_fill_rows(database=database):
        normalized_symbol = _normalize_optional_symbol(
            row.get("symbol") or row.get("stock_code") or row.get("code")
        )
        if normalized_symbol:
            normalized_symbols.add(normalized_symbol)
    return sorted(normalized_symbols)
