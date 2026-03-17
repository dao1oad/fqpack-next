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
            {"code": "000001", "category": "CLXS_10001", "remark": "daily-screening:clxs"}
        ),
        content_type="application/json",
    )
    delete_response = client.post(
        "/api/daily-screening/pre-pools/delete",
        data=json.dumps(
            {"code": "000001", "category": "CLXS_10001", "remark": "daily-screening:clxs"}
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
