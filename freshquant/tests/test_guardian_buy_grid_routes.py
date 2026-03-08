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

    class _Request:
        def __init__(self):
            self.args = {}
            self.json = None

        def get_json(self, silent=False):
            return self.json

    def _jsonify(payload=None):
        return _Response(json.dumps(payload), mimetype="application/json")

    flask_module.Blueprint = _Blueprint
    flask_module.Response = _Response
    flask_module.jsonify = _jsonify
    flask_module.request = _Request()

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
    business_service.BusinessService = lambda: object()

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


def test_guardian_buy_grid_config_routes_get_and_post(monkeypatch, stock_routes):
    captured = {}

    class FakeService:
        def get_config(self, code):
            captured["get_code"] = code
            return {
                "code": code,
                "BUY-1": 10.0,
                "BUY-2": 9.0,
                "BUY-3": 8.0,
                "enabled": True,
            }

        def upsert_config(self, code, **kwargs):
            captured["upsert"] = (code, kwargs)
            return {"code": code, **kwargs}

    monkeypatch.setattr(
        stock_routes,
        "_get_guardian_buy_grid_service",
        lambda: FakeService(),
        raising=False,
    )

    stock_routes.request.args = {"code": "000001"}
    response = stock_routes.guardian_buy_grid_config_get()

    assert response.status_code == 200
    assert response.get_json()["code"] == "000001"
    assert captured["get_code"] == "000001"

    stock_routes.request.json = {
        "code": "000001",
        "buy_1": 10.1,
        "buy_2": 9.1,
        "buy_3": 8.1,
        "enabled": True,
        "updated_by": "pytest",
    }
    response = stock_routes.guardian_buy_grid_config_post()

    assert response.status_code == 200
    assert captured["upsert"] == (
        "000001",
        {
            "buy_1": 10.1,
            "buy_2": 9.1,
            "buy_3": 8.1,
            "enabled": True,
            "updated_by": "pytest",
        },
    )


def test_guardian_buy_grid_state_routes_get_post_and_reset(monkeypatch, stock_routes):
    captured = {}

    class FakeService:
        def get_state(self, code):
            captured["get_code"] = code
            return {"code": code, "buy_active": [True, False, False]}

        def upsert_state(self, code, **kwargs):
            captured["upsert"] = (code, kwargs)
            return {"code": code, **kwargs}

        def reset_after_sell_trade(self, code, **kwargs):
            captured["reset"] = (code, kwargs)
            return {"code": code, "buy_active": [True, True, True]}

    monkeypatch.setattr(
        stock_routes,
        "_get_guardian_buy_grid_service",
        lambda: FakeService(),
        raising=False,
    )

    stock_routes.request.args = {"code": "000001"}
    response = stock_routes.guardian_buy_grid_state_get()

    assert response.status_code == 200
    assert response.get_json()["buy_active"] == [True, False, False]

    stock_routes.request.json = {
        "code": "000001",
        "buy_active": [False, True, True],
        "last_hit_level": "BUY-1",
        "last_hit_price": 9.8,
        "updated_by": "pytest",
    }
    response = stock_routes.guardian_buy_grid_state_post()

    assert response.status_code == 200
    assert captured["upsert"] == (
        "000001",
        {
            "buy_active": [False, True, True],
            "last_hit_level": "BUY-1",
            "last_hit_price": 9.8,
            "last_hit_signal_time": None,
            "last_reset_reason": None,
            "updated_by": "pytest",
        },
    )

    stock_routes.request.json = {"code": "000001", "updated_by": "pytest"}
    response = stock_routes.guardian_buy_grid_state_reset()

    assert response.status_code == 200
    assert captured["reset"] == (
        "000001",
        {"updated_by": "pytest", "reason": "manual_reset"},
    )
