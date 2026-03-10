from fqxtrade.xtquant.account import (
    resolve_broker_submit_mode,
    resolve_stock_account,
)


def test_resolve_stock_account_uses_configured_account_type():
    seen = {}

    def fake_query_param(key, default=None):
        values = {
            "xtquant.account": "068000076370",
            "xtquant.account_type": "CREDIT",
        }
        return values.get(key, default)

    class FakeStockAccount:
        def __init__(self, account_id, account_type="STOCK"):
            seen["account_id"] = account_id
            seen["account_type"] = account_type

    account, account_id, account_type = resolve_stock_account(
        query_param=fake_query_param,
        stock_account_cls=FakeStockAccount,
    )

    assert isinstance(account, FakeStockAccount)
    assert account_id == "068000076370"
    assert account_type == "CREDIT"
    assert seen == {
        "account_id": "068000076370",
        "account_type": "CREDIT",
    }


def test_resolve_stock_account_defaults_to_stock():
    seen = {}

    def fake_query_param(key, default=None):
        values = {
            "xtquant.account": "068000076370",
        }
        return values.get(key, default)

    class FakeStockAccount:
        def __init__(self, account_id, account_type="STOCK"):
            seen["account_id"] = account_id
            seen["account_type"] = account_type

    account, account_id, account_type = resolve_stock_account(
        query_param=fake_query_param,
        stock_account_cls=FakeStockAccount,
    )

    assert isinstance(account, FakeStockAccount)
    assert account_id == "068000076370"
    assert account_type == "STOCK"
    assert seen == {
        "account_id": "068000076370",
        "account_type": "STOCK",
    }


def test_resolve_broker_submit_mode_defaults_to_normal():
    def fake_query_param(key, default=None):
        values = {
            "xtquant.account": "068000076370",
        }
        return values.get(key, default)

    assert resolve_broker_submit_mode(query_param=fake_query_param) == "normal"


def test_resolve_broker_submit_mode_accepts_observe_only():
    def fake_query_param(key, default=None):
        values = {
            "xtquant.broker_submit_mode": "observe_only",
        }
        return values.get(key, default)

    assert resolve_broker_submit_mode(query_param=fake_query_param) == "observe_only"


def test_resolve_broker_submit_mode_normalizes_invalid_value_to_normal():
    def fake_query_param(key, default=None):
        values = {
            "xtquant.broker_submit_mode": "paper_trade",
        }
        return values.get(key, default)

    assert resolve_broker_submit_mode(query_param=fake_query_param) == "normal"
