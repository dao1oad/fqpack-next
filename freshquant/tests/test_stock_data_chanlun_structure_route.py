import importlib
import json
import sys
import types

import pytest


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

    stock_service = types.ModuleType("freshquant.stock_service")
    stock_service.get_stock_signal_list = lambda *args, **kwargs: []
    stock_service.get_stock_pools_list = lambda *args, **kwargs: []

    monkeypatch.setitem(sys.modules, "flask", flask_module)
    monkeypatch.setitem(sys.modules, "func_timeout", func_timeout_module)
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
    monkeypatch.setitem(sys.modules, "freshquant.stock_service", stock_service)


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


def test_stock_data_chanlun_structure_route_calls_service(monkeypatch, stock_routes):
    assert hasattr(stock_routes, "stock_data_chanlun_structure")

    called = {}

    def fake_service(symbol, period, end_date):
        called["args"] = (symbol, period, end_date)
        return {"ok": True, "symbol": symbol, "period": period, "endDate": end_date}

    monkeypatch.setattr(stock_routes, "get_chanlun_structure", fake_service)
    stock_routes.request.args = {
        "symbol": "sz000001",
        "period": "5m",
        "endDate": "2026-03-07",
    }

    response = stock_routes.stock_data_chanlun_structure()

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "symbol": "sz000001",
        "period": "5m",
        "endDate": "2026-03-07",
    }
    assert called["args"] == ("sz000001", "5m", "2026-03-07")
