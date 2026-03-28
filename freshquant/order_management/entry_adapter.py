# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.order_management.repository import OrderManagementRepository


def get_entry_view(entry_id, repository=None):
    repository = repository or OrderManagementRepository()
    entry_id_text = str(entry_id or "").strip()
    if not entry_id_text:
        return None
    entry = None
    if hasattr(repository, "find_position_entry"):
        entry = repository.find_position_entry(entry_id_text)
    if entry is not None:
        return _normalize_entry(entry)
    buy_lot = repository.find_buy_lot(entry_id_text)
    if buy_lot is None:
        return None
    return _legacy_buy_lot_to_entry(buy_lot)


def list_open_entry_views(symbol=None, repository=None):
    repository = repository or OrderManagementRepository()
    rows = []
    seen_entry_ids = set()

    if hasattr(repository, "list_position_entries"):
        for item in repository.list_position_entries(symbol=symbol):
            normalized = _normalize_entry(item)
            if int(normalized.get("remaining_quantity") or 0) <= 0:
                continue
            rows.append(normalized)
            seen_entry_ids.add(normalized["entry_id"])

    for item in repository.list_buy_lots(symbol):
        normalized = _legacy_buy_lot_to_entry(item)
        if normalized["entry_id"] in seen_entry_ids:
            continue
        if int(normalized.get("remaining_quantity") or 0) <= 0:
            continue
        rows.append(normalized)

    rows.sort(
        key=lambda item: (
            int(item.get("trade_time") or 0),
            int(item.get("date") or 0),
            str(item.get("time") or ""),
            str(item.get("entry_id") or ""),
        ),
        reverse=True,
    )
    return rows


def list_open_entry_slices_compat(symbol=None, entry_ids=None, repository=None):
    repository = repository or OrderManagementRepository()
    normalized_entry_ids = {str(item).strip() for item in list(entry_ids or []) if str(item).strip()}
    rows = []
    seen_slice_ids = set()

    if hasattr(repository, "list_open_entry_slices"):
        for item in repository.list_open_entry_slices(
            symbol=symbol,
            entry_ids=list(normalized_entry_ids) if normalized_entry_ids else None,
        ):
            normalized = _normalize_entry_slice(item)
            rows.append(normalized)
            seen_slice_ids.add(normalized["entry_slice_id"])

    legacy_rows = repository.list_open_slices(symbol)
    for item in legacy_rows:
        normalized = _legacy_lot_slice_to_entry_slice(item)
        if normalized_entry_ids and normalized["entry_id"] not in normalized_entry_ids:
            continue
        if normalized["entry_slice_id"] in seen_slice_ids:
            continue
        rows.append(normalized)

    rows.sort(
        key=lambda item: (
            float(item.get("guardian_price") or 0.0),
            int(item.get("slice_seq") or 0),
            str(item.get("entry_slice_id") or ""),
        ),
        reverse=True,
    )
    return rows


def list_entry_stoploss_bindings_compat(symbol=None, enabled=True, repository=None):
    repository = repository or OrderManagementRepository()
    rows = {}

    if hasattr(repository, "list_entry_stoploss_bindings"):
        for item in repository.list_entry_stoploss_bindings(symbol=symbol, enabled=enabled):
            normalized = _normalize_entry_binding(item)
            rows[normalized["entry_id"]] = normalized

    if hasattr(repository, "list_stoploss_bindings"):
        legacy_bindings = repository.list_stoploss_bindings(
            symbol=symbol,
            enabled=enabled,
        )
        for item in legacy_bindings:
            normalized = _legacy_binding_to_entry_binding(item)
            rows.setdefault(normalized["entry_id"], normalized)

    return list(rows.values())


def get_entry_stoploss_binding(entry_id, repository=None):
    repository = repository or OrderManagementRepository()
    entry_id_text = str(entry_id or "").strip()
    if not entry_id_text:
        return None

    if hasattr(repository, "find_entry_stoploss_binding"):
        binding = repository.find_entry_stoploss_binding(entry_id_text)
        if binding is not None:
            return _normalize_entry_binding(binding)

    if not hasattr(repository, "find_stoploss_binding"):
        return None
    legacy_binding = repository.find_stoploss_binding(entry_id_text)
    if legacy_binding is None:
        return None
    return _legacy_binding_to_entry_binding(legacy_binding)


def _normalize_entry(entry):
    row = dict(entry)
    row["entry_id"] = str(row.get("entry_id") or "").strip()
    row["entry_price"] = row.get("entry_price", row.get("buy_price_real"))
    row["entry_type"] = row.get("entry_type") or "position_entry"
    row["status"] = row.get("status") or "OPEN"
    row["sell_history"] = list(row.get("sell_history") or [])
    return row


def _legacy_buy_lot_to_entry(buy_lot):
    row = dict(buy_lot)
    entry_id = str(row.get("buy_lot_id") or "").strip()
    return {
        "entry_id": entry_id,
        "buy_lot_id": entry_id,
        "symbol": row.get("symbol"),
        "entry_type": "legacy_buy_lot",
        "entry_price": row.get("buy_price_real"),
        "buy_price_real": row.get("buy_price_real"),
        "original_quantity": row.get("original_quantity"),
        "remaining_quantity": row.get("remaining_quantity"),
        "amount": row.get("amount"),
        "amount_adjust": row.get("amount_adjust"),
        "date": row.get("date"),
        "time": row.get("time"),
        "trade_time": row.get("trade_time"),
        "source": row.get("source", "legacy_buy_lot"),
        "arrange_mode": row.get("arrange_mode", "runtime_grid"),
        "status": str(row.get("status") or "").upper() or "OPEN",
        "sell_history": list(row.get("sell_history") or []),
        "name": row.get("name"),
        "stock_code": row.get("stock_code"),
    }


def _normalize_entry_slice(item):
    row = dict(item)
    row["entry_slice_id"] = str(row.get("entry_slice_id") or "").strip()
    row["entry_id"] = str(row.get("entry_id") or "").strip()
    row["status"] = row.get("status") or "OPEN"
    return row


def _legacy_lot_slice_to_entry_slice(item):
    row = dict(item)
    entry_id = str(row.get("buy_lot_id") or "").strip()
    return {
        "entry_slice_id": str(row.get("lot_slice_id") or "").strip(),
        "entry_id": entry_id,
        "buy_lot_id": entry_id,
        "slice_seq": row.get("slice_seq"),
        "guardian_price": row.get("guardian_price"),
        "original_quantity": row.get("original_quantity"),
        "remaining_quantity": row.get("remaining_quantity"),
        "remaining_amount": row.get("remaining_amount"),
        "sort_key": row.get("sort_key"),
        "date": row.get("date"),
        "time": row.get("time"),
        "trade_time": row.get("trade_time"),
        "symbol": row.get("symbol"),
        "status": row.get("status") or "OPEN",
    }


def _normalize_entry_binding(item):
    row = dict(item)
    row["entry_id"] = str(row.get("entry_id") or "").strip()
    row["binding_scope"] = row.get("binding_scope") or "position_entry"
    return row


def _legacy_binding_to_entry_binding(item):
    row = dict(item)
    entry_id = str(row.get("buy_lot_id") or "").strip()
    row["entry_id"] = entry_id
    row["buy_lot_id"] = entry_id
    row["binding_scope"] = "legacy_buy_lot"
    return row
