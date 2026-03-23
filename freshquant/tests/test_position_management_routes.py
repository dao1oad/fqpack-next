import json

from flask import Flask


def _make_client():
    from freshquant.rear.position_management.routes import position_management_bp

    app = Flask("test_position_management_routes")
    app.register_blueprint(position_management_bp)
    return app.test_client()


def test_position_management_dashboard_route_returns_service_payload(monkeypatch):
    class FakeService:
        def get_dashboard(self):
            return {
                "state": {
                    "raw_state": "ALLOW_OPEN",
                    "effective_state": "ALLOW_OPEN",
                    "stale": False,
                },
                "rule_matrix": [{"key": "sell", "allowed": True}],
            }

    monkeypatch.setattr(
        "freshquant.rear.position_management.routes._get_position_management_dashboard_service",
        lambda: FakeService(),
    )

    client = _make_client()
    response = client.get("/api/position-management/dashboard")

    assert response.status_code == 200
    assert response.get_json()["state"]["effective_state"] == "ALLOW_OPEN"


def test_position_management_config_routes_forward_reads_and_validation_errors(
    monkeypatch,
):
    class FakeService:
        def get_config(self):
            return {
                "thresholds": {
                    "allow_open_min_bail": 800000.0,
                    "single_symbol_position_limit": 800000.0,
                }
            }

        def update_config(self, payload):
            raise ValueError(
                "allow_open_min_bail must be greater than holding_only_min_bail"
            )

    monkeypatch.setattr(
        "freshquant.rear.position_management.routes._get_position_management_dashboard_service",
        lambda: FakeService(),
    )

    client = _make_client()

    get_response = client.get("/api/position-management/config")
    post_response = client.post(
        "/api/position-management/config",
        data=json.dumps(
            {
                "allow_open_min_bail": 100000,
                "holding_only_min_bail": 200000,
                "single_symbol_position_limit": 800000,
            }
        ),
        content_type="application/json",
    )

    assert get_response.status_code == 200
    assert get_response.get_json()["thresholds"]["allow_open_min_bail"] == 800000.0
    assert (
        get_response.get_json()["thresholds"]["single_symbol_position_limit"]
        == 800000.0
    )
    assert post_response.status_code == 400
    assert (
        post_response.get_json()["error"]
        == "allow_open_min_bail must be greater than holding_only_min_bail"
    )


def test_position_management_symbol_limit_routes_forward_limit_only_payload(
    monkeypatch,
):
    captured = {}

    class FakeService:
        def get_symbol_limits(self):
            return {
                "rows": [
                    {
                        "symbol": "600000",
                        "effective_limit": 500000.0,
                    }
                ]
            }

        def get_symbol_limit(self, symbol):
            return {
                "symbol": symbol,
                "effective_limit": 500000.0,
            }

        def update_symbol_limit(self, symbol, payload):
            captured["call"] = (symbol, payload)
            return {
                "symbol": symbol,
                "effective_limit": payload.get("limit", 800000.0),
                "using_override": payload.get("limit") != 800000.0,
            }

    monkeypatch.setattr(
        "freshquant.rear.position_management.routes._get_position_management_dashboard_service",
        lambda: FakeService(),
    )

    client = _make_client()

    list_response = client.get("/api/position-management/symbol-limits")
    detail_response = client.get("/api/position-management/symbol-limits/600000")
    post_response = client.post(
        "/api/position-management/symbol-limits/600000",
        data=json.dumps({"limit": 500000, "updated_by": "pytest"}),
        content_type="application/json",
    )

    assert list_response.status_code == 200
    assert list_response.get_json()["rows"][0]["symbol"] == "600000"
    assert detail_response.status_code == 200
    assert detail_response.get_json()["effective_limit"] == 500000.0
    assert post_response.status_code == 200
    assert captured["call"] == (
        "600000",
        {"limit": 500000, "updated_by": "pytest"},
    )
