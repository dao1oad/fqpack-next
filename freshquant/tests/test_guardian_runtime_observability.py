from __future__ import annotations

import sys
import types

import pendulum


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
    assert captured["trace_id"] == submit_event["trace_id"]
    assert captured["intent_id"] == submit_event["intent_id"]


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
