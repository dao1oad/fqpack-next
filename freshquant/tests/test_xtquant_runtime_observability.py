import contextlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PUPPET_PATH = (
    REPO_ROOT / "morningglory" / "fqxtrade" / "fqxtrade" / "xtquant" / "puppet.py"
)
BROKER_PATH = (
    REPO_ROOT / "morningglory" / "fqxtrade" / "fqxtrade" / "xtquant" / "broker.py"
)


class EventCollector:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))


class FakeCollection:
    def __init__(self, find_one_result=None):
        self.find_one_result = find_one_result

    def find_one(self, *args, **kwargs):
        return self.find_one_result

    def bulk_write(self, *args, **kwargs):
        return None

    def find(self, *args, **kwargs):
        return []

    def delete_many(self, *args, **kwargs):
        return None


class FakeMongoDatabase(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


class FakeTradingManager:
    def __init__(self, xt_trader=None, account=None):
        self.xt_trader = xt_trader
        self.account = account or types.SimpleNamespace(account_id="acct-1")

    @contextlib.contextmanager
    def lock(self):
        yield

    def get_connection(self):
        return self.xt_trader, self.account, True

    def update_connection(self, xt_trader, acc, success):
        self.xt_trader = xt_trader
        self.account = acc


def _wrapper_class():
    class Wrapper:
        def __init__(self, value):
            self.value = value

        def to_dict(self):
            if isinstance(self.value, dict):
                return dict(self.value)
            return dict(getattr(self.value, "__dict__", {}))

    return Wrapper


def _install_runtime_logger_stub(monkeypatch):
    module = types.ModuleType("freshquant.runtime_observability.logger")

    class RuntimeEventLogger:
        def __init__(self, component):
            self.component = component

        def emit(self, event):
            return None

    module.RuntimeEventLogger = RuntimeEventLogger
    monkeypatch.setitem(sys.modules, "freshquant.runtime_observability.logger", module)


def _install_puppet_stubs(monkeypatch, xt_trader):
    _install_runtime_logger_stub(monkeypatch)

    fqxtrade_module = types.ModuleType("fqxtrade")
    fqxtrade_module.ORDER_QUEUE = "QUEUE:ORDER"
    monkeypatch.setitem(sys.modules, "fqxtrade", fqxtrade_module)

    database_package = types.ModuleType("fqxtrade.database")
    monkeypatch.setitem(sys.modules, "fqxtrade.database", database_package)

    mongodb_module = types.ModuleType("fqxtrade.database.mongodb")
    mongodb_module.DBfreshquant = FakeMongoDatabase(
        {"stock_orders": FakeCollection(find_one_result=None)}
    )
    monkeypatch.setitem(sys.modules, "fqxtrade.database.mongodb", mongodb_module)

    redis_module = types.ModuleType("fqxtrade.database.redis")
    redis_module.redis_db = types.SimpleNamespace(lpush=lambda *args, **kwargs: 1)
    monkeypatch.setitem(sys.modules, "fqxtrade.database.redis", redis_module)

    fqtype_module = types.ModuleType("fqxtrade.xtquant.fqtype")
    for name in ("FqXtAsset", "FqXtOrder", "FqXtPosition", "FqXtTrade"):
        setattr(fqtype_module, name, _wrapper_class())
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.fqtype", fqtype_module)

    lock_module = types.ModuleType("fqxtrade.xtquant.lock")

    @contextlib.contextmanager
    def redis_distributed_lock(*args, **kwargs):
        yield True

    lock_module.redis_distributed_lock = redis_distributed_lock
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.lock", lock_module)

    trading_manager_module = types.ModuleType("fqxtrade.xtquant.trading_manager")
    trading_manager_module.TradingManager = lambda: FakeTradingManager(
        xt_trader=xt_trader
    )
    monkeypatch.setitem(
        sys.modules, "fqxtrade.xtquant.trading_manager", trading_manager_module
    )

    xtquant_package = types.ModuleType("fqxtrade.xtquant")
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant", xtquant_package)
    fqxtrade_module.xtquant = xtquant_package

    rich_console_module = types.ModuleType("rich.console")

    class Console:
        def print(self, *args, **kwargs):
            return None

    rich_console_module.Console = Console
    monkeypatch.setitem(sys.modules, "rich.console", rich_console_module)

    rich_padding_module = types.ModuleType("rich.padding")
    rich_padding_module.Padding = lambda value, *args, **kwargs: value
    monkeypatch.setitem(sys.modules, "rich.padding", rich_padding_module)

    rich_table_module = types.ModuleType("rich.table")

    class Table:
        def __init__(self, *args, **kwargs):
            self.rows = []

        def add_column(self, *args, **kwargs):
            return None

        def add_row(self, *args, **kwargs):
            self.rows.append(args)

    rich_table_module.Table = Table
    monkeypatch.setitem(sys.modules, "rich.table", rich_table_module)

    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant", xtquant_package)

    xtconstant_module = types.ModuleType("xtquant.xtconstant")
    xtconstant_module.STOCK_BUY = 23
    xtconstant_module.STOCK_SELL = 24
    xtconstant_module.CREDIT_BUY = 27
    xtconstant_module.CREDIT_FIN_BUY = 28
    xtconstant_module.CREDIT_SELL = 31
    xtconstant_module.CREDIT_SELL_SECU_REPAY = 32
    xtconstant_module.FIX_PRICE = 11
    xtdata_module = types.ModuleType("xtquant.xtdata")
    xtdata_module.get_full_tick = lambda codes: {}
    xtquant_module = types.ModuleType("xtquant")
    xtquant_module.xtconstant = xtconstant_module
    xtquant_module.xtdata = xtdata_module
    monkeypatch.setitem(sys.modules, "xtquant", xtquant_module)
    monkeypatch.setitem(sys.modules, "xtquant.xtconstant", xtconstant_module)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata_module)

    bond_module = types.ModuleType("freshquant.instrument.bond")
    bond_module.REPO_CODE_LIST = set()
    monkeypatch.setitem(sys.modules, "freshquant.instrument.bond", bond_module)

    instrument_module = types.ModuleType("freshquant.instrument.general")
    instrument_module.query_instrument_info = lambda symbol: {"name": f"Name-{symbol}"}
    monkeypatch.setitem(sys.modules, "freshquant.instrument.general", instrument_module)

    ingest_module = types.ModuleType("freshquant.order_management.ingest.xt_reports")
    ingest_module.try_ingest_xt_order_dict = lambda payload: None
    ingest_module.try_ingest_xt_trade_dict = lambda payload: None
    monkeypatch.setitem(
        sys.modules, "freshquant.order_management.ingest.xt_reports", ingest_module
    )

    reconcile_module = types.ModuleType("freshquant.order_management.reconcile.service")
    reconcile_module.ExternalOrderReconcileService = (
        lambda *args, **kwargs: types.SimpleNamespace(
            reconcile_trade_reports=lambda reports: [],
            reconcile_account=lambda *args, **kwargs: None,
        )
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.order_management.reconcile.service", reconcile_module
    )

    ordering_module = types.ModuleType("freshquant.ordering.general")
    ordering_module.query_strategy_id = lambda name: name
    monkeypatch.setitem(sys.modules, "freshquant.ordering.general", ordering_module)

    trade_module = types.ModuleType("freshquant.trade.trade")
    trade_module.calculateTradeFee = lambda price, quantity: 0.0
    trade_module.saveInstrumentStrategy = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "freshquant.trade.trade", trade_module)

    code_module = types.ModuleType("freshquant.util.code")
    code_module.fq_util_code_append_market_code_suffix = (
        lambda symbol, upper_case=True: f"{symbol}.SH"
    )
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_module)

    xtutil_module = types.ModuleType("freshquant.util.xtquant")
    xtutil_module.translate_account_type = lambda value: value
    xtutil_module.translate_order_type = lambda value: value
    monkeypatch.setitem(sys.modules, "freshquant.util.xtquant", xtutil_module)


def _install_broker_stubs(monkeypatch):
    _install_runtime_logger_stub(monkeypatch)

    puppet_module = types.ModuleType("fqxtrade.xtquant.puppet")
    puppet_module.saveOrders = lambda orders: None
    puppet_module.saveTrades = lambda trades: None
    puppet_module.saveAssets = lambda assets: None
    puppet_module.sync_positions = lambda: None
    puppet_module.sync_orders = lambda: None
    puppet_module.sync_trades = lambda: None
    puppet_module.sync_summary = lambda: None
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.puppet", puppet_module)

    fqxtrade_module = types.ModuleType("fqxtrade")
    fqxtrade_module.ORDER_QUEUE = "QUEUE:ORDER"
    monkeypatch.setitem(sys.modules, "fqxtrade", fqxtrade_module)

    xtquant_package = types.ModuleType("fqxtrade.xtquant")
    xtquant_package.puppet = puppet_module
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant", xtquant_package)
    fqxtrade_module.xtquant = xtquant_package

    redis_module = types.ModuleType("fqxtrade.database.redis")
    redis_module.redis_db = types.SimpleNamespace(brpop=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "fqxtrade.database.redis", redis_module)

    trade_date_module = types.ModuleType("fqxtrade.util.trade_date_hist")
    trade_date_module.tool_trade_date_seconds_to_start = lambda: 1
    monkeypatch.setitem(sys.modules, "fqxtrade.util.trade_date_hist", trade_date_module)

    account_module = types.ModuleType("fqxtrade.xtquant.account")
    account_module.resolve_stock_account = lambda query_param: (
        types.SimpleNamespace(account_id="acct-1"),
        "acct-1",
        "STOCK",
    )
    account_module.resolve_broker_submit_mode = lambda query_param=None: "normal"
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.account", account_module)

    class FakeConnectionManager:
        def __init__(self):
            self.connected = False
            self.retry_count = 0
            self.max_retries = 3

        def mark_disconnected(self):
            self.connected = False

        def mark_connected(self):
            self.connected = True

        def get_retry_delay(self):
            return 1

        def can_retry(self):
            return True

        def reset_retry_count(self):
            self.retry_count = 0

    connection_manager_module = types.ModuleType("fqxtrade.xtquant.connection_manager")
    connection_manager_module.ConnectionManager = FakeConnectionManager
    monkeypatch.setitem(
        sys.modules,
        "fqxtrade.xtquant.connection_manager",
        connection_manager_module,
    )

    fqtype_module = types.ModuleType("fqxtrade.xtquant.fqtype")
    for name in (
        "FqXtAccountStatus",
        "FqXtAsset",
        "FqXtCancelError",
        "FqXtCancelOrderResponse",
        "FqXtOrder",
        "FqXtOrderError",
        "FqXtOrderResponse",
        "FqXtPosition",
        "FqXtSmtAppointmentResponse",
        "FqXtTrade",
    ):
        setattr(fqtype_module, name, _wrapper_class())
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.fqtype", fqtype_module)

    handlers_module = types.ModuleType("fqxtrade.xtquant.handlers")
    handlers_module.handlers = []
    monkeypatch.setitem(sys.modules, "fqxtrade.xtquant.handlers", handlers_module)

    trading_manager_module = types.ModuleType("fqxtrade.xtquant.trading_manager")
    trading_manager_module.TradingManager = lambda: FakeTradingManager()
    monkeypatch.setitem(
        sys.modules, "fqxtrade.xtquant.trading_manager", trading_manager_module
    )

    xttrader_module = types.ModuleType("xtquant.xttrader")

    class XtQuantTrader:
        def __init__(self, *args, **kwargs):
            return None

    class XtQuantTraderCallback:
        pass

    xttrader_module.XtQuantTrader = XtQuantTrader
    xttrader_module.XtQuantTraderCallback = XtQuantTraderCallback
    monkeypatch.setitem(sys.modules, "xtquant.xttrader", xttrader_module)

    tornado_package = types.ModuleType("tornado")
    tornado_web_module = types.ModuleType("tornado.web")
    tornado_web_module.Application = lambda *args, **kwargs: types.SimpleNamespace(
        listen=lambda port: None
    )
    tornado_ioloop_module = types.ModuleType("tornado.ioloop")
    tornado_ioloop_module.IOLoop = types.SimpleNamespace(
        current=lambda: types.SimpleNamespace(start=lambda: None)
    )
    tornado_package.web = tornado_web_module
    tornado_package.ioloop = tornado_ioloop_module
    monkeypatch.setitem(sys.modules, "tornado", tornado_package)
    monkeypatch.setitem(sys.modules, "tornado.web", tornado_web_module)
    monkeypatch.setitem(sys.modules, "tornado.ioloop", tornado_ioloop_module)

    query_param_module = types.ModuleType("freshquant.carnation.param")
    query_param_module.queryParam = lambda key, default=None: default
    monkeypatch.setitem(sys.modules, "freshquant.carnation.param", query_param_module)

    repository_module = types.ModuleType("freshquant.order_management.repository")

    class OrderManagementRepository:
        def find_order_by_broker_order_id(self, broker_order_id):
            return None

    repository_module.OrderManagementRepository = OrderManagementRepository
    monkeypatch.setitem(
        sys.modules, "freshquant.order_management.repository", repository_module
    )

    execution_bridge_module = types.ModuleType(
        "freshquant.order_management.submit.execution_bridge"
    )
    execution_bridge_module.dispatch_cancel_execution = lambda *args, **kwargs: {
        "status": "cancel_submitted"
    }
    execution_bridge_module.finalize_submit_execution = lambda *args, **kwargs: None
    execution_bridge_module.prepare_submit_execution = lambda order, **kwargs: {
        "status": "ready",
        "order_message": order,
    }
    execution_bridge_module.resolve_sell_price_type_compat = lambda order: 11
    monkeypatch.setitem(
        sys.modules,
        "freshquant.order_management.submit.execution_bridge",
        execution_bridge_module,
    )

    tracking_module = types.ModuleType("freshquant.order_management.tracking.service")
    tracking_module.OrderTrackingService = (
        lambda repository=None: types.SimpleNamespace()
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.order_management.tracking.service", tracking_module
    )

    trade_module = types.ModuleType("freshquant.trade.trade")
    trade_module.checkManualStrategyInstument = lambda stock_code: False
    monkeypatch.setitem(sys.modules, "freshquant.trade.trade", trade_module)

    code_module = types.ModuleType("freshquant.util.code")
    code_module.fq_util_code_append_market_code_suffix = (
        lambda symbol, upper_case=True: f"{symbol}.SH"
    )
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_module)


def _load_module(module_name, module_path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_puppet_buy_emits_runtime_trace_context(monkeypatch):
    class FakeTrader:
        def query_stock_asset(self, acc):
            return types.SimpleNamespace(cash=100000.0, frozen_cash=0.0)

        def order_stock(self, *args, **kwargs):
            return 123456

    _install_puppet_stubs(monkeypatch, xt_trader=FakeTrader())
    puppet = _load_module("test_runtime_puppet", PUPPET_PATH)
    collector = EventCollector()
    puppet._runtime_logger = collector

    broker_order_id = puppet.buy(
        "600000",
        10.0,
        300,
        trace_id="trace-puppet-1",
        intent_id="intent-puppet-1",
        request_id="req-puppet-1",
        internal_order_id="ord-puppet-1",
    )

    assert broker_order_id == 123456
    assert [item["node"] for item in collector.events] == [
        "submit_prepare",
        "submit_decision",
        "submit_result",
    ]
    for event in collector.events:
        assert event["trace_id"] == "trace-puppet-1"
        assert event["intent_id"] == "intent-puppet-1"
        assert event["request_id"] == "req-puppet-1"
        assert event["internal_order_id"] == "ord-puppet-1"
        assert event["symbol"] == "600000"
        assert event["action"] == "buy"


def test_puppet_buy_emits_runtime_error_when_order_submit_raises(monkeypatch):
    class FakeTrader:
        def query_stock_asset(self, acc):
            return types.SimpleNamespace(cash=100000.0, frozen_cash=0.0)

        def order_stock(self, *args, **kwargs):
            raise RuntimeError("xt submit failed")

    _install_puppet_stubs(monkeypatch, xt_trader=FakeTrader())
    puppet = _load_module("test_runtime_puppet_error", PUPPET_PATH)
    collector = EventCollector()
    puppet._runtime_logger = collector

    with pytest.raises(RuntimeError, match="xt submit failed"):
        puppet.buy(
            "600000",
            10.0,
            300,
            trace_id="trace-puppet-error-1",
            intent_id="intent-puppet-error-1",
            request_id="req-puppet-error-1",
            internal_order_id="ord-puppet-error-1",
        )

    assert collector.events[-1]["node"] == "submit_result"
    assert collector.events[-1]["status"] == "error"
    assert collector.events[-1]["payload"]["error_type"] == "RuntimeError"
    assert collector.events[-1]["payload"]["error_message"] == "xt submit failed"


def test_puppet_buy_keeps_duplicate_check_and_submit_inside_trading_lock(
    monkeypatch,
):
    _install_puppet_stubs(monkeypatch, xt_trader=types.SimpleNamespace())
    puppet = _load_module("test_runtime_puppet_buy_lock", PUPPET_PATH)

    class LockTrackingManager:
        def __init__(self):
            self.account = types.SimpleNamespace(account_id="acct-1")
            self.lock_active = False

        @contextlib.contextmanager
        def lock(self):
            self.lock_active = True
            try:
                yield
            finally:
                self.lock_active = False

        def get_connection(self):
            return self.xt_trader, self.account, True

    manager = LockTrackingManager()

    class GuardedCollection(FakeCollection):
        def find_one(self, *args, **kwargs):
            assert manager.lock_active
            return None

    class GuardedTrader:
        def query_stock_asset(self, acc):
            assert manager.lock_active
            return types.SimpleNamespace(cash=100000.0, frozen_cash=0.0)

        def order_stock(self, *args, **kwargs):
            assert manager.lock_active
            return 123456

    manager.xt_trader = GuardedTrader()
    puppet.trading_manager = manager
    puppet.DBfreshquant["stock_orders"] = GuardedCollection()

    assert puppet.buy("600000", 10.0, 300) == 123456


def test_puppet_sell_keeps_duplicate_check_and_submit_inside_trading_lock(
    monkeypatch,
):
    _install_puppet_stubs(monkeypatch, xt_trader=types.SimpleNamespace())
    puppet = _load_module("test_runtime_puppet_sell_lock", PUPPET_PATH)

    class LockTrackingManager:
        def __init__(self):
            self.account = types.SimpleNamespace(account_id="acct-1")
            self.lock_active = False

        @contextlib.contextmanager
        def lock(self):
            self.lock_active = True
            try:
                yield
            finally:
                self.lock_active = False

        def get_connection(self):
            return self.xt_trader, self.account, True

    manager = LockTrackingManager()

    class GuardedCollection(FakeCollection):
        def find_one(self, *args, **kwargs):
            assert manager.lock_active
            return None

    class GuardedTrader:
        def query_stock_positions(self, acc):
            assert manager.lock_active
            return [types.SimpleNamespace(stock_code="600000.SH", can_use_volume=500)]

        def order_stock(self, *args, **kwargs):
            assert manager.lock_active
            return 654321

    manager.xt_trader = GuardedTrader()
    puppet.trading_manager = manager
    puppet.DBfreshquant["stock_orders"] = GuardedCollection()

    assert puppet.sell("600000", 11, 10.0, 300) == 654321


def test_broker_trade_callback_emits_resolved_runtime_context(monkeypatch):
    _install_broker_stubs(monkeypatch)
    broker = _load_module("test_runtime_broker", BROKER_PATH)
    collector = EventCollector()
    broker._runtime_logger = collector
    broker.order_management_repository = types.SimpleNamespace(
        find_order_by_broker_order_id=lambda broker_order_id: {
            "trace_id": "trace-broker-1",
            "intent_id": "intent-broker-1",
            "request_id": "req-broker-1",
            "internal_order_id": "ord-broker-1",
            "symbol": "600000",
            "side": "buy",
        }
    )

    callback = broker.MyXtQuantTraderCallback()
    callback.on_stock_trade(
        types.SimpleNamespace(
            order_id="90001",
            traded_id="T-90001",
            stock_code="600000.SH",
        )
    )

    assert collector.events[0]["node"] == "trade_callback"
    assert collector.events[0]["trace_id"] == "trace-broker-1"
    assert collector.events[0]["intent_id"] == "intent-broker-1"
    assert collector.events[0]["request_id"] == "req-broker-1"
    assert collector.events[0]["internal_order_id"] == "ord-broker-1"
    assert collector.events[0]["symbol"] == "600000"
    assert collector.events[0]["action"] == "buy"
    assert collector.events[0]["payload"]["broker_order_id"] == "90001"
    assert collector.events[0]["payload"]["broker_trade_id"] == "T-90001"


def test_broker_observe_only_submit_emits_bypass_event_without_calling_executor(
    monkeypatch,
):
    _install_broker_stubs(monkeypatch)
    broker = _load_module("test_runtime_broker_observe_only", BROKER_PATH)
    collector = EventCollector()
    broker._runtime_logger = collector

    observed = {}
    broker.prepare_submit_execution = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("prepare_submit_execution should not run in observe_only")
    )
    broker.finalize_submit_execution = lambda *args, **kwargs: observed.update(
        {
            "broker_submit_mode": kwargs.get("broker_submit_mode"),
            "broker_order_id": kwargs.get("broker_order_id"),
        }
    ) or {"status": "broker_bypassed"}

    def fail_submit_executor(resolved_order):
        raise AssertionError("submit executor should not be called in observe_only")

    result = broker._handle_submit_action(
        {
            "action": "buy",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "internal_order_id": "ord-observe-1",
            "request_id": "req-observe-1",
            "trace_id": "trace-observe-1",
            "intent_id": "intent-observe-1",
        },
        action="buy",
        submit_executor=fail_submit_executor,
        broker_submit_mode="observe_only",
    )

    assert result["status"] == "broker_bypassed"
    assert observed == {
        "broker_submit_mode": "observe_only",
        "broker_order_id": None,
    }
    assert collector.events[-1]["node"] == "execution_bypassed"
    assert collector.events[-1]["action"] == "buy"
    assert collector.events[-1]["payload"]["reason"] == "observe_only"


def test_broker_submit_emits_runtime_error_when_executor_raises(monkeypatch):
    _install_broker_stubs(monkeypatch)
    broker = _load_module("test_runtime_broker_submit_error", BROKER_PATH)
    collector = EventCollector()
    broker._runtime_logger = collector

    with pytest.raises(RuntimeError, match="broker submit failed"):
        broker._handle_submit_action(
            {
                "action": "buy",
                "symbol": "600000",
                "price": 10.0,
                "quantity": 100,
                "internal_order_id": "ord-broker-error-1",
                "request_id": "req-broker-error-1",
                "trace_id": "trace-broker-error-1",
                "intent_id": "intent-broker-error-1",
            },
            action="buy",
            submit_executor=lambda _resolved_order: (_ for _ in ()).throw(
                RuntimeError("broker submit failed")
            ),
            broker_submit_mode="normal",
        )

    assert collector.events[-1]["node"] == "submit_result"
    assert collector.events[-1]["status"] == "error"
    assert collector.events[-1]["payload"]["error_type"] == "RuntimeError"
    assert collector.events[-1]["payload"]["error_message"] == "broker submit failed"


def test_broker_observe_only_helper_is_defined_before_script_entrypoint():
    broker_source = BROKER_PATH.read_text(encoding="utf-8")

    helper_index = broker_source.index("def _is_observe_only_mode")
    entrypoint_index = broker_source.index('if __name__ == "__main__":')

    assert helper_index < entrypoint_index
