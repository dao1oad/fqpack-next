# -*- coding: utf-8 -*-

from freshquant.carnation import xtconstant


class FakeTrader:
    def __init__(self):
        self.start_calls = 0
        self.connect_calls = 0
        self.subscribe_calls = []
        self.order_calls = []

    def start(self):
        self.start_calls += 1

    def connect(self):
        self.connect_calls += 1
        return 0

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
