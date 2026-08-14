# -*- coding: utf-8 -*-

from freshquant.order_management.broker_correlation import (
    looks_like_broker_correlation_token,
    normalize_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    build_broker_order_key,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    resolve_trading_day,
)

_BUY_ORDER_TYPES = {23, 27, 28, "23", "27", "28", "buy", "BUY"}
_SELL_ORDER_TYPES = {24, 31, 32, "24", "31", "32", "sell", "SELL"}


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
    if repository is None:
        return None
    report = report or {}
    raw_correlation_token = report.get("broker_correlation_token") or report.get(
        "order_remark"
    )
    correlation_token = normalize_broker_correlation_token(raw_correlation_token)
    if correlation_token is None and looks_like_broker_correlation_token(
        raw_correlation_token
    ):
        return None
    if correlation_token is not None:
        finder = getattr(repository, "find_order_by_broker_correlation_token", None)
        candidate = finder(correlation_token) if callable(finder) else None
        if candidate is None:
            return None
        return (
            candidate
            if _candidate_matches_report(candidate, report, trust_correlation=True)
            else None
        )

    symbol = normalize_symbol(
        symbol or report.get("symbol") or report.get("stock_code")
    )
    order_type = order_type if order_type is not None else report.get("order_type")
    side = normalize_side(side) or side_from_order_type(order_type)
    account_id = normalize_account_id(report.get("account_id"))
    order_sysid = normalize_identifier(report.get("order_sysid"))
    trading_day = resolve_trading_day(report, report_time=report_time)
    broker_order_id = normalize_identifier(broker_order_id)
    broker_order_key = build_broker_order_key(
        account_id=account_id,
        order_sysid=order_sysid,
        trading_day=trading_day,
        symbol=symbol,
        side=side,
        broker_order_id=broker_order_id,
        strict=False,
    )
    if broker_order_key is not None:
        broker_order = repository.find_broker_order(broker_order_key)
        if broker_order is not None and _candidate_matches_report(broker_order, report):
            return repository.find_order(broker_order.get("internal_order_id"))

    if broker_order_id is None:
        return None
    candidates = [
        candidate
        for candidate in _list_order_candidates(repository, broker_order_id)
        if _candidate_proves_full_identity(
            candidate,
            account_id=account_id,
            order_sysid=order_sysid,
            trading_day=trading_day,
            symbol=symbol,
            side=side,
            broker_order_id=broker_order_id,
        )
    ]
    return candidates[0] if len(candidates) == 1 else None


def _candidate_matches_report(candidate, report, *, trust_correlation=False):
    for field, expected, normalizer in (
        ("account_id", report.get("account_id"), normalize_account_id),
        ("order_sysid", report.get("order_sysid"), normalize_identifier),
        (
            "trading_day",
            resolve_trading_day(report),
            lambda value: resolve_trading_day({"trading_day": value}),
        ),
        ("symbol", report.get("symbol") or report.get("stock_code"), normalize_symbol),
        (
            "side",
            (
                None
                if trust_correlation
                else report.get("side")
                or side_from_order_type(report.get("order_type"))
            ),
            normalize_side,
        ),
        (
            "broker_order_id",
            report.get("broker_order_id") or report.get("order_id"),
            normalize_identifier,
        ),
    ):
        right = normalizer(expected)
        left = normalizer(candidate.get(field))
        if right is not None and left is not None and left != right:
            return False
    return True


def _candidate_proves_full_identity(
    candidate,
    *,
    account_id,
    order_sysid,
    trading_day,
    symbol,
    side,
    broker_order_id,
):
    if account_id is None or trading_day is None:
        return False
    if order_sysid is None and None in (symbol, side, broker_order_id):
        return False
    candidate_order_sysid = normalize_identifier(candidate.get("order_sysid"))
    if order_sysid is not None and candidate_order_sysid is not None:
        if candidate_order_sysid != order_sysid:
            return False
    elif order_sysid is not None and None in (symbol, side, broker_order_id):
        return False
    return all(
        (
            normalize_account_id(candidate.get("account_id")) == account_id,
            resolve_trading_day(candidate) == trading_day,
            (
                candidate_order_sysid == order_sysid
                if order_sysid is not None and candidate_order_sysid is not None
                else normalize_symbol(candidate.get("symbol")) == symbol
                and normalize_side(candidate.get("side")) == side
                and normalize_identifier(candidate.get("broker_order_id"))
                == broker_order_id
            ),
        )
    )


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
    return list(repository.list_orders_by_broker_order_id(broker_order_id))
