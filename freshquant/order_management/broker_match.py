# -*- coding: utf-8 -*-

from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    identity_conflicts,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    resolve_trading_day,
)

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
    account_id=None,
    order_sysid=None,
    trading_day=None,
    pinned_internal_order_id=None,
):
    if repository is None:
        return None

    report = report or {}
    report_identity = {
        "account_id": normalize_account_id(
            account_id if account_id is not None else report.get("account_id")
        ),
        "order_sysid": normalize_identifier(
            order_sysid if order_sysid is not None else report.get("order_sysid")
        ),
        "trading_day": resolve_trading_day(
            report,
            trading_day=trading_day,
            report_time=report_time,
        ),
        "symbol": normalize_symbol(
            symbol or report.get("symbol") or report.get("stock_code")
        ),
        "broker_order_id": normalize_identifier(
            broker_order_id
            if broker_order_id is not None
            else report.get("broker_order_id") or report.get("order_id")
        ),
    }
    order_type = order_type if order_type is not None else report.get("order_type")
    report_identity["side"] = normalize_side(side) or side_from_order_type(order_type)

    if pinned_internal_order_id not in (None, "", "None"):
        candidate = repository.find_order(str(pinned_internal_order_id))
        if candidate is None:
            raise BrokerIdentityConflict(
                f"pinned internal order does not exist: {pinned_internal_order_id}"
            )
        conflicts = identity_conflicts(_candidate_identity(candidate), report_identity)
        if conflicts:
            dimensions = ", ".join(sorted(conflicts))
            raise BrokerIdentityConflict(
                f"pinned internal order conflicts with broker report: {dimensions}"
            )
        return candidate

    candidates = _list_order_candidates(
        repository,
        broker_order_id=report_identity["broker_order_id"],
        order_sysid=report_identity["order_sysid"],
    )
    compatible = [
        candidate
        for candidate in candidates
        if not identity_conflicts(_candidate_identity(candidate), report_identity)
    ]
    if not compatible:
        return None

    if (
        report_identity["account_id"]
        and report_identity["trading_day"]
        and report_identity["order_sysid"]
    ):
        primary = [
            candidate
            for candidate in compatible
            if normalize_account_id(candidate.get("account_id"))
            == report_identity["account_id"]
            and resolve_trading_day(candidate) == report_identity["trading_day"]
            and normalize_identifier(candidate.get("order_sysid"))
            == report_identity["order_sysid"]
        ]
        if len(primary) == 1:
            return primary[0]
        if len(primary) > 1:
            return None

    fallback_fields = (
        "account_id",
        "trading_day",
        "symbol",
        "side",
        "broker_order_id",
    )
    if all(report_identity.get(field) is not None for field in fallback_fields):
        exact_fallback = [
            candidate
            for candidate in compatible
            if all(
                _candidate_identity(candidate).get(field) == report_identity[field]
                for field in fallback_fields
            )
        ]
        if len(exact_fallback) == 1:
            return exact_fallback[0]
        if len(exact_fallback) > 1:
            return None

    return None


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


def _list_order_candidates(repository, *, broker_order_id, order_sysid):
    candidates = []
    if broker_order_id is not None and hasattr(
        repository, "list_orders_by_broker_order_id"
    ):
        candidates.extend(repository.list_orders_by_broker_order_id(broker_order_id))
    elif broker_order_id is not None and hasattr(
        repository, "find_order_by_broker_order_id"
    ):
        order = repository.find_order_by_broker_order_id(broker_order_id)
        if order is not None:
            candidates.append(order)

    if order_sysid is not None and hasattr(repository, "list_orders"):
        candidates.extend(
            order
            for order in repository.list_orders()
            if normalize_identifier(order.get("order_sysid")) == order_sysid
        )

    deduplicated = {}
    for candidate in candidates:
        key = normalize_identifier(candidate.get("internal_order_id")) or id(candidate)
        deduplicated[key] = candidate
    return list(deduplicated.values())


def _candidate_side(order):
    return normalize_side(order.get("side")) or side_from_order_type(
        order.get("broker_order_type")
    )


def _candidate_identity(order):
    return {
        "account_id": order.get("account_id"),
        "order_sysid": order.get("order_sysid"),
        "trading_day": resolve_trading_day(order),
        "symbol": order.get("symbol"),
        "side": _candidate_side(order),
        "broker_order_id": order.get("broker_order_id"),
    }


def _order_type_equivalent(left, right):
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left).strip().lower() == str(right).strip().lower()
