import json

from flask import Flask


def _make_client(monkeypatch, fake_service):
    from freshquant.rear.daily_screening.routes import daily_screening_bp

    monkeypatch.setattr(
        "freshquant.rear.daily_screening.routes._get_daily_screening_service",
        lambda: fake_service,
    )
    app = Flask("test_daily_screening_routes")
    app.register_blueprint(daily_screening_bp)
    return app.test_client()


def test_daily_screening_schema_route_is_disabled(monkeypatch):
    client = _make_client(monkeypatch, object())
    response = client.get("/api/daily-screening/schema")

    assert response.status_code == 410
    assert "disabled" in response.get_json()["error"]


def test_daily_screening_runs_route_is_disabled(monkeypatch):
    client = _make_client(monkeypatch, object())
    response = client.post(
        "/api/daily-screening/runs",
        data=json.dumps({"model": "clxs", "days": 1}),
        content_type="application/json",
    )

    assert response.status_code == 410
    assert "Dagster" in response.get_json()["error"]


def test_daily_screening_run_detail_route_is_disabled(monkeypatch):
    client = _make_client(monkeypatch, object())
    response = client.get("/api/daily-screening/runs/run-1")

    assert response.status_code == 410
    assert "disabled" in response.get_json()["error"]


def test_daily_screening_stream_route_is_disabled(monkeypatch):
    client = _make_client(monkeypatch, object())
    response = client.get("/api/daily-screening/runs/run-1/stream?once=1")

    assert response.status_code == 410
    assert "SSE disabled" in response.get_json()["error"]


def test_daily_screening_pre_pools_routes_delegate_to_service(monkeypatch):
    captured = {}

    class FakeService:
        def list_pre_pools(self, **kwargs):
            captured["list"] = kwargs
            return {"rows": [{"code": "000001"}]}

        def add_pre_pool_to_stock_pool(self, payload):
            captured["add"] = payload
            return {"code": "000001", "category": "CLXS_10001"}

        def delete_pre_pool(self, payload):
            captured["delete"] = payload
            return {"deleted_count": 1}

    client = _make_client(monkeypatch, FakeService())

    list_response = client.get(
        "/api/daily-screening/pre-pools?remark=daily-screening:clxs&run_id=run-1&limit=20"
    )
    add_response = client.post(
        "/api/daily-screening/pre-pools/stock-pools",
        data=json.dumps(
            {
                "code": "000001",
                "category": "CLXS_10001",
                "remark": "daily-screening:clxs",
            }
        ),
        content_type="application/json",
    )
    delete_response = client.post(
        "/api/daily-screening/pre-pools/delete",
        data=json.dumps(
            {
                "code": "000001",
                "category": "CLXS_10001",
                "remark": "daily-screening:clxs",
            }
        ),
        content_type="application/json",
    )

    assert list_response.status_code == 200
    assert list_response.get_json()["rows"] == [{"code": "000001"}]
    assert captured["list"] == {
        "remark": "daily-screening:clxs",
        "category": None,
        "run_id": "run-1",
        "limit": 20,
    }
    assert add_response.status_code == 200
    assert captured["add"]["code"] == "000001"
    assert delete_response.status_code == 200
    assert captured["delete"]["remark"] == "daily-screening:clxs"


def test_daily_screening_filters_route_returns_catalog(monkeypatch):
    captured = {}

    class FakeService:
        def get_filter_catalog(self, scope_id):
            captured["scope_id"] = scope_id
            return {
                "scope_id": scope_id,
                "groups": {"hot_windows": []},
                "condition_keys": [],
            }

    client = _make_client(monkeypatch, FakeService())
    response = client.get("/api/daily-screening/filters?scope_id=trade_date:2026-03-18")

    assert response.status_code == 200
    assert response.get_json()["groups"] == {"hot_windows": []}
    assert captured["scope_id"] == "trade_date:2026-03-18"


def test_daily_screening_scope_query_routes_delegate_to_service(monkeypatch):
    captured = {}

    class FakeService:
        def get_scopes(self):
            captured["scopes"] = True
            return {
                "items": [
                    {
                        "run_id": "trade_date:2026-03-18",
                        "scope": "trade_date:2026-03-18",
                        "label": "正式 2026-03-18",
                        "is_latest": True,
                    }
                ]
            }

        def get_latest_scope(self):
            captured["latest"] = True
            return {
                "run_id": "trade_date:2026-03-18",
                "scope": "trade_date:2026-03-18",
                "label": "正式 2026-03-18",
                "is_latest": True,
            }

        def get_scope_summary(self, run_id):
            captured["summary"] = run_id
            return {"run_id": run_id, "scope": run_id, "stock_count": 1}

        def query_scope(self, run_id, payload):
            captured["query"] = (run_id, payload)
            return {
                "run_id": run_id,
                "scope": run_id,
                "rows": [{"code": "000001"}],
                "total": 1,
            }

        def get_stock_detail(self, run_id, code):
            captured["detail"] = (run_id, code)
            return {
                "run_id": run_id,
                "scope": run_id,
                "snapshot": {"code": code},
                "memberships": [],
            }

        def search_market_stocks(self, run_id, query, limit=20):
            captured["search"] = (run_id, query, limit)
            return {
                "scope_id": run_id,
                "query": query,
                "rows": [{"code": "600917", "name": "渝农商行"}],
                "total": 1,
            }

        def add_to_pre_pool(self, payload):
            captured["add_to_pre_pool"] = payload
            return {
                "code": "000001",
                "category": "CLXS_10001",
                "remark": "daily-screening:clxs",
            }

        def add_batch_to_pre_pool(self, payload):
            captured["add_batch_to_pre_pool"] = payload
            return {"created_count": 1, "codes": ["000001"]}

    client = _make_client(monkeypatch, FakeService())

    scopes_response = client.get("/api/daily-screening/scopes")
    latest_response = client.get("/api/daily-screening/scopes/latest")
    summary_response = client.get(
        "/api/daily-screening/scopes/trade_date:2026-03-18/summary"
    )
    query_response = client.post(
        "/api/daily-screening/query",
        data=json.dumps(
            {
                "scope_id": "trade_date:2026-03-18",
                "condition_keys": ["hot:30d"],
                "metric_filters": {"higher_multiple_lte": 2.5},
            }
        ),
        content_type="application/json",
    )
    detail_response = client.get(
        "/api/daily-screening/stocks/000001/detail?scope_id=trade_date:2026-03-18"
    )
    search_response = client.get(
        "/api/daily-screening/stocks/search?scope_id=trade_date:2026-03-18&q=600917&limit=8"
    )
    add_to_pre_pool_response = client.post(
        "/api/daily-screening/actions/add-to-pre-pool",
        data=json.dumps({"run_id": "trade_date:2026-03-18", "code": "000001"}),
        content_type="application/json",
    )
    add_batch_to_pre_pool_response = client.post(
        "/api/daily-screening/actions/add-batch-to-pre-pool",
        data=json.dumps({"run_id": "trade_date:2026-03-18", "selected_sets": ["clxs"]}),
        content_type="application/json",
    )

    assert scopes_response.status_code == 200
    assert scopes_response.get_json()["items"][0]["run_id"] == "trade_date:2026-03-18"
    assert captured["scopes"] is True

    assert latest_response.status_code == 200
    assert latest_response.get_json()["run_id"] == "trade_date:2026-03-18"
    assert captured["latest"] is True

    assert summary_response.status_code == 200
    assert summary_response.get_json()["scope"] == "trade_date:2026-03-18"
    assert captured["summary"] == "trade_date:2026-03-18"

    assert query_response.status_code == 200
    assert query_response.get_json()["rows"] == [{"code": "000001"}]
    assert captured["query"] == (
        "trade_date:2026-03-18",
        {
            "scope_id": "trade_date:2026-03-18",
            "condition_keys": ["hot:30d"],
            "metric_filters": {"higher_multiple_lte": 2.5},
        },
    )

    assert detail_response.status_code == 200
    assert detail_response.get_json()["snapshot"]["code"] == "000001"
    assert captured["detail"] == ("trade_date:2026-03-18", "000001")

    assert search_response.status_code == 200
    assert search_response.get_json()["rows"] == [{"code": "600917", "name": "渝农商行"}]
    assert captured["search"] == ("trade_date:2026-03-18", "600917", 8)

    assert add_to_pre_pool_response.status_code == 200
    assert add_to_pre_pool_response.get_json()["code"] == "000001"
    assert captured["add_to_pre_pool"] == {
        "run_id": "trade_date:2026-03-18",
        "code": "000001",
    }

    assert add_batch_to_pre_pool_response.status_code == 200
    assert add_batch_to_pre_pool_response.get_json()["codes"] == ["000001"]
    assert captured["add_batch_to_pre_pool"] == {
        "run_id": "trade_date:2026-03-18",
        "selected_sets": ["clxs"],
    }
