# -*- coding: utf-8 -*-
"""PR3：buy_cluster 聚类的 account_id fail-closed 语义（单元级）。"""

from freshquant.order_management.entry_aggregation import select_cluster_entry


def _entry(
    entry_id="entry_1",
    symbol="000001",
    account_id="acc-1",
    position_type="base",
    remaining_quantity=100,
    member_key="key_1",
    trade_time=1710000000,
    trading_day=20240310,
    entry_price=10.0,
):
    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "account_id": account_id,
        "position_type": position_type,
        "remaining_quantity": remaining_quantity,
        "entry_price": entry_price,
        "sell_history": [],
        "aggregation_members": [
            {
                "broker_order_key": member_key,
                "trade_time": trade_time,
                "trading_day": trading_day,
                "entry_price": entry_price,
            }
        ],
        "aggregation_member_keys": [member_key],
    }


def _fact(
    symbol="000001",
    account_id="acc-1",
    trade_time=1710000060,
    price=10.01,
):
    return {
        "symbol": symbol,
        "account_id": account_id,
        "trade_time": trade_time,
        "date": 20240310,
        "time": "09:31:00",
        "price": price,
    }


def test_cluster_matches_same_account_entry():
    selected = select_cluster_entry(
        [_entry()],
        _fact(),
        "group_key",
        position_type="base",
    )

    assert selected is not None
    assert selected["entry_id"] == "entry_1"


def test_cluster_does_not_match_cross_account_entry():
    selected = select_cluster_entry(
        [_entry(account_id="acc-2")],
        _fact(account_id="acc-1"),
        "group_key",
        position_type="base",
    )

    assert selected is None


def test_cluster_does_not_match_entry_without_account():
    selected = select_cluster_entry(
        [_entry(account_id=None)],
        _fact(account_id="acc-1"),
        "group_key",
        position_type="base",
    )

    assert selected is None


def test_cluster_fail_closed_without_group_account():
    selected = select_cluster_entry(
        [_entry(account_id="acc-1")],
        _fact(account_id=None),
        "group_key",
        position_type="base",
    )

    assert selected is None


def test_exact_member_key_match_wins_before_account_filter():
    selected = select_cluster_entry(
        [_entry(account_id="acc-2", member_key="group_key")],
        _fact(account_id="acc-1"),
        "group_key",
        position_type="base",
    )

    assert selected is not None
    assert selected["entry_id"] == "entry_1"
