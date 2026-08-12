# -*- coding: utf-8 -*-

"""#589：/api/pools/must/sync-from-tdx allow_empty 透传与 empty_group 400 响应测试。"""

import pytest
from flask import Flask

from freshquant.rear.stock import routes as stock_routes


class _FakeStockService:
    class TdxEmptyGroupError(RuntimeError):
        pass

    def __init__(self, fail_with=None, seen=None):
        self.fail_with = fail_with
        self.seen = seen

    def sync_must_pool_from_tdx_self_select(self, days=30, allow_empty=False):
        self.seen.append({"days": days, "allow_empty": allow_empty})
        if self.fail_with is not None:
            raise self.fail_with
        return {"synced_codes": ["600000"], "removed_codes": []}


@pytest.fixture
def route_app(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(stock_routes.stock_bp)
    app.testing = True
    return app


def test_sync_must_pool_allow_empty_passthrough(route_app, monkeypatch):
    seen = []
    monkeypatch.setattr(
        stock_routes,
        "_get_stock_service",
        lambda: _FakeStockService(seen=seen),
    )

    resp = route_app.test_client().post(
        "/api/pools/must/sync-from-tdx?days=30&allow_empty=1"
    )

    assert resp.status_code == 200
    assert resp.get_json()["code"] == "0"
    assert seen == [{"days": 30, "allow_empty": True}]


def test_sync_must_pool_empty_group_returns_400(route_app, monkeypatch):
    service = _FakeStockService(
        fail_with=_FakeStockService.TdxEmptyGroupError("empty"),
        seen=[],
    )
    monkeypatch.setattr(stock_routes, "_get_stock_service", lambda: service)

    resp = route_app.test_client().post("/api/pools/must/sync-from-tdx")

    assert resp.status_code == 400
    assert resp.get_json()["code"] == "empty_group"
    assert service.seen == [{"days": 30, "allow_empty": False}]


def test_sync_must_pool_other_error_keeps_500(route_app, monkeypatch):
    service = _FakeStockService(
        fail_with=RuntimeError("boom"),
        seen=[],
    )
    monkeypatch.setattr(stock_routes, "_get_stock_service", lambda: service)

    resp = route_app.test_client().post("/api/pools/must/sync-from-tdx")

    assert resp.status_code == 500
    assert resp.get_json()["code"] == "1"
