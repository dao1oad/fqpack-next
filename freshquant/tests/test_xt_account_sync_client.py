# -*- coding: utf-8 -*-

from types import SimpleNamespace


def test_query_client_supports_legacy_account_resolver_signature():
    from freshquant.xt_account_sync.client import XtAccountQueryClient

    seen = {}

    class FakeTrader:
        def __init__(self, path, session_id):
            self.path = path
            self.session_id = session_id
            self.started = False
            self.subscribed_account = None

        def start(self):
            self.started = True

        def connect(self):
            return 0

        def subscribe(self, account):
            self.subscribed_account = account
            return 0

        def query_stock_asset(self, account):
            return {
                "account_id": account.account_id,
                "account_type": account.account_type,
                "path": self.path,
                "session_id": self.session_id,
            }

    def legacy_resolver(query_param=None, stock_account_cls=None):
        seen["account_id"] = query_param("xtquant.account", "")
        seen["account_type"] = query_param("xtquant.account_type", "STOCK")
        account = SimpleNamespace(
            account_id=seen["account_id"],
            account_type=seen["account_type"],
        )
        return account, seen["account_id"], seen["account_type"]

    settings_provider = SimpleNamespace(
        xtquant=SimpleNamespace(
            path="D:/xtquant",
            account="068000076370",
            account_type="CREDIT",
        )
    )
    client = XtAccountQueryClient(
        session_id=123456,
        trader_factory=FakeTrader,
        settings_provider=settings_provider,
        account_resolver=legacy_resolver,
    )

    asset = client.query_stock_asset()

    assert asset == {
        "account_id": "068000076370",
        "account_type": "CREDIT",
        "path": "D:/xtquant",
        "session_id": 123456,
    }
    assert client.account_id == "068000076370"
    assert client.account_type == "CREDIT"
    assert seen == {
        "account_id": "068000076370",
        "account_type": "CREDIT",
    }


def test_query_client_reconnects_after_empty_credit_detail_response():
    from freshquant.xt_account_sync.client import XtAccountQueryClient

    class FakeTrader:
        def __init__(self, detail):
            self.detail = detail
            self.started = False
            self.stopped = False
            self.connect_calls = 0
            self.subscribe_calls = 0

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def connect(self):
            self.connect_calls += 1
            return 0

        def subscribe(self, account):
            self.subscribe_calls += 1
            return 0

        def query_credit_detail(self, account):
            return self.detail

    first_trader = FakeTrader([])
    second_trader = FakeTrader([{"m_dAvailable": 9000.0, "m_dFinDebt": 2000.0}])
    traders = iter([first_trader, second_trader])

    def resolve_account(settings_provider=None):
        xtquant = settings_provider.xtquant
        account = SimpleNamespace(
            account_id=xtquant.account,
            account_type=xtquant.account_type,
        )
        return account, xtquant.account, xtquant.account_type

    settings_provider = SimpleNamespace(
        xtquant=SimpleNamespace(
            path="D:/xtquant",
            account="068000076370",
            account_type="CREDIT",
        )
    )
    client = XtAccountQueryClient(
        session_id=123456,
        trader_factory=lambda path, session_id: next(traders),
        settings_provider=settings_provider,
        account_resolver=resolve_account,
    )

    detail = client.query_credit_detail()

    assert detail == [{"m_dAvailable": 9000.0, "m_dFinDebt": 2000.0}]
    assert first_trader.connect_calls == 1
    assert first_trader.stopped is True
    assert second_trader.connect_calls == 1


def test_query_client_reraises_retryable_xt_failure_after_retry_exhaustion():
    import pytest

    from freshquant.xt_account_sync.client import XtAccountQueryClient

    class FailingTrader:
        def __init__(self):
            self.connect_calls = 0
            self.stopped = False

        def start(self):
            return None

        def stop(self):
            self.stopped = True

        def connect(self):
            self.connect_calls += 1
            return 0

        def subscribe(self, account):
            return 0

        def query_credit_detail(self, account):
            raise RuntimeError("xtquant connect failed: -1")

    traders = [FailingTrader(), FailingTrader()]
    trader_iter = iter(traders)

    def resolve_account(settings_provider=None):
        xtquant = settings_provider.xtquant
        account = SimpleNamespace(
            account_id=xtquant.account,
            account_type=xtquant.account_type,
        )
        return account, xtquant.account, xtquant.account_type

    settings_provider = SimpleNamespace(
        xtquant=SimpleNamespace(
            path="D:/xtquant",
            account="068000076370",
            account_type="CREDIT",
        )
    )
    client = XtAccountQueryClient(
        session_id=123456,
        trader_factory=lambda path, session_id: next(trader_iter),
        settings_provider=settings_provider,
        account_resolver=resolve_account,
    )

    with pytest.raises(RuntimeError, match="xtquant connect failed: -1"):
        client.query_credit_detail()

    assert traders[0].stopped is True
    assert traders[1].stopped is True
