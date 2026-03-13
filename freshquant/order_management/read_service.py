# -*- coding: utf-8 -*-

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from freshquant.order_management.repository import OrderManagementRepository
from freshquant.util.code import normalize_to_base_code

_TIME_FIELDS = {"created_at", "updated_at", "submitted_at"}
_FAILED_STATES = {"FAILED", "REJECTED", "ERROR"}


class OrderManagementReadService:
    def __init__(self, repository=None):
        self.repository = repository or OrderManagementRepository()

    def list_orders(
        self,
        *,
        symbol=None,
        side=None,
        state=None,
        source=None,
        strategy_name=None,
        account_type=None,
        internal_order_id=None,
        request_id=None,
        broker_order_id=None,
        date_from=None,
        date_to=None,
        time_field="updated_at",
        missing_broker_only=False,
        page=1,
        size=20,
    ):
        rows = self._query_rows(
            symbol=symbol,
            side=side,
            state=state,
            source=source,
            strategy_name=strategy_name,
            account_type=account_type,
            internal_order_id=internal_order_id,
            request_id=request_id,
            broker_order_id=broker_order_id,
            date_from=date_from,
            date_to=date_to,
            time_field=time_field,
            missing_broker_only=missing_broker_only,
        )
        page_value = max(int(page or 1), 1)
        size_value = max(int(size or 20), 1)
        start = (page_value - 1) * size_value
        end = start + size_value
        return {
            "rows": rows[start:end],
            "total": len(rows),
            "page": page_value,
            "size": size_value,
        }

    def get_order_detail(self, internal_order_id):
        order_id = str(internal_order_id or "").strip()
        if not order_id:
            raise ValueError("order not found")
        order = self.repository.find_order(order_id)
        if order is None:
            raise ValueError("order not found")
        request = self.repository.find_order_request(order.get("request_id"))
        events = sorted(
            self.repository.list_order_events(internal_order_ids=[order_id]),
            key=lambda item: item.get("created_at") or "",
        )
        trades = sorted(
            self.repository.list_trade_facts(internal_order_ids=[order_id]),
            key=lambda item: (
                str(item.get("trade_time") or ""),
                item.get("trade_fact_id") or "",
            ),
        )
        assembled_order = _assemble_order_row(order, request)
        return {
            "order": assembled_order,
            "request": dict(request or {}),
            "events": [dict(item) for item in events],
            "trades": [dict(item) for item in trades],
            "identifiers": {
                "trace_id": assembled_order.get("trace_id"),
                "intent_id": assembled_order.get("intent_id"),
                "request_id": assembled_order.get("request_id"),
                "internal_order_id": assembled_order.get("internal_order_id"),
                "broker_order_id": assembled_order.get("broker_order_id"),
            },
        }

    def get_stats(
        self,
        *,
        symbol=None,
        side=None,
        state=None,
        source=None,
        strategy_name=None,
        account_type=None,
        internal_order_id=None,
        request_id=None,
        broker_order_id=None,
        date_from=None,
        date_to=None,
        time_field="updated_at",
        missing_broker_only=False,
    ):
        rows = self._query_rows(
            symbol=symbol,
            side=side,
            state=state,
            source=source,
            strategy_name=strategy_name,
            account_type=account_type,
            internal_order_id=internal_order_id,
            request_id=request_id,
            broker_order_id=broker_order_id,
            date_from=date_from,
            date_to=date_to,
            time_field=time_field,
            missing_broker_only=missing_broker_only,
        )
        state_distribution = Counter()
        side_distribution = {"buy": 0, "sell": 0}
        latest_updated_at = ""
        for row in rows:
            state_value = str(row.get("state") or "").strip().upper()
            if state_value:
                state_distribution[state_value] += 1
            side_value = str(row.get("side") or "").strip().lower()
            if side_value in side_distribution:
                side_distribution[side_value] += 1
            updated_at = str(row.get("updated_at") or "")
            if updated_at > latest_updated_at:
                latest_updated_at = updated_at

        return {
            "total": len(rows),
            "side_distribution": {
                "buy": side_distribution["buy"],
                "sell": side_distribution["sell"],
            },
            "state_distribution": dict(sorted(state_distribution.items())),
            "missing_broker_order_count": sum(
                1 for row in rows if row.get("broker_order_id") in (None, "")
            ),
            "latest_updated_at": latest_updated_at or None,
            "filled_count": sum(
                1 for row in rows if str(row.get("state") or "").upper() == "FILLED"
            ),
            "partial_filled_count": sum(
                1
                for row in rows
                if str(row.get("state") or "").upper() == "PARTIAL_FILLED"
            ),
            "canceled_count": sum(
                1
                for row in rows
                if "CANCEL" in str(row.get("state") or "").upper()
            ),
            "failed_count": sum(
                1
                for row in rows
                if str(row.get("state") or "").upper() in _FAILED_STATES
            ),
        }

    def _query_rows(
        self,
        *,
        symbol=None,
        side=None,
        state=None,
        source=None,
        strategy_name=None,
        account_type=None,
        internal_order_id=None,
        request_id=None,
        broker_order_id=None,
        date_from=None,
        date_to=None,
        time_field="updated_at",
        missing_broker_only=False,
    ):
        time_field_value = _normalize_time_field(time_field)
        lower_bound = _parse_filter_datetime(date_from, upper_bound=False)
        upper_bound = _parse_filter_datetime(date_to, upper_bound=True)
        normalized_symbol = _normalize_symbol(symbol)
        states = _normalize_filter_values(state, transform=str.upper)
        sides = _normalize_filter_values(side, transform=str.lower)
        normalized_source = _normalize_optional_text(source)
        normalized_strategy_name = _normalize_optional_text(strategy_name)
        normalized_account_type = _normalize_optional_text(account_type, transform=str.upper)
        normalized_request_id = _normalize_optional_text(request_id)
        normalized_internal_order_id = _normalize_optional_text(internal_order_id)
        normalized_broker_order_id = _normalize_optional_text(broker_order_id)

        orders = self.repository.list_orders(
            symbol=normalized_symbol,
            states=states or None,
            missing_broker_only=bool(missing_broker_only),
        )
        if normalized_request_id is not None:
            orders = [
                item for item in orders if item.get("request_id") == normalized_request_id
            ]
        if normalized_internal_order_id is not None:
            orders = [
                item
                for item in orders
                if item.get("internal_order_id") == normalized_internal_order_id
            ]
        if normalized_broker_order_id is not None:
            orders = [
                item
                for item in orders
                if str(item.get("broker_order_id") or "").strip()
                == normalized_broker_order_id
            ]
        if sides:
            orders = [
                item
                for item in orders
                if str(item.get("side") or "").strip().lower() in sides
            ]

        request_ids = {
            item.get("request_id")
            for item in orders
            if item.get("request_id") is not None
        }
        request_map = {
            item.get("request_id"): item
            for item in self.repository.list_order_requests(request_ids=list(request_ids))
            if item.get("request_id") is not None
        }

        rows = []
        for order in orders:
            request = request_map.get(order.get("request_id"))
            row = _assemble_order_row(order, request)
            if normalized_source is not None and row.get("source") != normalized_source:
                continue
            if (
                normalized_strategy_name is not None
                and row.get("strategy_name") != normalized_strategy_name
            ):
                continue
            if (
                normalized_account_type is not None
                and str(row.get("account_type") or "").strip().upper()
                != normalized_account_type
            ):
                continue
            if not _row_matches_time_window(
                row,
                time_field=time_field_value,
                lower_bound=lower_bound,
                upper_bound=upper_bound,
            ):
                continue
            rows.append(row)
        rows.sort(key=_order_sort_key, reverse=True)
        return rows


def _assemble_order_row(order, request):
    order_row = dict(order or {})
    request_row = dict(request or {})
    return {
        **order_row,
        "request_id": order_row.get("request_id"),
        "symbol": _normalize_symbol(order_row.get("symbol")),
        "side": str(order_row.get("side") or "").strip().lower(),
        "state": str(order_row.get("state") or "").strip().upper(),
        "source": _normalize_optional_text(
            request_row.get("source") or order_row.get("source_type")
        ),
        "source_type": _normalize_optional_text(order_row.get("source_type")),
        "strategy_name": _normalize_optional_text(request_row.get("strategy_name")),
        "account_type": _normalize_optional_text(
            order_row.get("account_type") or request_row.get("account_type"),
            transform=str.upper,
        ),
        "price": request_row.get("price"),
        "quantity": request_row.get("quantity"),
        "remark": _normalize_optional_text(request_row.get("remark")),
        "scope_type": _normalize_optional_text(request_row.get("scope_type")),
        "scope_ref_id": _normalize_optional_text(request_row.get("scope_ref_id")),
        "created_at": _normalize_optional_text(request_row.get("created_at")),
        "trace_id": _normalize_optional_text(
            order_row.get("trace_id") or request_row.get("trace_id")
        ),
        "intent_id": _normalize_optional_text(
            order_row.get("intent_id") or request_row.get("intent_id")
        ),
    }


def _order_sort_key(row):
    return (
        row.get("updated_at") or "",
        row.get("created_at") or "",
        row.get("submitted_at") or "",
        row.get("internal_order_id") or "",
    )


def _row_matches_time_window(row, *, time_field, lower_bound, upper_bound):
    if lower_bound is None and upper_bound is None:
        return True
    timestamp = _parse_filter_datetime(row.get(time_field), upper_bound=False)
    if timestamp is None:
        return False
    if lower_bound is not None and timestamp < lower_bound:
        return False
    if upper_bound is not None and timestamp > upper_bound:
        return False
    return True


def _normalize_symbol(value):
    text = str(value or "").strip()
    if not text:
        return None
    normalized = normalize_to_base_code(text)
    return normalized or text


def _normalize_optional_text(value, transform=None):
    text = str(value or "").strip()
    if not text:
        return None
    return transform(text) if callable(transform) else text


def _normalize_filter_values(value, *, transform=None):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = str(value).split(",")
    normalized = []
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        normalized.append(transform(text) if callable(transform) else text)
    return normalized


def _normalize_time_field(value):
    field = str(value or "updated_at").strip()
    if field not in _TIME_FIELDS:
        raise ValueError("invalid time_field")
    return field


def _parse_filter_datetime(value, *, upper_bound):
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) == 10:
        text = f"{text}T23:59:59+00:00" if upper_bound else f"{text}T00:00:00+00:00"
    elif " " in text and "T" not in text:
        text = text.replace(" ", "T")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("invalid datetime filter") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
