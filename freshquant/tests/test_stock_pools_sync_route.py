# -*- coding: utf-8 -*-

"""#589：/api/pools/must/sync-from-tdx allow_empty 透传与 empty_group 400 响应测试。"""

import sys

import pytest
from flask import Flask


def _load_stock_routes():
    """惰性导入 rear.stock.routes，避免集合期被既有模块级 stub 污染。

    guardian 测试文件曾在本文件集合前把 ``freshquant.data.astock.holding``
    替换为 stub（无 get_stock_fills）；该行为已改为用后恢复的 fixture，此处的
    防御逻辑保留：若仍探测到 stub，临时恢复真实 holding 完成导入后还原。
    """

    holding = sys.modules.get("freshquant.data.astock.holding")
    restore = holding is not None and not hasattr(holding, "get_stock_fills")
    if restore:
        sys.modules.pop("freshquant.data.astock.holding", None)
    try:
        from freshquant.rear.stock import routes as stock_routes
    finally:
        if restore:
            sys.modules["freshquant.data.astock.holding"] = holding
    return stock_routes


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
    app.register_blueprint(_load_stock_routes().stock_bp)
    app.testing = True
    return app


def test_sync_must_pool_allow_empty_passthrough(route_app, monkeypatch):
    seen = []
    monkeypatch.setattr(
        _load_stock_routes(),
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
    monkeypatch.setattr(_load_stock_routes(), "_get_stock_service", lambda: service)

    resp = route_app.test_client().post("/api/pools/must/sync-from-tdx")

    assert resp.status_code == 400
    assert resp.get_json()["code"] == "empty_group"
    assert service.seen == [{"days": 30, "allow_empty": False}]


def test_sync_must_pool_other_error_keeps_500(route_app, monkeypatch):
    service = _FakeStockService(
        fail_with=RuntimeError("boom"),
        seen=[],
    )
    monkeypatch.setattr(_load_stock_routes(), "_get_stock_service", lambda: service)

    resp = route_app.test_client().post("/api/pools/must/sync-from-tdx")

    assert resp.status_code == 500
    assert resp.get_json()["code"] == "1"
