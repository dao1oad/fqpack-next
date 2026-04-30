# -*- coding: utf-8 -*-

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BEIJING_TZ = ZoneInfo("Asia/Shanghai")
_BUY_ORDER_TYPES = {23, 27, 28, "23", "27", "28", "buy", "BUY"}
_SELL_ORDER_TYPES = {24, 31, 32, "24", "31", "32", "sell", "SELL"}
_NONTERMINAL_STATES = {
    "ACCEPTED",
    "VALIDATED",
    "QUEUED",
    "SUBMITTING",
    "SUBMITTED",
    "PARTIAL_FILLED",
    "CANCEL_REQUESTED",
    "INFERRED_PENDING",
}


def find_order_for_broker_report(
    repository,
    *,
    broker_order_id,
    report=None,
    symbol=None,
    side=None,
    order_type=None,
    report_time=None,
):
    if repository is None or broker_order_id in (None, "", "None"):
        return None

    candidates = _list_order_candidates(repository, broker_order_id)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    report = report or {}
    symbol = _normalize_symbol(
        symbol or report.get("symbol") or report.get("stock_code")
    )
    order_type = order_type if order_type is not None else report.get("order_type")
    side = _normalize_side(side) or side_from_order_type(order_type)
    report_time = _coalesce_report_time(report_time, report)

    filtered = candidates
    if symbol:
        by_symbol = [
            item for item in filtered if _normalize_symbol(item.get("symbol")) == symbol
        ]
        if by_symbol:
            filtered = by_symbol

    if side:
        by_side = [item for item in filtered if _candidate_side(item) in (None, side)]
        if by_side:
            filtered = by_side

    if order_type is not None and len(filtered) > 1:
        report_side = side_from_order_type(order_type)
        by_order_type = [
            item
            for item in filtered
            if _order_type_equivalent(item.get("broker_order_type"), order_type)
            or (
                report_side is not None
                and side_from_order_type(item.get("broker_order_type")) == report_side
            )
        ]
        if by_order_type:
            filtered = by_order_type

    scored = sorted(
        ((_candidate_score(item, report_time), item) for item in filtered),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored:
        return None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def side_from_order_type(order_type):
    if order_type in _BUY_ORDER_TYPES:
        return "buy"
    if order_type in _SELL_ORDER_TYPES:
        return "sell"
    try:
        numeric = int(order_type)
    except (TypeError, ValueError):
        return None
    if numeric in {23, 27, 28}:
        return "buy"
    if numeric in {24, 31, 32}:
        return "sell"
    return None


def _list_order_candidates(repository, broker_order_id):
    if hasattr(repository, "list_orders_by_broker_order_id"):
        return list(repository.list_orders_by_broker_order_id(broker_order_id))

    order = repository.find_order_by_broker_order_id(broker_order_id)
    return [order] if order is not None else []


def _candidate_side(order):
    return _normalize_side(order.get("side")) or side_from_order_type(
        order.get("broker_order_type")
    )


def _candidate_score(order, report_time):
    state_score = 1 if order.get("state") in _NONTERMINAL_STATES else 0
    submitted_at = _parse_order_datetime(
        order.get("submitted_at") or order.get("updated_at") or order.get("created_at")
    )
    if report_time is None or submitted_at is None:
        time_score = 0
        distance_score = 0
    else:
        distance = abs((report_time - submitted_at).total_seconds())
        time_score = 1
        distance_score = -distance
    recency = submitted_at.timestamp() if submitted_at is not None else 0
    return (time_score, state_score, distance_score, recency)


def _coalesce_report_time(report_time, report):
    if report_time is not None:
        return _parse_report_datetime(report_time)
    for key in ("traded_time", "trade_time", "order_time"):
        if report.get(key) is not None:
            return _parse_report_datetime(report.get(key))
    return None


def _parse_report_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _as_aware(value)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return _parse_order_datetime(value)


def _parse_order_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return _as_aware(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _as_aware(parsed)


def _as_aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=_BEIJING_TZ).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_symbol(value):
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    return text[:6] if len(text) >= 6 else text


def _normalize_side(value):
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"buy", "sell"}:
        return text
    return None


def _order_type_equivalent(left, right):
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left).strip().lower() == str(right).strip().lower()
