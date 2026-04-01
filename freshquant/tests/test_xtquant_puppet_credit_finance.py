import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "morningglory" / "fqxtrade"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from fqxtrade.xtquant import puppet
from xtquant import xtconstant


class _FakeStockOrdersCollection:
    def find_one(self, _query):
        return None


class _FakeTrader:
    def __init__(self, *, cash, frozen_cash=0.0, order_result=123456):
        self.asset = SimpleNamespace(cash=cash, frozen_cash=frozen_cash)
        self.order_result = order_result
        self.order_calls = []

    def query_stock_asset(self, _account):
        return self.asset

    def order_stock(
        self,
        account,
        stock_code,
        order_type,
        quantity,
        price_type,
        price,
        strategy_name,
        order_remark,
    ):
        self.order_calls.append(
            {
                "account": account,
                "stock_code": stock_code,
                "order_type": order_type,
                "quantity": quantity,
                "price_type": price_type,
                "price": price,
                "strategy_name": strategy_name,
                "order_remark": order_remark,
            }
        )
        return self.order_result


class _FakeTradingManager:
    def __init__(self, trader):
        self.trader = trader

    def lock(self):
        return nullcontext()

    def get_connection(self):
        return self.trader, object(), None


def _install_buy_test_doubles(monkeypatch, trader):
    monkeypatch.setattr(puppet, "trading_manager", _FakeTradingManager(trader))
    monkeypatch.setattr(
        puppet,
        "DBfreshquant",
        {"stock_orders": _FakeStockOrdersCollection()},
    )
    monkeypatch.setattr(puppet, "calculateTradeFee", lambda price, quantity: 0.0)
    monkeypatch.setattr(
        puppet,
        "fq_util_code_append_market_code_suffix",
        lambda symbol, upper_case=True: f"{symbol}.SH",
    )
    events = []
    monkeypatch.setattr(
        puppet,
        "_emit_puppet_event",
        lambda node, **kwargs: events.append({"node": node, **kwargs}),
    )
    return events


def test_credit_fin_buy_skips_cash_balance_precheck(monkeypatch):
    trader = _FakeTrader(cash=305.7)
    events = _install_buy_test_doubles(monkeypatch, trader)

    result = puppet.buy(
        "513180",
        0.613872,
        82100,
        "guardian",
        "V反上涨",
        order_type=xtconstant.CREDIT_FIN_BUY,
    )

    assert result == 123456
    assert trader.order_calls
    assert trader.order_calls[0]["order_type"] == xtconstant.CREDIT_FIN_BUY
    assert not any(
        event.get("payload", {}).get("reason") == "insufficient_cash"
        for event in events
    )


def test_stock_buy_still_blocks_when_cash_is_insufficient(monkeypatch):
    trader = _FakeTrader(cash=305.7)
    events = _install_buy_test_doubles(monkeypatch, trader)

    result = puppet.buy(
        "513180",
        0.613872,
        82100,
        "guardian",
        "V反上涨",
        order_type=xtconstant.STOCK_BUY,
    )

    assert result is None
    assert trader.order_calls == []
    assert any(
        event.get("payload", {}).get("reason") == "insufficient_cash"
        for event in events
    )
