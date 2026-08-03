import importlib
import json
import sys
import types
from datetime import datetime as real_datetime

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
    stock_service.sync_stock_pools_from_tdx_self_select = lambda *args, **kwargs: {}

    chanlun_service = types.ModuleType("freshquant.chanlun_service")
    chanlun_service.get_data_v2 = lambda *args, **kwargs: {}

    holding = types.ModuleType("freshquant.data.astock.holding")
    holding.get_arranged_stock_fill_list = lambda *args, **kwargs: []
    holding.get_stock_fills = lambda *args, **kwargs: []
    holding.get_stock_hold_position = lambda *args, **kwargs: None
    holding.get_stock_positions = lambda *args, **kwargs: []

    db = types.ModuleType("freshquant.db")
    db.DBfreshquant = {}
    db.DBQuantAxis = {}

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
    util_code.normalize_to_base_code = (
        lambda code: str(code or "").replace("sz", "").replace("sh", "")
    )

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


def test_stock_data_normalizes_backend_minute_alias_before_fallback(
    monkeypatch, stock_routes
):
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "period": period}

    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(stock_routes, symbol="sz000001", period="15min")

    assert response.status_code == 200
    assert response.get_json()["period"] == "15m"
    assert fallback_calls == [("sz000001", "15m", None, 0)]


def test_stock_data_maps_qfq_not_ready_to_503(monkeypatch, stock_routes):
    def fail(*_args, **_kwargs):
        raise stock_routes.QFQDataNotReadyError(
            "active snapshot is missing", scope="stock", code="000001"
        )

    monkeypatch.setattr(stock_routes, "get_data_v2", fail)

    response = call_stock_data(stock_routes, symbol="sz000001", period="5m")

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "QFQ_DATA_NOT_READY"


def test_stock_data_realtime_qfq_not_ready_falls_back_to_history(
    monkeypatch, stock_routes
):
    fallback_calls = []

    def fail_realtime(*_args, **_kwargs):
        raise stock_routes.QFQDataNotReadyError(
            "intraday override is missing", scope="stock", code="000001"
        )

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "history", "symbol": symbol, "period": period}

    monkeypatch.setattr(
        stock_routes, "_get_realtime_stock_data_from_cache", fail_realtime
    )
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes, symbol="sz000001", period="30min", realtimeCache="1"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "history",
        "symbol": "sz000001",
        "period": "30m",
    }
    assert fallback_calls == [("sz000001", "30m", None, 0)]


def test_stock_data_realtime_today_qfq_gap_uses_previous_trade_date(
    monkeypatch, stock_routes
):
    class FakeDatetime:
        @staticmethod
        def now():
            return real_datetime(2026, 8, 3, 10, 30)

    calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        calls.append((symbol, period, end_date, bar_count))
        if end_date is None:
            raise stock_routes.QFQDataNotReadyError(
                "snapshot-bound intraday override is missing",
                scope="stock",
                code="300127",
                missing_dates=["2026-08-03"],
            )
        return {"source": "history", "endDate": end_date, "barCount": bar_count}

    monkeypatch.setattr(stock_routes, "datetime", FakeDatetime)
    monkeypatch.setattr(
        stock_routes, "_get_realtime_stock_data_from_cache", lambda *args: None
    )
    monkeypatch.setattr(
        stock_routes,
        "fq_trading_fetch_trade_dates",
        lambda *args, **kwargs: ["2026-07-30", "2026-07-31", "2026-08-03"],
    )
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    response = call_stock_data(
        stock_routes,
        symbol="sz300127",
        period="15min",
        realtimeCache="1",
        barCount="5",
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "history",
        "endDate": "2026-07-31",
        "barCount": 5,
    }
    assert calls == [
        ("sz300127", "15m", None, 5),
        ("sz300127", "15m", "2026-07-31", 5),
    ]


def test_stock_data_explicit_end_date_qfq_gap_stays_503(monkeypatch, stock_routes):
    def fail(*_args, **_kwargs):
        raise stock_routes.QFQDataNotReadyError(
            "snapshot-bound intraday override is missing",
            scope="stock",
            code="300127",
            missing_dates=["2026-08-03"],
        )

    monkeypatch.setattr(stock_routes, "get_data_v2", fail)

    response = call_stock_data(
        stock_routes,
        symbol="sz300127",
        period="15min",
        endDate="2026-08-03",
        realtimeCache="1",
    )

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "QFQ_DATA_NOT_READY"


def test_stock_data_v2_maps_qfq_not_ready_to_503(monkeypatch, stock_routes):
    def fail(*_args, **_kwargs):
        raise stock_routes.QFQDataNotReadyError(
            "active snapshot is missing", scope="stock", code="000001"
        )

    monkeypatch.setattr(stock_routes, "get_data_v2", fail)
    stock_routes.request.args = {"symbol": "sz000001", "period": "5m"}

    response = stock_routes.stock_data_v2()

    assert response.status_code == 503
    assert response.get_json()["error_code"] == "QFQ_DATA_NOT_READY"


def test_stock_data_v2_normalizes_backend_minute_alias(monkeypatch, stock_routes):
    calls = []

    def fake_get_data_v2(symbol, period, end_date):
        calls.append((symbol, period, end_date))
        return {"period": period}

    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)
    stock_routes.request.args = {"symbol": "sz000001", "period": "30min"}

    response = stock_routes.stock_data_v2()

    assert response.status_code == 200
    assert response.get_json() == {"period": "30m"}
    assert calls == [("sz000001", "30m", None)]


def test_sync_stock_pools_from_tdx_self_select_route_calls_service(
    monkeypatch, stock_routes
):
    calls = []

    service = types.SimpleNamespace(
        sync_stock_pools_from_tdx_self_select=lambda days: calls.append(days)
        or {"appended_count": 2}
    )
    monkeypatch.setattr(stock_routes, "_get_stock_service", lambda: service)
    stock_routes.request.args = {"days": "45"}

    response = stock_routes.sync_stock_pools_from_tdx_self_select()

    assert response.status_code == 200
    assert response.get_json() == {
        "code": "0",
        "msg": "操作成功",
        "data": {"appended_count": 2},
    }
    assert calls == [45]


def test_stock_data_cache_key_is_bound_to_adjustment_version(monkeypatch, stock_routes):
    payload = {"symbol": "sz000001", "period": "5m"}
    fake_redis = FakeRedis(value=json.dumps(payload))
    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v2"
    )

    response = call_stock_data(
        stock_routes,
        symbol="sz000001",
        period="5m",
        realtimeCache="true",
    )

    assert response.status_code == 200
    assert fake_redis.keys == [
        get_redis_cache_key("sz000001", "5min", adjustment_version="snapshot-v2")
    ]


def test_index_cache_key_uses_bfq_version_written_by_strategy_consumer(
    monkeypatch, stock_routes
):
    payload = {"symbol": "sh000001", "period": "5m"}
    fake_redis = FakeRedis(value=json.dumps(payload))
    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes,
        "query_instrument_type",
        lambda _symbol: stock_routes.InstrumentType.INDEX_CN,
    )

    response = call_stock_data(
        stock_routes,
        symbol="sh000001",
        period="5m",
        realtimeCache="true",
    )

    assert response.status_code == 200
    assert response.get_json() == payload
    assert fake_redis.keys == [
        get_redis_cache_key("sh000001", "5min", adjustment_version="bfq")
    ]


def test_stock_data_reads_redis_for_opt_in_realtime_period(monkeypatch, stock_routes):
    cached_payload = {"symbol": "sz000001", "period": "5m", "close": [1, 2, 3]}
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
    assert fake_redis.keys == [
        get_redis_cache_key("sz000001", "5min", adjustment_version="snapshot-v1")
    ]


def test_stock_data_falls_back_when_opt_in_cache_missing(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
    assert fake_redis.keys == [
        get_redis_cache_key("sz000001", "15min", adjustment_version="snapshot-v1")
    ]


def test_stock_data_reads_redis_for_opt_in_1d_period(monkeypatch, stock_routes):
    cached_payload = {"symbol": "sz000001", "period": "1d", "close": [1, 2, 3]}
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
    assert fake_redis.keys == [
        get_redis_cache_key("sz000001", "1d", adjustment_version="snapshot-v1")
    ]


def test_stock_data_falls_back_when_opt_in_1d_cache_missing(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
    assert fake_redis.keys == [
        get_redis_cache_key("sz000001", "1d", adjustment_version="snapshot-v1")
    ]


def test_stock_data_skips_redis_when_end_date_present(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=json.dumps({"source": "cache"}))
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count=0):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "history", "endDate": end_date}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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


def test_unknown_instrument_never_reads_unversioned_realtime_cache(
    monkeypatch, stock_routes
):
    fake_redis = FakeRedis(value=json.dumps({"source": "stale-unversioned"}))
    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "query_instrument_type", lambda _symbol: None)
    monkeypatch.setattr(
        stock_routes,
        "get_data_v2",
        lambda symbol, period, end_date, bar_count=0: {"source": "fallback"},
    )

    response = call_stock_data(
        stock_routes, symbol="unknown", period="5m", realtimeCache="1"
    )

    assert response.status_code == 200
    assert response.get_json() == {"source": "fallback"}
    assert fake_redis.keys == []


def test_stock_data_forwards_bar_count_to_fallback(monkeypatch, stock_routes):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date, bar_count):
        fallback_calls.append((symbol, period, end_date, bar_count))
        return {"source": "fallback", "barCount": bar_count}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
    monkeypatch.setattr(
        stock_routes, "_resolve_qfq_cache_version", lambda _symbol: "snapshot-v1"
    )
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
