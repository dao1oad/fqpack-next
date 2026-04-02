import importlib
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "morningglory" / "fqxtrade"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


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


def _install_buy_test_doubles(monkeypatch, puppet_module, trader):
    monkeypatch.setattr(puppet_module, "trading_manager", _FakeTradingManager(trader))
    monkeypatch.setattr(
        puppet_module,
        "DBfreshquant",
        {"stock_orders": _FakeStockOrdersCollection()},
    )
    monkeypatch.setattr(puppet_module, "calculateTradeFee", lambda price, quantity: 0.0)
    monkeypatch.setattr(
        puppet_module,
        "fq_util_code_append_market_code_suffix",
        lambda symbol, upper_case=True: f"{symbol}.SH",
    )
    events = []
    monkeypatch.setattr(
        puppet_module,
        "_emit_puppet_event",
        lambda node, **kwargs: events.append({"node": node, **kwargs}),
    )
    return events


def _load_puppet_module(monkeypatch):
    xtconstant_module = ModuleType("xtquant.xtconstant")
    xtconstant_module.SECURITY_ACCOUNT = 2
    xtconstant_module.STOCK_BUY = 23
    xtconstant_module.STOCK_SELL = 24
    xtconstant_module.CREDIT_BUY = 27
    xtconstant_module.CREDIT_FIN_BUY = 28
    xtconstant_module.CREDIT_SELL = 31
    xtconstant_module.CREDIT_SELL_SECU_REPAY = 32
    xtconstant_module.FIX_PRICE = 11

    xtdata_module = ModuleType("xtquant.xtdata")
    xtdata_module.get_full_tick = lambda _codes: {}

    xttype_module = ModuleType("xtquant.xttype")
    for name in (
        "XtAccountStatus",
        "XtAsset",
        "XtCancelError",
        "XtCancelOrderResponse",
        "XtOrder",
        "XtOrderError",
        "XtOrderResponse",
        "XtPosition",
        "XtSmtAppointmentResponse",
        "XtTrade",
    ):
        setattr(xttype_module, name, type(name, (), {}))

    xtquant_module = ModuleType("xtquant")
    xtquant_module.__path__ = []
    xtquant_module.xtconstant = xtconstant_module
    xtquant_module.xtdata = xtdata_module
    xtquant_module.xttype = xttype_module

    monkeypatch.setitem(sys.modules, "xtquant", xtquant_module)
    monkeypatch.setitem(sys.modules, "xtquant.xtconstant", xtconstant_module)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata_module)
    monkeypatch.setitem(sys.modules, "xtquant.xttype", xttype_module)
    monkeypatch.delitem(sys.modules, "fqxtrade.xtquant.puppet", raising=False)

    puppet_module = importlib.import_module("fqxtrade.xtquant.puppet")
    return puppet_module, xtconstant_module


def test_credit_fin_buy_skips_cash_balance_precheck(monkeypatch):
    puppet, xtconstant = _load_puppet_module(monkeypatch)
    trader = _FakeTrader(cash=305.7)
    events = _install_buy_test_doubles(monkeypatch, puppet, trader)

    result = puppet.buy(
        "513180",
        0.613872,
        82100,
        "guardian",
        "V反上涨",
        order_type=xtconstant.CREDIT_FIN_BUY,
        available_bail_balance=60000.0,
        available_amount=1000.0,
    )

    assert result == 123456
    assert trader.order_calls
    assert trader.order_calls[0]["order_type"] == xtconstant.CREDIT_FIN_BUY
    assert not any(
        event.get("payload", {}).get("reason") == "insufficient_cash"
        for event in events
    )


def test_credit_fin_buy_blocks_when_bail_balance_is_insufficient(monkeypatch):
    puppet, xtconstant = _load_puppet_module(monkeypatch)
    trader = _FakeTrader(cash=100000.0)
    events = _install_buy_test_doubles(monkeypatch, puppet, trader)

    result = puppet.buy(
        "513180",
        0.613872,
        82100,
        "guardian",
        "V反上涨",
        order_type=xtconstant.CREDIT_FIN_BUY,
        available_bail_balance=1000.0,
        available_amount=999999.0,
    )

    assert result is None
    assert trader.order_calls == []
    assert any(
        event.get("payload", {}).get("reason") == "insufficient_bail_balance"
        for event in events
    )


def test_stock_buy_still_blocks_when_cash_is_insufficient(monkeypatch):
    puppet, xtconstant = _load_puppet_module(monkeypatch)
    trader = _FakeTrader(cash=305.7)
    events = _install_buy_test_doubles(monkeypatch, puppet, trader)

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
