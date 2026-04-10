from __future__ import annotations

import sys
import types

import pendulum

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


def _make_fill_reference(fire_time, *, price=10.0, source="execution_fill"):
    return {
        "fill_time": fire_time.subtract(minutes=1),
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
        is_profitable=None,
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
                "date": int(fire_time.add(minutes=1).format("YYYYMMDD")),
                "time": fire_time.add(minutes=1).format("HH:mm:ss"),
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
        is_profitable=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
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
    assert fake_redis.events[0][1] == "buy:000001"


def test_holding_buy_fallback_uses_next_guardian_slice_threshold(monkeypatch):
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
        "freshquant.strategy.guardian._get_guardian_buy_slice_grid_interval",
        lambda _code, _fill_reference: 1.03,
    )
    monkeypatch.setattr(
        "freshquant.strategy.guardian.eval_stock_threshold_price",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("threshold config should not be used for guardian fallback")
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
        is_profitable=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
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
        is_profitable=None,
    ):
        captured.update(
            {
                "action": action,
                "symbol": symbol,
                "price": price,
                "quantity": quantity,
                "remark": remark,
                "strategy_context": strategy_context,
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
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 10.0,
                "quantity": 300,
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
                "date": int(fire_time.subtract(minutes=4).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=4).format("HH:mm:ss"),
                "price": 9.8,
                "quantity": 100,
            },
            {
                "entry_id": "entry_mid_1",
                "date": int(fire_time.subtract(minutes=3).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=3).format("HH:mm:ss"),
                "price": 9.7,
                "quantity": 1000,
            },
            {
                "entry_id": "entry_mid_2",
                "date": int(fire_time.subtract(minutes=2).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=2).format("HH:mm:ss"),
                "price": 9.6,
                "quantity": 1000,
            },
            {
                "entry_id": "entry_new",
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 9.5,
                "quantity": 1000,
            },
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
    assert captured["kwargs"]["strategy_context"]["guardian_sell_sources"] == {
        "profitable_fill_count": 4,
        "requested_quantity": 3100,
        "submit_quantity": 3100,
        "entries": [
            {"entry_id": "entry_new", "quantity": 1000},
            {"entry_id": "entry_mid_2", "quantity": 1000},
            {"entry_id": "entry_mid_1", "quantity": 1000},
            {"entry_id": "entry_old", "quantity": 100},
        ],
    }
