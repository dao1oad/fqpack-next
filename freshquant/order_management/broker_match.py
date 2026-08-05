# -*- coding: utf-8 -*-

from freshquant.order_management.broker_correlation import (
    looks_like_broker_correlation_token,
    normalize_broker_correlation_token,
)
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
    broker_correlation_token=None,
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
    report_identity["broker_order_type"] = order_type

    raw_correlation_token = (
        broker_correlation_token
        if broker_correlation_token is not None
        else report.get("broker_correlation_token") or report.get("order_remark")
    )
    correlation_token = normalize_broker_correlation_token(raw_correlation_token)
    if correlation_token is None and looks_like_broker_correlation_token(
        raw_correlation_token
    ):
        raise BrokerIdentityConflict("broker correlation token is malformed")
    if correlation_token is not None:
        correlated_order = _find_order_by_broker_correlation_token(
            repository,
            correlation_token,
        )
        if correlated_order is None:
            raise BrokerIdentityConflict("broker correlation token is unknown")
        correlated_internal_order_id = normalize_identifier(
            correlated_order.get("internal_order_id")
        )
        if correlated_internal_order_id is None:
            raise BrokerIdentityConflict(
                "broker correlation token has no internal order owner"
            )
        if (
            pinned_internal_order_id not in (None, "", "None")
            and normalize_identifier(pinned_internal_order_id)
            != correlated_internal_order_id
        ):
            raise BrokerIdentityConflict(
                "pinned internal order conflicts with broker correlation token"
            )
        pinned_internal_order_id = correlated_internal_order_id

    if pinned_internal_order_id not in (None, "", "None"):
        candidate = repository.find_order(str(pinned_internal_order_id))
        if candidate is None:
            raise BrokerIdentityConflict(
                f"pinned internal order does not exist: {pinned_internal_order_id}"
            )
        conflicts = _identity_conflicts(_candidate_identity(candidate), report_identity)
        if conflicts:
            dimensions = ", ".join(sorted(conflicts))
            raise BrokerIdentityConflict(
                f"pinned internal order conflicts with broker report: {dimensions}"
            )
        _assert_no_competing_broker_identity(
            repository,
            candidate=candidate,
            report_identity=report_identity,
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
        if not _identity_conflicts(_candidate_identity(candidate), report_identity)
    ]
    matching_unbound_orders = _list_matching_unbound_orders(
        repository,
        report_identity=report_identity,
    )
    if not compatible:
        if matching_unbound_orders:
            raise BrokerIdentityConflict(
                "broker report lacks correlation token for unbound internal order candidates"
            )
        return None
    if matching_unbound_orders:
        raise BrokerIdentityConflict(
            "broker report has bound and unbound internal order candidates without a correlation token"
        )

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
            raise BrokerIdentityConflict(
                "broker report matches multiple primary internal orders"
            )

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
            raise BrokerIdentityConflict(
                "broker report matches multiple fallback internal orders"
            )

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
        "broker_order_type": order.get("broker_order_type"),
    }


def _identity_conflicts(candidate_identity, report_identity):
    conflicts = identity_conflicts(candidate_identity, report_identity)
    candidate_order_type = candidate_identity.get("broker_order_type")
    report_order_type = report_identity.get("broker_order_type")
    if (
        candidate_order_type not in (None, "")
        and report_order_type not in (None, "")
        and not _order_type_equivalent(candidate_order_type, report_order_type)
    ):
        conflicts["broker_order_type"] = (
            candidate_order_type,
            report_order_type,
        )
    return conflicts


def _find_order_by_broker_correlation_token(repository, token):
    finder = getattr(repository, "find_order_by_broker_correlation_token", None)
    if callable(finder):
        return finder(token)
    if not hasattr(repository, "list_orders"):
        return None
    matches = [
        order
        for order in repository.list_orders()
        if normalize_broker_correlation_token(order.get("broker_correlation_token"))
        == token
    ]
    if len(matches) > 1:
        raise BrokerIdentityConflict(
            "broker correlation token has multiple internal order owners"
        )
    return matches[0] if matches else None


def _list_matching_unbound_orders(repository, *, report_identity):
    required_fields = ("account_id", "trading_day", "symbol", "side")
    if not hasattr(repository, "list_orders") or not all(
        report_identity.get(field) is not None for field in required_fields
    ):
        return []
    try:
        candidates = repository.list_orders(
            symbol=report_identity["symbol"],
            states=_NONTERMINAL_STATES,
            missing_broker_only=True,
        )
    except TypeError:
        candidates = repository.list_orders()
    return [
        candidate
        for candidate in candidates
        if normalize_identifier(candidate.get("broker_order_id")) is None
        and str(candidate.get("state") or "").upper() in _NONTERMINAL_STATES
        and all(
            _candidate_identity(candidate).get(field) == report_identity[field]
            for field in required_fields
        )
    ]


def _assert_no_competing_broker_identity(
    repository,
    *,
    candidate,
    report_identity,
):
    candidate_internal_order_id = normalize_identifier(
        candidate.get("internal_order_id")
    )
    for other in _list_order_candidates(
        repository,
        broker_order_id=report_identity.get("broker_order_id"),
        order_sysid=report_identity.get("order_sysid"),
    ):
        other_internal_order_id = normalize_identifier(other.get("internal_order_id"))
        if (
            candidate_internal_order_id is not None
            and other_internal_order_id == candidate_internal_order_id
        ):
            continue
        if not identity_conflicts(_candidate_identity(other), report_identity):
            raise BrokerIdentityConflict(
                "broker identity is already owned by another internal order"
            )


def _order_type_equivalent(left, right):
    if left in (None, "") or right in (None, ""):
        return False
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left).strip().lower() == str(right).strip().lower()
