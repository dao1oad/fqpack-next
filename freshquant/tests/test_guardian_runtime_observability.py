from __future__ import annotations

import sys
import types

import pendulum
import pytest


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
sys.modules.setdefault(
    "freshquant.strategy.toolkit.threshold",
    _module(
        "freshquant.strategy.toolkit.threshold",
        eval_stock_threshold_price=lambda _code, _price: {
            "bot_river_price": 0.0,
            "top_river_price": 0.0,
        },
    ),
)
sys.modules.setdefault(
    "freshquant.data.astock.holding",
    _module(
        "freshquant.data.astock.holding",
        _query_grid_interval=lambda _code, _date_str: 1.03,
        get_arranged_stock_fill_list=lambda _code: [],
        get_stock_holding_codes=lambda: [],
    ),
)
sys.modules.setdefault(
    "freshquant.pool.general",
    _module("freshquant.pool.general", queryMustPoolCodes=lambda: []),
)
sys.modules.setdefault(
    "freshquant.position.stock",
    _module(
        "freshquant.position.stock",
        query_stock_position_pct=lambda *_args, **_kwargs: 0,
    ),
)

from freshquant.strategy.guardian import StrategyGuardian

sys.modules.pop("freshquant.message", None)


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl):
        self.data[key] = value
        return True


class FakeGuardianBuyGridService:
    def build_holding_add_decision(self, code, price):
        return {
            "path": "holding_add",
            "quantity": 300,
            "grid_level": "BUY-1",
            "hit_levels": ["BUY-1"],
            "multiplier": 2,
            "source_price": price,
            "buy_prices_snapshot": {"BUY-1": 10.0},
            "buy_active_before": [True],
        }

    def build_new_open_decision(self, code, price):
        return {
            "path": "new_open",
            "quantity": 300,
            "grid_level": "BUY-0",
            "hit_levels": ["BUY-0"],
            "multiplier": 1,
            "source_price": price,
            "buy_prices_snapshot": {"BUY-0": price},
            "buy_active_before": [],
        }


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


def test_guardian_submit_intent_emits_trace_step(monkeypatch):
    captured = {}
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time, price=10.0),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 10.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
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
        is_profitable=None,
        strategy_context=None,
        trace_id=None,
        intent_id=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "trace_id": trace_id,
                "intent_id": intent_id,
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

    guardian.on_signal(signal)

    submit_event = next(
        event
        for event in runtime_logger.events
        if event["component"] == "guardian_strategy"
        and event["node"] == "submit_intent"
    )
    assert submit_event["trace_id"].startswith("trc_")
    assert submit_event["intent_id"].startswith("int_")
    assert submit_event["signal_summary"]["code"] == signal["code"]
    assert submit_event["signal_summary"]["position"] == signal["position"]
    assert submit_event["decision_context"]["quantity"]["quantity"] == 300
    assert submit_event["decision_outcome"]["outcome"] == "submit"
    assert captured["trace_id"] == submit_event["trace_id"]
    assert captured["intent_id"] == submit_event["intent_id"]


def test_guardian_holding_buy_price_threshold_emits_structured_skip_finish(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time, price=10.0),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 9.5, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *args, **kwargs: None,
    )

    guardian.on_signal(signal)

    price_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "price_threshold_check"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert price_event["signal_summary"]["code"] == signal["code"]
    assert (
        price_event["decision_context"]["threshold"]["current_price"] == signal["price"]
    )
    assert (
        price_event["decision_context"]["threshold"]["fill_reference_source"]
        == "execution_fill"
    )
    assert (
        price_event["decision_context"]["threshold"]["threshold_rule_source"]
        == "threshold_config"
    )
    assert price_event["decision_context"]["threshold"]["bot_river_price"] == 9.5
    assert price_event["decision_outcome"]["outcome"] == "skip"
    assert price_event["reason_code"] == "price_threshold_not_met"

    assert finish_event["signal_summary"]["code"] == signal["code"]
    assert finish_event["decision_outcome"]["outcome"] == "skip"
    assert finish_event["reason_code"] == "price_threshold_not_met"
    assert finish_event["status"] == "skipped"


def test_guardian_holding_buy_guardian_slice_fallback_emits_slice_threshold_rule(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    signal["price"] = 10.01
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
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
                "price": 10.3,
                "quantity": 100,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_guardian_buy_slice_grid_interval",
        lambda _code, _fill_reference: 1.03,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.fq_util_code_append_market_code_suffix",
        lambda _code: f"SZ{_code}",
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("threshold config should not be used for guardian fallback")
        ),
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *args, **kwargs: None,
    )

    guardian.on_signal(signal)

    price_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "price_threshold_check"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert (
        price_event["decision_context"]["threshold"]["fill_reference_source"]
        == "guardian_arranged_fill_fallback"
    )
    assert (
        price_event["decision_context"]["threshold"]["threshold_rule_source"]
        == "guardian_slice_next_level"
    )
    assert price_event["decision_context"]["threshold"]["grid_interval"] == 1.03
    assert price_event["decision_context"]["threshold"]["bot_river_price"] == 10.0
    assert price_event["decision_context"]["threshold"]["top_river_price"] == 10.3
    assert price_event["decision_outcome"]["outcome"] == "skip"
    assert finish_event["reason_code"] == "price_threshold_not_met"


def test_guardian_new_open_buy_cooldown_emits_structured_skip_finish(monkeypatch):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()

    fake_redis = FakeRedis()
    fake_redis.data["fq:xtrade:last_new_order_time"] = "2026-03-09 10:00:00"

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
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
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *args, **kwargs: None,
    )

    guardian.on_signal(signal)

    cooldown_event = next(
        event for event in runtime_logger.events if event["node"] == "cooldown_check"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert cooldown_event["signal_summary"]["code"] == signal["code"]
    assert (
        cooldown_event["decision_context"]["cooldown"]["key"]
        == "fq:xtrade:last_new_order_time"
    )
    assert cooldown_event["decision_context"]["cooldown"]["active"] is True
    assert cooldown_event["decision_outcome"]["outcome"] == "skip"
    assert cooldown_event["reason_code"] == "new_open_cooldown_active"

    assert finish_event["decision_outcome"]["outcome"] == "skip"
    assert finish_event["reason_code"] == "new_open_cooldown_active"
    assert finish_event["status"] == "skipped"


def test_guardian_scope_exception_emits_error_at_scope_node(monkeypatch):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: (_ for _ in ()).throw(
            RuntimeError("holding scope backend unavailable")
        ),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )

    with pytest.raises(RuntimeError, match="holding scope backend unavailable"):
        guardian.on_signal(signal)

    error_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "holding_scope_resolve" and event["status"] == "error"
    )
    assert error_event["reason_code"] == "unexpected_exception"
    assert error_event["payload"]["error_type"] == "RuntimeError"
    assert (
        error_event["payload"]["error_message"] == "holding scope backend unavailable"
    )
    assert runtime_logger.events[-1] == error_event


def test_guardian_holding_buy_unexpected_exception_emits_error_at_timing_check(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: None,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": None,
                "time": None,
                "price": 10.0,
                "quantity": 100,
            }
        ],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )

    with pytest.raises(ValueError, match="None None"):
        guardian.on_signal(signal)

    error_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "timing_check" and event["status"] == "error"
    )
    assert error_event["reason_code"] == "unexpected_exception"
    assert error_event["payload"]["error_type"] == "ValueError"
    assert "None None" in error_event["payload"]["error_message"]
    assert runtime_logger.events[-1] == error_event


def test_guardian_new_open_buy_unexpected_exception_emits_error_at_quantity_check(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: types.SimpleNamespace(
            build_new_open_decision=lambda *_args, **_kwargs: (
                (_ for _ in ()).throw(RuntimeError("grid decision unavailable"))
            )
        ),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.queryMustPoolCodes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )

    with pytest.raises(RuntimeError, match="grid decision unavailable"):
        guardian.on_signal(signal)

    error_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "quantity_check" and event["status"] == "error"
    )
    assert error_event["reason_code"] == "unexpected_exception"
    assert error_event["payload"]["error_type"] == "RuntimeError"
    assert error_event["payload"]["error_message"] == "grid decision unavailable"
    assert runtime_logger.events[-1] == error_event


def test_guardian_buy_submit_unexpected_exception_emits_error_at_submit_intent(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_latest_execution_fill_reference",
        lambda _code: _make_fill_reference(fire_time, price=10.0),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda _code, _price: {"bot_river_price": 10.0, "top_river_price": 12.0},
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("submit failed")),
    )

    with pytest.raises(RuntimeError, match="submit failed"):
        guardian.on_signal(signal)

    error_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "submit_intent" and event["status"] == "error"
    )
    assert error_event["reason_code"] == "unexpected_exception"
    assert error_event["payload"]["error_type"] == "RuntimeError"
    assert error_event["payload"]["error_message"] == "submit failed"
    assert runtime_logger.events[-1] == error_event


def test_guardian_sell_unexpected_exception_emits_error_and_failed_finish(monkeypatch):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    signal["position"] = "SELL_SHORT"

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_guardian_buy_grid_service",
        lambda: FakeGuardianBuyGridService(),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": None,
                "time": None,
                "price": 10.0,
                "quantity": 100,
            }
        ],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            exception=lambda *args, **kwargs: None,
        ),
    )

    with pytest.raises(ValueError, match="None None"):
        guardian.on_signal(signal)

    error_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "timing_check" and event["status"] == "error"
    )
    assert error_event["reason_code"] == "unexpected_exception"
    assert error_event["payload"]["error_type"] == "ValueError"
    assert "None None" in error_event["payload"]["error_message"]
    assert runtime_logger.events[-1] == error_event


def test_guardian_sell_board_lot_check_emits_structured_skip_finish(monkeypatch):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    signal["position"] = "SELL_SHORT"
    signal["price"] = 12.5
    fire_time = signal["fire_time"]

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 10.0,
                "quantity": 50,
            }
        ],
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
    monkeypatch.setattr(
        "freshquant.strategy.guardian._get_position_reader",
        lambda: types.SimpleNamespace(get_can_use_volume=lambda _code: 500),
    )
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submit should not be called")
        ),
    )

    guardian.on_signal(signal)

    sellable_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "sellable_volume_check"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert sellable_event["reason_code"] == "sell_board_lot_blocked"
    assert sellable_event["decision_outcome"]["outcome"] == "skip"
    assert sellable_event["decision_context"]["quantity"]["raw_quantity"] == 50
    assert sellable_event["decision_context"]["quantity"]["submit_quantity"] == 0
    assert finish_event["reason_code"] == "sell_board_lot_blocked"
    assert finish_event["decision_outcome"]["outcome"] == "skip"


def test_guardian_sell_degraded_arrangement_emits_structured_skip_finish(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    signal["position"] = "SELL_SHORT"

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.list_open_entry_views",
        lambda symbol=None: [
            {
                "entry_id": "entry_1",
                "symbol": symbol,
                "remaining_quantity": 300,
                "arrange_status": "DEGRADED",
                "arrange_degraded": True,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submit should not be called")
        ),
    )

    guardian.on_signal(signal)

    holding_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "holding_scope_resolve"
        and event["status"] == "skipped"
        and event["reason_code"] == "arrangement_degraded"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert holding_event["decision_context"]["scope"]["in_holding"] is True
    assert holding_event["decision_context"]["scope"]["entry_count"] == 1
    assert holding_event["decision_context"]["scope"]["degraded_entry_count"] == 1
    assert (
        holding_event["decision_context"]["scope"]["arrangement_state"]
        == "entry_present_arrangement_degraded"
    )
    assert finish_event["reason_code"] == "arrangement_degraded"
    assert finish_event["decision_outcome"]["outcome"] == "skip"


def test_guardian_sell_entry_without_slices_emits_structured_skip_finish(monkeypatch):
    runtime_logger = FakeRuntimeLogger()
    guardian = StrategyGuardian()
    guardian.runtime_logger = runtime_logger
    signal = _make_signal()
    signal["position"] = "SELL_SHORT"

    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.list_open_entry_views",
        lambda symbol=None: [
            {
                "entry_id": "entry_1",
                "symbol": symbol,
                "remaining_quantity": 300,
                "arrange_status": "READY",
                "arrange_degraded": False,
            }
        ],
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.get_stock_holding_codes",
        lambda: ["000001"],
    )
    monkeypatch.setattr("freshquant.strategy.guardian.queryMustPoolCodes", lambda: [])
    monkeypatch.setattr("freshquant.strategy.guardian.redis_db", FakeRedis())
    monkeypatch.setattr(
        "freshquant.strategy.guardian.order_alert",
        types.SimpleNamespace(send=lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.logger",
        types.SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.submit_guardian_order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submit should not be called")
        ),
    )

    guardian.on_signal(signal)

    holding_event = next(
        event
        for event in runtime_logger.events
        if event["node"] == "holding_scope_resolve"
        and event["status"] == "skipped"
        and event["reason_code"] == "entry_without_slices"
    )
    finish_event = next(
        event for event in runtime_logger.events if event["node"] == "finish"
    )

    assert holding_event["decision_context"]["scope"]["in_holding"] is True
    assert holding_event["decision_context"]["scope"]["entry_count"] == 1
    assert holding_event["decision_context"]["scope"]["degraded_entry_count"] == 0
    assert (
        holding_event["decision_context"]["scope"]["arrangement_state"]
        == "entry_present_without_slices"
    )
    assert finish_event["reason_code"] == "entry_without_slices"
    assert finish_event["decision_outcome"]["outcome"] == "skip"


def _make_signal():
    now = pendulum.now()
    return {
        "symbol": "000001",
        "code": "000001",
        "name": "Ping An Bank",
        "period": "1m",
        "fire_time": now,
        "discover_time": now,
        "price": 9.8,
        "stop_lose_price": 7.0,
        "position": "BUY_LONG",
        "remark": "runtime-test",
        "tags": [],
        "zsdata": None,
        "fills": None,
    }
