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
