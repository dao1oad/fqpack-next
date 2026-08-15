from __future__ import annotations

import importlib
import sys
import types

import pendulum
import pytest

from freshquant.position_management.errors import PositionManagementRejectedError


def _module(name: str, **attrs: object) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr_name, value in attrs.items():
        setattr(module, attr_name, value)
    return module


sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))
sys.modules.setdefault(
    "arrow",
    _module(
        "arrow",
        get=lambda dt: types.SimpleNamespace(
            floor=lambda _unit: types.SimpleNamespace(datetime=dt)
        ),
    ),
)
sys.modules.setdefault(
    "tzlocal",
    _module("tzlocal", get_localzone=lambda: pendulum.local_timezone()),
)
sys.modules.setdefault(
    "redis",
    _module(
        "redis",
        ConnectionPool=lambda **_kwargs: object(),
        Redis=lambda **_kwargs: types.SimpleNamespace(
            get=lambda *_args, **_kwargs: None,
            set=lambda *_args, **_kwargs: True,
        ),
        StrictRedis=lambda **_kwargs: types.SimpleNamespace(
            get=lambda *_args, **_kwargs: None,
            set=lambda *_args, **_kwargs: True,
        ),
    ),
)


def _install_guardian_dependency_stubs() -> None:
    """强制替换 guardian 依赖模块为 stub。

    用赋值而非 setdefault：同进程内若这些模块已被其他测试真实导入（shard
    组合变化即可触发），setdefault 不生效，guardian 会绑定真实函数并访问
    真实 Mongo（CI 无 Mongo 时 30s 超时失败）。替换后需 reload guardian
    让模块级绑定刷新。
    """
    sys.modules["freshquant.strategy.toolkit.threshold"] = _module(
        "freshquant.strategy.toolkit.threshold",
        eval_stock_threshold_price=lambda _code, _price: {
            "bot_river_price": 0.0,
            "top_river_price": 0.0,
        },
    )
    sys.modules["freshquant.data.astock.holding"] = _module(
        "freshquant.data.astock.holding",
        _query_grid_interval=lambda _code, _date_str: 1.03,
        get_arranged_stock_fill_list=lambda _code: [],
        get_stock_holding_codes=lambda: [],
    )
    sys.modules["freshquant.pool.general"] = _module(
        "freshquant.pool.general", queryMustPoolCodes=lambda: []
    )
    sys.modules["freshquant.position.stock"] = _module(
        "freshquant.position.stock",
        query_stock_position_pct=lambda *_args, **_kwargs: 0,
    )


guardian_module = None
StrategyGuardian = None

_STUBBED_DEPENDENCY_MODULES = (
    "freshquant.strategy.toolkit.threshold",
    "freshquant.data.astock.holding",
    "freshquant.pool.general",
    "freshquant.position.stock",
)


@pytest.fixture(scope="module", autouse=True)
def _guardian_dependency_stubs_for_module():
    """本文件测试期间强制替换 guardian 依赖为 stub，文件结束后恢复原模块。

    安装必须在首个测试前完成（guardian 的模块级绑定需 reload 刷新），恢复
    必须在本文件全部测试结束后进行——此前在模块导入期安装且从不恢复，
    污染同一进程内后续测试文件（xdist loadfile 分布下跨文件可见）。
    """
    global guardian_module, StrategyGuardian

    originals = {name: sys.modules.get(name) for name in _STUBBED_DEPENDENCY_MODULES}
    _install_guardian_dependency_stubs()
    import freshquant.strategy.guardian as module

    module = importlib.reload(module)
    guardian_module = module
    StrategyGuardian = module.StrategyGuardian
    sys.modules.pop("freshquant.message", None)
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        try:
            importlib.reload(guardian_module)
        except Exception:
            pass
        guardian_module = None
        StrategyGuardian = None


class FailDb:
    def __getitem__(self, name):
        raise AssertionError(f"unexpected DB access: {name}")


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.events = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl):
        self.events.append(("set", key, value, ttl))
        self.data[key] = value


class FakeOrderAlert:
    def __init__(self):
        self.calls = []

    def send(self, sender, **kwargs):
        self.calls.append((sender, kwargs))


class FakeGuardianBuyGridService:
    def __init__(self, *, holding_decision=None, new_open_decision=None):
        self.calls = []
        self.holding_decision = holding_decision or {}
        self.new_open_decision = new_open_decision or {}

    def build_holding_add_decision(self, code, price):
        self.calls.append(("holding_add", code, price))
        return dict(self.holding_decision)

    def build_new_open_decision(self, code, price):
        self.calls.append(("new_open", code, price))
        return dict(self.new_open_decision)


@pytest.fixture(autouse=True)
def _stub_empty_order_management_repository(monkeypatch):
    class EmptyRepository:
        def list_broker_orders(self, **_kwargs):
            return []

    monkeypatch.setattr(
        guardian_module,
        "_get_order_management_repository",
        lambda: EmptyRepository(),
    )


def _prepare_guardian_buy_orders(monkeypatch, orders):
    queries = []
    cancel_calls = []

    class FakeRepository:
        def list_broker_orders(self, **kwargs):
            queries.append(kwargs)
            return list(orders)

    class FakeSubmitService:
        def cancel_order(self, payload):
            cancel_calls.append(payload)

    monkeypatch.setattr(
        guardian_module,
        "_get_order_management_repository",
        lambda: FakeRepository(),
    )
    monkeypatch.setattr(
        "freshquant.order_management.submit.service.OrderSubmitService",
        FakeSubmitService,
    )
    result = guardian_module._prepare_guardian_buy_orders("000001")
    return result, queries, cancel_calls


def test_prepare_guardian_buy_orders_allows_when_no_active_buy(monkeypatch):
    result, queries, cancel_calls = _prepare_guardian_buy_orders(monkeypatch, [])

    assert result == {
        "blocked": False,
        "reason_code": None,
        "count": 0,
        "canceled": 0,
        "waiting": 0,
        "unmapped": 0,
    }
    assert queries[0]["symbol"] == "000001"
    assert cancel_calls == []


@pytest.mark.parametrize("state", ["SUBMITTED", "PARTIAL_FILLED"])
def test_prepare_guardian_buy_orders_cancels_internal_active_buy(monkeypatch, state):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": state,
                "side": "buy",
                "internal_order_id": "ord_buy_1",
                "broker_order_id": "broker_buy_1",
                "source_type": "guardian",
            }
        ],
    )

    assert result == {
        "blocked": True,
        "reason_code": "active_buy_orders_cancel_requested",
        "count": 1,
        "canceled": 1,
        "waiting": 0,
        "unmapped": 0,
    }
    assert cancel_calls == [
        {
            "internal_order_id": "ord_buy_1",
            "source": "guardian_replace_buy",
            "strategy_name": "Guardian",
            "remark": "cancel active buy before recalculation",
        }
    ]


@pytest.mark.parametrize("state", ["CANCEL_REQUESTED", "INFERRED_PENDING"])
def test_prepare_guardian_buy_orders_waits_without_repeated_cancel(monkeypatch, state):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": state,
                "side": "buy",
                "internal_order_id": "ord_buy_1",
                "broker_order_id": "broker_buy_1",
                "source_type": "guardian",
            }
        ],
    )

    assert result["blocked"] is True
    assert result["reason_code"] == "active_buy_orders_waiting"
    assert result["canceled"] == 0
    assert result["waiting"] == 1
    assert result["unmapped"] == 0
    assert cancel_calls == []


@pytest.mark.parametrize("source_type", ["external_reported", "external_inferred"])
def test_prepare_guardian_buy_orders_waits_for_external_buy(monkeypatch, source_type):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": "SUBMITTED",
                "side": "buy",
                "internal_order_id": "ord_external_1",
                "broker_order_id": "broker_external_1",
                "source_type": source_type,
            }
        ],
    )

    assert result["blocked"] is True
    assert result["reason_code"] == "active_buy_orders_waiting"
    assert result["canceled"] == 0
    assert result["waiting"] == 1
    assert result["unmapped"] == 0
    assert cancel_calls == []


@pytest.mark.parametrize(
    ("broker_order_id", "expected_canceled", "expected_waiting"),
    [(None, 0, 1), ("broker_bypass_1", 1, 0)],
)
def test_prepare_guardian_buy_orders_classifies_broker_bypassed_buy(
    monkeypatch,
    broker_order_id,
    expected_canceled,
    expected_waiting,
):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": "BROKER_BYPASSED",
                "side": "buy",
                "internal_order_id": "ord_bypass_1",
                "broker_order_id": broker_order_id,
                "source_type": "guardian",
            }
        ],
    )

    assert result["blocked"] is True
    assert result["canceled"] == expected_canceled
    assert result["waiting"] == expected_waiting
    assert result["unmapped"] == 0
    assert len(cancel_calls) == expected_canceled


def test_prepare_guardian_buy_orders_ignores_sell_orders(monkeypatch):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": "SUBMITTED",
                "side": "sell",
                "internal_order_id": "ord_sell_1",
                "broker_order_id": "broker_sell_1",
                "source_type": "guardian",
            }
        ],
    )

    assert result["blocked"] is False
    assert result["count"] == 0
    assert cancel_calls == []


def test_prepare_guardian_buy_orders_blocks_unmapped_active_buy(monkeypatch):
    result, _queries, cancel_calls = _prepare_guardian_buy_orders(
        monkeypatch,
        [
            {
                "state": "SUBMITTED",
                "side": "buy",
                "broker_order_id": "broker_unmapped_1",
                "source_type": "guardian",
            }
        ],
    )

    assert result == {
        "blocked": True,
        "reason_code": "active_buy_orders_waiting",
        "count": 1,
        "canceled": 0,
        "waiting": 1,
        "unmapped": 1,
    }
    assert cancel_calls == []


def _make_fill_reference(fire_time, *, price=10.0, source="execution_fill"):
    localized_fill_time = pendulum.from_format(
        fire_time.format("YYYY-MM-DD HH:mm:ss"),
        "YYYY-MM-DD HH:mm:ss",
        tz="Asia/Shanghai",
    )
    return {
        "fill_time": localized_fill_time,
        "fill_price": price,
        "fill_reference_source": source,
    }


def _make_signal(
    *, code="000001", position="BUY_LONG", price=7.8, remark="test-remark"
):
    now = pendulum.now()
    return {
        "symbol": code,
        "code": code,
        "name": "Ping An Bank",
        "period": "1m",
        "fire_time": now,
        "discover_time": now,
        "price": price,
        "stop_lose_price": 7.0,
        "position": position,
        "remark": remark,
        "tags": [],
        "zsdata": None,
        "fills": None,
    }


def test_holding_buy_uses_guardian_buy_grid_and_sets_cooldown_after_submit(
    monkeypatch,
):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        holding_decision={
            "path": "holding_add",
            "quantity": 25600,
            "grid_level": "BUY-3",
            "hit_levels": ["BUY-1", "BUY-2", "BUY-3"],
            "multiplier": 4,
            "source_price": 7.8,
            "buy_prices_snapshot": {"BUY-1": 10.0, "BUY-2": 9.0, "BUY-3": 8.0},
            "buy_active_before": [True, True, True],
        }
    )
    signal = _make_signal()
    fire_time = signal["fire_time"]
    events = []

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time, price=10.0),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 8.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.query_stock_position_pct",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("position_pct should not be used for buy sizing")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_auto_open",
        lambda: (_ for _ in ()).throw(
            AssertionError("auto_open should not be used for must-pool opening")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_position_pct",
        lambda: (_ for _ in ()).throw(
            AssertionError("position_pct gate should not be used for new open")
        ),
        raising=False,
    )

    def fake_submit(
        action,
        symbol,
        price,
        quantity,
        remark=None,
        strategy_context=None,
        ledger_intent=None,
        is_profitable=None,
        trace_id=None,
        intent_id=None,
    ):
        events.append("submit")
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
                "ledger_intent": ledger_intent,
                "trace_id": trace_id,
                "intent_id": intent_id,
                "is_profitable": is_profitable,
            }
        )
        return {
            "request_id": "req_1",
            "internal_order_id": "ord_1",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert decision_service.calls == [("holding_add", "000001", 7.8)]
    assert captured["action"] == "buy"
    assert captured["quantity"] == 25600
    assert captured["remark"] == "test-remark"
    assert captured["strategy_context"]["guardian_buy_grid"]["grid_level"] == "BUY-3"
    assert captured["strategy_context"]["guardian_buy_grid"]["path"] == "holding_add"
    assert captured["ledger_intent"] == "t"
    assert (
        captured["strategy_context"]["guardian_buy_grid"]["signal_time"]
        == fire_time.isoformat()
    )
    assert signal["quantity"] == 25600
    assert events == ["submit"]
    assert len(fake_redis.events) == 1
    assert fake_redis.events[0][1] == "buy:000001"


def test_holding_buy_prefers_latest_execution_fill_over_arranged_fill(monkeypatch):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        holding_decision={
            "path": "holding_add",
            "quantity": 300,
            "grid_level": "BUY-1",
            "hit_levels": ["BUY-1"],
            "multiplier": 2,
            "source_price": 9.8,
            "buy_prices_snapshot": {"BUY-1": 10.0},
            "buy_active_before": [True],
        }
    )
    signal = _make_signal(price=9.8)
    fire_time = signal["fire_time"]
    threshold_prices = []

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_order_management_repository",
        lambda: types.SimpleNamespace(
            list_execution_fills=lambda symbol=None: [
                {
                    "trade_time": int(fire_time.subtract(minutes=1).timestamp()),
                    "price": 10.0,
                    "execution_fill_id": "fill_1",
                    "broker_trade_id": "trade_1",
                    "created_at": "2026-03-09T09:59:00+08:00",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 30.0,
                "quantity": 100,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, threshold_price: (
            threshold_prices.append(threshold_price)
            or {
                "bot_river_price": 9.8 if threshold_price == 10.0 else 29.4,
                "top_river_price": 12.0,
            }
        ),
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    def fake_submit(
        action,
        symbol,
        price,
        quantity,
        remark=None,
        strategy_context=None,
        ledger_intent=None,
        is_profitable=None,
        trace_id=None,
        intent_id=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
                "ledger_intent": ledger_intent,
                "trace_id": trace_id,
                "intent_id": intent_id,
                "is_profitable": is_profitable,
            }
        )
        return {
            "request_id": "req_exec_1",
            "internal_order_id": "ord_exec_1",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert threshold_prices == [10.0]
    assert captured["action"] == "buy"
    assert captured["quantity"] == 300
    assert captured["ledger_intent"] == "t"
    assert fake_redis.events[0][1] == "buy:000001"


def test_holding_buy_uses_latest_execution_fill_as_threshold_base(monkeypatch):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        holding_decision={
            "path": "holding_add",
            "quantity": 300,
            "grid_level": "BUY-1",
            "hit_levels": ["BUY-1"],
            "multiplier": 2,
            "source_price": 10.0,
            "buy_prices_snapshot": {"BUY-1": 10.3},
            "buy_active_before": [True],
        }
    )
    signal = _make_signal(price=10.0)
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time.subtract(minutes=3), price=10.8),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 12.0,
                "quantity": 100,
            },
            {
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 10.3,
                "quantity": 100,
            },
        ],
    )
    threshold_prices = []
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, price: threshold_prices.append(price)
        or {"bot_river_price": 11.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    def fake_submit(
        action,
        symbol,
        price,
        quantity,
        remark=None,
        strategy_context=None,
        ledger_intent=None,
        is_profitable=None,
        trace_id=None,
        intent_id=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
                "ledger_intent": ledger_intent,
                "trace_id": trace_id,
                "intent_id": intent_id,
                "is_profitable": is_profitable,
            }
        )
        return {
            "request_id": "req_slice_stale_1",
            "internal_order_id": "ord_slice_stale_1",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert captured["action"] == "buy"
    assert captured["quantity"] == 300
    # #549：最近 execution fill（10.8）是做T买入门槛基准，不再回退切片下一档。
    assert threshold_prices == [10.8]
    assert captured["ledger_intent"] == "t"
    assert fake_redis.events[0][1] == "buy:000001"


def test_holding_buy_fallback_uses_broker_avg_price_when_no_fill(monkeypatch):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        holding_decision={
            "path": "holding_add",
            "quantity": 300,
            "grid_level": "BUY-1",
            "hit_levels": ["BUY-1"],
            "multiplier": 2,
            "source_price": 10.0,
            "buy_prices_snapshot": {"BUY-1": 10.3},
            "buy_active_before": [True],
        }
    )
    signal = _make_signal(price=10.0)
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: None,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 10.3,
                "quantity": 100,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_ledger_average_cost_reference",
        lambda _code: None,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_broker_position_average_cost_reference",
        lambda _code: {
            "fill_time": None,
            "fill_price": 10.2,
            "fill_reference_source": "broker_position_avg_price",
        },
    )
    threshold_prices = []
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, price: threshold_prices.append(price)
        or {"bot_river_price": 11.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    def fake_submit(
        action,
        symbol,
        price,
        quantity,
        remark=None,
        strategy_context=None,
        ledger_intent=None,
        is_profitable=None,
        trace_id=None,
        intent_id=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
                "ledger_intent": ledger_intent,
                "trace_id": trace_id,
                "intent_id": intent_id,
                "is_profitable": is_profitable,
            }
        )
        return {
            "request_id": "req_slice_1",
            "internal_order_id": "ord_slice_1",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert captured["action"] == "buy"
    assert captured["quantity"] == 300
    # #549：无 execution fill 且无 OM entries → xt_positions.avg_price 兜底门槛。
    assert threshold_prices == [10.2]
    assert captured["ledger_intent"] == "t"
    assert fake_redis.events[0][1] == "buy:000001"


def test_new_open_for_must_pool_uses_new_open_decision_without_auto_open_gate(
    monkeypatch,
):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        new_open_decision={
            "path": "new_open",
            "quantity": 10000,
            "initial_amount": 100000,
            "grid_level": None,
            "hit_levels": [],
            "multiplier": 1,
            "source_price": 10.0,
            "buy_prices_snapshot": None,
            "buy_active_before": None,
        }
    )
    signal = _make_signal(price=10.0)
    signal["tags"] = [guardian_module.MUST_POOL_5M_NEW_OPEN_TAG]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_auto_open",
        lambda: (_ for _ in ()).throw(
            AssertionError("auto_open should not gate must_pool new opens")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_position_pct",
        lambda: (_ for _ in ()).throw(
            AssertionError("position_pct should not gate must_pool new opens")
        ),
        raising=False,
    )

    def fake_submit(
        action,
        symbol,
        price,
        quantity,
        remark=None,
        strategy_context=None,
        ledger_intent=None,
        is_profitable=None,
        trace_id=None,
        intent_id=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
                "ledger_intent": ledger_intent,
                "trace_id": trace_id,
                "intent_id": intent_id,
            }
        )
        return {
            "request_id": "req_2",
            "internal_order_id": "ord_2",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert decision_service.calls == [("new_open", "000001", 10.0)]
    assert captured["action"] == "buy"
    assert captured["quantity"] == 10000
    assert captured["strategy_context"]["guardian_buy_grid"]["path"] == "new_open"
    assert captured["ledger_intent"] == "base"
    assert (
        captured["strategy_context"]["guardian_buy_grid"]["signal_time"]
        == signal["fire_time"].isoformat()
    )
    assert fake_redis.events[0][1] == "buy:000001"


def test_position_management_rejection_does_not_write_buy_cooldown(monkeypatch):
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    decision_service = FakeGuardianBuyGridService(
        holding_decision={
            "path": "holding_add",
            "quantity": 300,
            "grid_level": "BUY-1",
            "hit_levels": ["BUY-1"],
            "multiplier": 2,
            "source_price": 9.8,
            "buy_prices_snapshot": {"BUY-1": 10.0, "BUY-2": 9.0, "BUY-3": 8.0},
            "buy_active_before": [True, True, True],
        }
    )
    signal = _make_signal(price=9.8)
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: decision_service,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time, price=10.0),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 10.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    def fake_submit(*_args, **_kwargs):
        raise PositionManagementRejectedError("rejected")

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert decision_service.calls == [("holding_add", "000001", 9.8)]
    assert fake_redis.events == []


def test_guardian_sell_caps_quantity_by_can_use_volume_and_board_lot(monkeypatch):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    signal = _make_signal(position="SELL_SHORT", price=12.5)
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "position_type": "t",
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 10.0,
                "quantity": 300,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_trade_amount",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 9.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_position_reader",
        lambda: types.SimpleNamespace(get_can_use_volume=lambda _code: 250),
    )

    def fake_submit(action, symbol, price, quantity, **kwargs):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "kwargs": kwargs,
            }
        )
        return {
            "request_id": "req_sell_1",
            "internal_order_id": "ord_sell_1",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert captured["action"] == "sell"
    assert captured["symbol"] == "000001"
    assert captured["quantity"] == 200
    assert captured["kwargs"]["ledger_intent"] == "t"
    assert signal["quantity"] == 200


def test_guardian_sell_carries_selected_source_entries_in_strategy_context(
    monkeypatch,
):
    captured = {}
    fake_redis = FakeRedis()
    fake_order_alert = FakeOrderAlert()
    signal = _make_signal(position="SELL_SHORT", price=12.5)
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "entry_id": "entry_old",
                "position_type": "t",
                "date": int(fire_time.subtract(minutes=4).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=4).format("HH:mm:ss"),
                "price": 9.8,
                "quantity": 100,
            },
            {
                "entry_id": "entry_mid_1",
                "position_type": "t",
                "date": int(fire_time.subtract(minutes=3).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=3).format("HH:mm:ss"),
                "price": 9.7,
                "quantity": 1000,
            },
            {
                "entry_id": "entry_mid_2",
                "position_type": "t",
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 9.6,
                "quantity": 1000,
            },
            {
                "entry_id": "entry_new",
                "position_type": "t",
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 9.5,
                "quantity": 1000,
            },
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_trade_amount",
        lambda *_args, **_kwargs: 100,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 9.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", fake_redis)
    monkeypatch.setattr("freshquant.strategy.guardian.order_alert", fake_order_alert)
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_position_reader",
        lambda: types.SimpleNamespace(get_can_use_volume=lambda _code: 3100),
    )

    def fake_submit(action, symbol, price, quantity, **kwargs):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "kwargs": kwargs,
            }
        )
        return {
            "request_id": "req_sell_2",
            "internal_order_id": "ord_sell_2",
            "queue_payload": {},
        }

    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order", fake_submit
    )

    StrategyGuardian().on_signal(signal)

    assert captured["action"] == "sell"
    assert captured["quantity"] == 3100
    assert captured["kwargs"]["ledger_intent"] == "t"
    assert captured["kwargs"]["strategy_context"]["guardian_sell_sources"] == {
        "version": 2,
        "profitable_fill_count": 4,
        "requested_quantity": 3100,
        "submit_quantity": 3100,
        "slices": [],
        "entries": [
            {"entry_id": "entry_new", "quantity": 1000},
            {"entry_id": "entry_mid_2", "quantity": 1000},
            {"entry_id": "entry_mid_1", "quantity": 1000},
            {"entry_id": "entry_old", "quantity": 100},
        ],
    }
