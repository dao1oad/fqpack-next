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
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 10.0,
                "quantity": 100,
            }
        ],
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
    assert signal["quantity"] == 25600
    assert events == ["submit"]
    assert len(fake_redis.events) == 1
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
            "quantity": 15000,
            "initial_amount": 150000,
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
    assert captured["quantity"] == 15000
    assert captured["strategy_context"]["guardian_buy_grid"]["path"] == "new_open"
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
        "freshquant.strategy.guardian.get_arranged_stock_fill_list",
        lambda _code: [
            {
                "date": int(fire_time.subtract(minutes=1).format("YYYYMMDD")),
                "time": fire_time.subtract(minutes=1).format("HH:mm:ss"),
                "price": 10.0,
                "quantity": 100,
            }
        ],
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
