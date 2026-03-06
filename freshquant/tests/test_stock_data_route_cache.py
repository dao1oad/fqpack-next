import json
import sys
import types

from flask import Flask

from freshquant.util.period import get_redis_cache_key


def _install_route_stubs():
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

    sys.modules["freshquant.stock_service"] = stock_service
    sys.modules["freshquant.chanlun_service"] = chanlun_service
    sys.modules["freshquant.data.astock.holding"] = holding
    sys.modules["freshquant.db"] = db
    sys.modules["freshquant.instrument.general"] = instrument_general
    sys.modules["freshquant.position.cn_future"] = position_future
    sys.modules["freshquant.research.cjsd.main"] = cjsd_main
    sys.modules["freshquant.signal.BusinessService"] = business_service
    sys.modules["freshquant.trading.dt"] = trading_dt
    sys.modules["freshquant.util.code"] = util_code
    sys.modules["freshquant.util.encoder"] = util_encoder


_install_route_stubs()

import freshquant.rear.stock.routes as stock_routes


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


def make_client():
    app = Flask(__name__)
    app.register_blueprint(stock_routes.stock_bp)
    return app.test_client()


def test_stock_data_reads_redis_for_realtime_period(monkeypatch):
    cached_payload = {"symbol": "sz000001", "period": "5m", "close": [1, 2, 3]}
    fake_redis = FakeRedis(value=json.dumps(cached_payload))

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(
        stock_routes,
        "get_data_v2",
        lambda symbol, period, end_date: {"source": "fallback"},
    )

    client = make_client()
    response = client.get("/api/stock_data?symbol=sz000001&period=5m")

    assert response.status_code == 200
    assert response.get_json() == cached_payload
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "5min")]


def test_stock_data_falls_back_when_cache_missing(monkeypatch):
    fake_redis = FakeRedis(value=None)
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date):
        fallback_calls.append((symbol, period, end_date))
        return {"source": "fallback", "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    client = make_client()
    response = client.get("/api/stock_data?symbol=sz000001&period=15m")

    assert response.status_code == 200
    assert response.get_json() == {
        "source": "fallback",
        "symbol": "sz000001",
        "period": "15m",
    }
    assert fallback_calls == [("sz000001", "15m", None)]
    assert fake_redis.keys == [get_redis_cache_key("sz000001", "15min")]


def test_stock_data_skips_redis_when_end_date_present(monkeypatch):
    fake_redis = FakeRedis(value=json.dumps({"source": "cache"}))
    fallback_calls = []

    def fake_get_data_v2(symbol, period, end_date):
        fallback_calls.append((symbol, period, end_date))
        return {"source": "history", "endDate": end_date}

    monkeypatch.setattr(stock_routes, "redis_db", fake_redis)
    monkeypatch.setattr(stock_routes, "get_data_v2", fake_get_data_v2)

    client = make_client()
    response = client.get(
        "/api/stock_data?symbol=sz000001&period=5m&endDate=2026-03-05"
    )

    assert response.status_code == 200
    assert response.get_json() == {"source": "history", "endDate": "2026-03-05"}
    assert fallback_calls == [("sz000001", "5m", "2026-03-05")]
    assert fake_redis.keys == []
