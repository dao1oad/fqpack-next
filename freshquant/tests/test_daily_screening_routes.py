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


def test_daily_screening_schema_route_returns_schema(monkeypatch):
    class FakeService:
        def get_schema(self):
            return {"models": [{"id": "clxs"}], "options": {"pre_pool_categories": []}}

    client = _make_client(monkeypatch, FakeService())
    response = client.get("/api/daily-screening/schema")

    assert response.status_code == 200
    assert response.get_json()["models"] == [{"id": "clxs"}]


def test_daily_screening_runs_route_starts_scan(monkeypatch):
    captured = {}

    class FakeService:
        def start_run(self, payload, run_async=True):
            captured["call"] = (payload, run_async)
            return {"id": "run-1", "status": "queued"}

    client = _make_client(monkeypatch, FakeService())
    response = client.post(
        "/api/daily-screening/runs",
        data=json.dumps({"model": "clxs", "days": 1}),
        content_type="application/json",
    )

    assert response.status_code == 202
    assert captured["call"] == ({"model": "clxs", "days": 1}, True)
    assert response.get_json()["run"]["id"] == "run-1"


def test_daily_screening_stream_route_returns_sse(monkeypatch):
    class FakeService:
        def get_run(self, run_id):
            assert run_id == "run-1"
            return {"id": run_id, "status": "running", "event_count": 1}

        def iter_sse(self, run_id, *, after=0, once=False):
            assert run_id == "run-1"
            assert after == 0
            assert once is True
            yield 'id: 1\nevent: started\ndata: {"seq": 1}\n\n'

    client = _make_client(monkeypatch, FakeService())
    response = client.get("/api/daily-screening/runs/run-1/stream?once=1")

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert 'event: started' in response.get_data(as_text=True)


def test_daily_screening_stream_route_uses_last_event_id_header(monkeypatch):
    class FakeService:
        def get_run(self, run_id):
            assert run_id == "run-1"
            return {"id": run_id, "status": "running", "event_count": 4}

        def iter_sse(self, run_id, *, after=0, once=False):
            assert run_id == "run-1"
            assert after == 3
            assert once is False
            yield 'id: 4\nevent: progress\ndata: {"seq": 4}\n\n'

    client = _make_client(monkeypatch, FakeService())
    response = client.get(
        "/api/daily-screening/runs/run-1/stream",
        headers={"Last-Event-ID": "3"},
    )

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert 'event: progress' in response.get_data(as_text=True)


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
            return {"run_id": run_id, "scope": run_id, "rows": [{"code": "000001"}], "total": 1}

        def get_stock_detail(self, run_id, code):
            captured["detail"] = (run_id, code)
            return {"run_id": run_id, "scope": run_id, "snapshot": {"code": code}, "memberships": []}

        def add_to_pre_pool(self, payload):
            captured["add_to_pre_pool"] = payload
            return {"code": "000001", "category": "CLXS_10001", "remark": "daily-screening:clxs"}

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
                "run_id": "trade_date:2026-03-18",
                "selected_sets": ["clxs", "chanlun"],
            }
        ),
        content_type="application/json",
    )
    detail_response = client.get(
        "/api/daily-screening/stocks/000001/detail?run_id=trade_date:2026-03-18"
    )
    add_to_pre_pool_response = client.post(
        "/api/daily-screening/actions/add-to-pre-pool",
        data=json.dumps({"run_id": "trade_date:2026-03-18", "code": "000001"}),
        content_type="application/json",
    )
    add_batch_to_pre_pool_response = client.post(
        "/api/daily-screening/actions/add-batch-to-pre-pool",
        data=json.dumps(
            {"run_id": "trade_date:2026-03-18", "selected_sets": ["clxs"]}
        ),
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
            "run_id": "trade_date:2026-03-18",
            "selected_sets": ["clxs", "chanlun"],
        },
    )

    assert detail_response.status_code == 200
    assert detail_response.get_json()["snapshot"]["code"] == "000001"
    assert captured["detail"] == ("trade_date:2026-03-18", "000001")

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
