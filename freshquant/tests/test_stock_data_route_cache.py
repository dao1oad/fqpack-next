import importlib
import json
import sys
import types

import pytest

from freshquant.util.period import get_redis_cache_key


def _install_route_stubs(monkeypatch):
    flask_module = types.ModuleType("flask")

    class _Blueprint:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def route(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _Response:
        def __init__(self, response="", mimetype=None, status=200):
            self._body = response
            self.mimetype = mimetype
            self.status_code = status

        def get_json(self):
            return json.loads(self._body)

    def _jsonify(payload=None):
        return _Response(json.dumps(payload), mimetype="application/json")

    flask_module.Blueprint = _Blueprint
    flask_module.Response = _Response
    flask_module.jsonify = _jsonify
    flask_module.request = types.SimpleNamespace(args={}, json=None)

    func_timeout_module = types.ModuleType("func_timeout")
    func_timeout_module.func_timeout = lambda timeout, func, args=(), kwargs=None: func(
        *(args or ()), **(kwargs or {})
    )

    stock_service = types.ModuleType("freshquant.stock_service")
    stock_service.get_stock_signal_list = lambda *args, **kwargs: []
    stock_service.get_stock_pools_list = lambda *args, **kwargs: []

    chanlun_service = types.ModuleType("freshquant.chanlun_service")
    chanlun_service.get_data_v2 = lambda *args, **kwargs: {}

    holding = types.ModuleType("freshquant.data.astock.holding")
    holding.get_arranged_stock_fill_list = lambda *args, **kwargs: []
    holding.get_stock_fills = lambda *args, **kwargs: []
    holding.get_stock_hold_position = lambda *args, **kwargs: None
    holding.get_stock_positions = lambda *args, **kwargs: []

    db = types.ModuleType("freshquant.db")
    db.DBfreshquant = {}

    instrument_general = types.ModuleType("freshquant.instrument.general")
    instrument_general.query_instrument_info = lambda *args, **kwargs: {}
    instrument_general.query_instrument_type = lambda *args, **kwargs: None

    position_future = types.ModuleType("freshquant.position.cn_future")
    position_future.queryArrangedCnFutureFillList = lambda *args, **kwargs: []

    cjsd_main = types.ModuleType("freshquant.research.cjsd.main")
    cjsd_main.getCjsdList = lambda *args, **kwargs: []

    business_service = types.ModuleType("freshquant.signal.BusinessService")

    class _BusinessService:
        pass

    business_service.BusinessService = _BusinessService

    trading_dt = types.ModuleType("freshquant.trading.dt")
    trading_dt.fq_trading_fetch_trade_dates = lambda *args, **kwargs: []

    util_code = types.ModuleType("freshquant.util.code")
    util_code.fq_util_code_append_market_code_suffix = lambda code: code

    util_encoder = types.ModuleType("freshquant.util.encoder")

    class _FqJsonEncoder(json.JSONEncoder):
        pass

    util_encoder.FqJsonEncoder = _FqJsonEncoder

    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "func_timeout", func_timeout_module)
    monkeypatch.setitem(sys.modules, "freshquant.stock_service", stock_service)
    monkeypatch.setitem(sys.modules, "freshquant.chanlun_service", chanlun_service)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.holding", holding)
    monkeypatch.setitem(sys.modules, "freshquant.db", db)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.general", instrument_general
    )
    monkeypatch.setitem(sys.modules, "freshquant.position.cn_future", position_future)
    monkeypatch.setitem(sys.modules, "freshquant.research.cjsd.main", cjsd_main)
    monkeypatch.setitem(
        sys.modules, "freshquant.signal.BusinessService", business_service
    )
    monkeypatch.setitem(sys.modules, "freshquant.trading.dt", trading_dt)
    monkeypatch.setitem(sys.modules, "freshquant.util.code", util_code)
    monkeypatch.setitem(sys.modules, "freshquant.util.encoder", util_encoder)


@pytest.fixture
def stock_routes(monkeypatch):
    original_routes = sys.modules.get("freshquant.rear.stock.routes")
    _install_route_stubs(monkeypatch)
    try:
        import freshquant.rear.stock.routes as stock_routes_module

        yield importlib.reload(stock_routes_module)
    finally:
        if original_routes is None:
            sys.modules.pop("freshquant.rear.stock.routes", None)
        else:
            sys.modules["freshquant.rear.stock.routes"] = original_routes


class FakeRedis:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.keys = []

    def get(self, key):
        self.keys.append(key)
        if self.error is not None:
            raise self.error
        return self.value


def call_stock_data(stock_routes, **params):
    stock_routes.request.args = params
    return stock_routes.stock_data()


def test_stock_data_uses_fallback_by_default(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=json.dumps({"source": "cache"}))
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(stock_routes, symbol="sz000001", period="5m")

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "fallback",
        "symbol": "sz000001",
        "period": "5m",
    }
    assert fallback_calls == [("sz000001", "5m", None, 0)]
    assert fake_redis.keys == []


def test_stock_data_reads_redis_for_opt_in_realtime_period(monkeypatch, stock_routes):
    cached_payload = {"symbol": "sz000001", "period": "5m", "close": [1, 2, 3]}
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes,
        "get_data_v2",
        lambda symbol, period, end_date: {"source": "fallback"},
    )

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="5m", realtimeCache="1"
    )

    assert response.status_code == 200
    assert response.get_json() == cached_payload
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "5min")]


def test_stock_data_falls_back_when_opt_in_cache_missing(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="15m", realtimeCache="true"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "fallback",
        "symbol": "sz000001",
        "period": "15m",
    }
    assert fallback_calls == [("sz000001", "15m", None, 0)]
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "15min")]


def test_stock_data_reads_redis_for_opt_in_1d_period(monkeypatch, stock_routes):
    cached_payload = {"symbol": "sz000001", "period": "1d", "close": [1, 2, 3]}
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes,
        "get_data_v2",
        lambda *args, **kwargs: pytest.fail("1d cache hit should not call fallback"),
    )

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="1d", realtimeCache="1"
    )

    assert response.status_code == 200
    assert response.get_json() == cached_payload
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "1d")]


def test_stock_data_falls_back_when_opt_in_1d_cache_missing(
    monkeypatch, stock_routes
):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="1d", realtimeCache="true"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "fallback",
        "symbol": "sz000001",
        "period": "1d",
    }
    assert fallback_calls == [("sz000001", "1d", None, 0)]
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "1d")]


def test_stock_data_skips_redis_when_end_date_present(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=json.dumps({"source": "cache"}))
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "history", "endDate": end_date}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="5m", endDate="2026-03-05"
    )

    assert response.status_code == 200
    assert response.get_json() == {"source": "history", "endDate": "2026-03-05"}
    assert fallback_calls == [("sz000001", "5m", "2026-03-05", 0)]
    assert fake_redis.keys == []


def test_stock_data_tails_cache_payload_when_bar_count_is_provided(
    monkeypatch, stock_routes
):
    cached_payload = {
        "symbol": "sz000001",
        "period": "5m",
        "date": [
            "2026-03-10 09:30",
            "2026-03-10 09:35",
            "2026-03-10 09:40",
            "2026-03-10 09:45",
            "2026-03-10 09:50",
        ],
        "open": [1, 2, 3, 4, 5],
        "high": [2, 3, 4, 5, 6],
        "low": [0, 1, 2, 3, 4],
        "close": [1.5, 2.5, 3.5, 4.5, 5.5],
    }
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes,
        "get_data_v2",
        lambda *args, **kwargs: pytest.fail("cache hit should not call fallback"),
    )

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="5m", realtimeCache="1", barCount="3"
    )

    assert response.status_code == 200
    assert response.get_json()["date"] == [
        "2026-03-10 09:40",
        "2026-03-10 09:45",
        "2026-03-10 09:50",
    ]
    assert response.get_json()["close"] == [3.5, 4.5, 5.5]


def test_stock_data_forwards_bar_count_to_fallback(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "barCount": bar_count}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes,
        symbol="sz000001",
        period="5m",
        realtimeCache="1",
        barCount="20000",
    )

    assert response.status_code == 200
    assert response.get_json() == {"source": "fallback", "barCount": 20000}
    assert fallback_calls == [("sz000001", "5m", None, 20000)]


def test_stock_data_clamps_oversized_bar_count_before_fallback(
    monkeypatch, stock_routes
):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "barCount": bar_count}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes,
        symbol="sz000001",
        period="5m",
        realtimeCache="1",
        barCount="999999",
    )

    assert response.status_code == 200
    assert response.get_json() == {"source": "fallback", "barCount": 20000}
    assert fallback_calls == [("sz000001", "5m", None, 20000)]
