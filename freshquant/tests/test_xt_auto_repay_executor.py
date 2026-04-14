# -*- coding: utf-8 -*-

from types import SimpleNamespace

from freshquant.carnation import xtconstant


class FakeTrader:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0
        self.connect_calls = 0
        self.subscribe_calls = []
        self.order_calls = []

    def start(self):
        self.start_calls += 1

    def connect(self):
        self.connect_calls += 1
        return 0

    def stop(self):
        self.stop_calls += 1

    def subscribe(self, account):
        self.subscribe_calls.append(account)
        return 0

    def order_stock(
        self,
        account,
        stock_code,
        order_type,
        order_volume,
        price_type,
        price,
        strategy_name="",
        order_remark="",
    ):
        self.order_calls.append(
            {
                "account": account,
                "stock_code": stock_code,
                "order_type": order_type,
                "order_volume": order_volume,
                "price_type": price_type,
                "price": price,
                "strategy_name": strategy_name,
                "order_remark": order_remark,
            }
        )
        return 7788

    def query_credit_detail(self, account):
        return [
            type(
                "FakeCreditDetail",
                (),
                {
                    "m_dAvailable": 12000.0,
                    "m_dFinDebt": 9000.0,
                },
            )()
        ]


class ReloadableSettingsProvider:
    def __init__(self):
        self.loaded_once = False
        self.reload_calls = []
        self.xtquant = SimpleNamespace(
            path="",
            account="",
            account_type="STOCK",
            broker_submit_mode="normal",
            auto_repay_enabled=True,
            auto_repay_reserve_cash=5000,
        )

    def reload(self, *, strict=False):
        self.reload_calls.append(strict)
        self.loaded_once = True
        self.xtquant = SimpleNamespace(
            path="D:/mock/xtquant",
            account="068000076370",
            account_type="CREDIT",
            broker_submit_mode="normal",
            auto_repay_enabled=True,
            auto_repay_reserve_cash=5000,
        )
        return self


class FailingSettingsProvider:
    def __init__(self):
        self.xtquant = SimpleNamespace(
            path="",
            account="",
            account_type="STOCK",
        )

    def reload(self, *, strict=False):
        raise RuntimeError("settings unavailable")


def test_executor_submits_credit_direct_cash_repay():
    from freshquant.position_management.credit_client import PositionCreditClient
    from freshquant.xt_auto_repay.executor import XtAutoRepayExecutor

    trader = FakeTrader()
    client = PositionCreditClient(
        path="D:/mock/xtquant",
        account_id="068000076370",
        account_type="CREDIT",
        session_id=9527,
        trader_factory=lambda path, session_id: trader,
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
    )
    executor = XtAutoRepayExecutor(credit_client=client)

    order_id = executor.submit_direct_cash_repay(
        repay_amount=6000,
        remark="xt_auto_repay:intraday",
    )

    assert order_id == 7788
    assert trader.order_calls[0]["order_type"] == xtconstant.CREDIT_DIRECT_CASH_REPAY
    assert trader.order_calls[0]["order_volume"] == 6000
    assert trader.order_calls[0]["price_type"] == xtconstant.FIX_PRICE
    assert trader.order_calls[0]["price"] == 0.0


def test_credit_client_refreshes_settings_before_connecting():
    from freshquant.position_management.credit_client import PositionCreditClient

    trader = FakeTrader()
    settings_provider = ReloadableSettingsProvider()
    client = PositionCreditClient(
        trader_factory=lambda path, session_id: trader,
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
        system_settings_provider=settings_provider,
    )

    detail = client.query_credit_detail()

    assert settings_provider.reload_calls == [False, True]
    assert trader.connect_calls == 1
    assert client.path == "D:/mock/xtquant"
    assert client.account_id == "068000076370"
    assert len(detail) == 1


def test_credit_client_does_not_reload_global_settings_when_all_overrides_are_explicit():
    from freshquant.position_management.credit_client import PositionCreditClient

    trader = FakeTrader()
    client = PositionCreditClient(
        path="D:/mock/xtquant",
        account_id="068000076370",
        account_type="CREDIT",
        trader_factory=lambda path, session_id: trader,
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
        system_settings_provider=FailingSettingsProvider(),
    )

    detail = client.query_credit_detail()

    assert trader.connect_calls == 1
    assert len(detail) == 1


def test_credit_client_reconnects_after_retryable_query_error():
    from freshquant.position_management.credit_client import PositionCreditClient

    class FlakyQueryTrader(FakeTrader):
        def __init__(self, *, error=None, detail=None):
            super().__init__()
            self.error = error
            self.detail = detail or [
                type(
                    "FakeCreditDetail",
                    (),
                    {
                        "m_dAvailable": 12000.0,
                        "m_dFinDebt": 9000.0,
                    },
                )()
            ]

        def query_credit_detail(self, account):
            if self.error is not None:
                raise self.error
            return list(self.detail)

    first_trader = FlakyQueryTrader(error=RuntimeError("xtquant connect failed: -1"))
    second_trader = FlakyQueryTrader()
    traders = iter([first_trader, second_trader])
    client = PositionCreditClient(
        path="D:/mock/xtquant",
        account_id="068000076370",
        account_type="CREDIT",
        trader_factory=lambda path, session_id: next(traders),
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
    )

    detail = client.query_credit_detail()

    assert len(detail) == 1
    assert first_trader.connect_calls == 1
    assert first_trader.stop_calls == 1
    assert second_trader.connect_calls == 1


def test_credit_client_reconnects_after_empty_credit_detail_response():
    from freshquant.position_management.credit_client import PositionCreditClient

    class EmptyThenReadyTrader(FakeTrader):
        def __init__(self, detail):
            super().__init__()
            self.detail = detail

        def query_credit_detail(self, account):
            return self.detail

    first_trader = EmptyThenReadyTrader([])
    second_trader = EmptyThenReadyTrader(
        [
            type(
                "FakeCreditDetail",
                (),
                {
                    "m_dAvailable": 12000.0,
                    "m_dFinDebt": 9000.0,
                },
            )()
        ]
    )
    traders = iter([first_trader, second_trader])

    client = PositionCreditClient(
        path="D:/mock/xtquant",
        account_id="068000076370",
        account_type="CREDIT",
        trader_factory=lambda path, session_id: next(traders),
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
    )

    detail = client.query_credit_detail()

    assert len(detail) == 1
    assert first_trader.connect_calls == 1
    assert first_trader.stop_calls == 1
    assert second_trader.connect_calls == 1


def test_credit_client_reraises_retryable_xt_failure_after_retry_exhaustion():
    import pytest

    from freshquant.position_management.credit_client import PositionCreditClient

    class FailingQueryTrader(FakeTrader):
        def query_credit_detail(self, account):
            raise RuntimeError("xtquant connect failed: -1")

    traders = [FailingQueryTrader(), FailingQueryTrader()]
    trader_iter = iter(traders)
    client = PositionCreditClient(
        path="D:/mock/xtquant",
        account_id="068000076370",
        account_type="CREDIT",
        trader_factory=lambda path, session_id: next(trader_iter),
        account_factory=lambda account_id, account_type: type(
            "FakeAccount",
            (),
            {"account_id": account_id, "account_type": account_type},
        )(),
    )

    with pytest.raises(RuntimeError, match="xtquant connect failed: -1"):
        client.query_credit_detail()

    assert traders[0].stop_calls == 1
    assert traders[1].stop_calls == 1
