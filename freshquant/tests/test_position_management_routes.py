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


def test_position_management_reconciliation_routes_forward_read_only_payload(
    monkeypatch,
):
    class FakeReadService:
        def get_overview(self):
            return {
                "summary": {
                    "row_count": 1,
                    "audit_status_counts": {"OK": 0, "WARN": 1, "ERROR": 0},
                    "rule_counts": {
                        "R1": {"OK": 1, "WARN": 0, "ERROR": 0},
                        "R2": {"OK": 1, "WARN": 0, "ERROR": 0},
                        "R3": {"OK": 0, "WARN": 1, "ERROR": 0},
                        "R4": {"OK": 0, "WARN": 1, "ERROR": 0},
                    },
                    "reconciliation_state_counts": {
                        "ALIGNED": 0,
                        "OBSERVING": 1,
                        "AUTO_RECONCILED": 0,
                        "BROKEN": 0,
                        "DRIFT": 0,
                    },
                },
                "rows": [
                    {
                        "symbol": "600000",
                        "audit_status": "WARN",
                        "surface_values": {
                            "broker": {"quantity": 1200},
                        },
                        "rule_results": {
                            "R4": {"status": "WARN"},
                        },
                        "evidence_sections": {
                            "surfaces": [{"key": "broker"}],
                            "rules": [{"id": "R4"}],
                            "reconciliation": {"state": "OBSERVING"},
                        },
                    }
                ],
            }

        def get_symbol_detail(self, symbol):
            return {
                "symbol": symbol,
                "audit_status": "WARN",
                "reconciliation": {"state": "OBSERVING"},
                "surface_values": {
                    "broker": {"quantity": 1200},
                },
                "rule_results": {
                    "R4": {"status": "WARN"},
                },
                "evidence_sections": {
                    "surfaces": [{"key": "broker"}],
                    "rules": [{"id": "R4"}],
                    "reconciliation": {"state": "OBSERVING"},
                },
            }

        def get_symbol_workspace(self, symbol):
            return {
                "detail": {
                    "symbol": symbol,
                    "audit_status": "WARN",
                },
                "gaps": [{"gap_id": "gap_1", "state": "OPEN"}],
                "resolutions": [
                    {
                        "resolution_id": "resolution_1",
                        "gap_id": "gap_1",
                        "resolution_type": "auto_open_entry",
                    }
                ],
                "rejections": [
                    {
                        "rejection_id": "rejection_1",
                        "reason_code": "non_board_lot_quantity",
                    }
                ],
            }

    monkeypatch.setattr(
        "freshquant.rear.position_management.routes._get_position_reconciliation_read_service",
        lambda: FakeReadService(),
    )

    client = _make_client()
    list_response = client.get("/api/position-management/reconciliation")
    detail_response = client.get("/api/position-management/reconciliation/600000")
    workspace_response = client.get(
        "/api/position-management/reconciliation-workspace/600000"
    )

    assert list_response.status_code == 200
    assert list_response.get_json()["summary"]["row_count"] == 1
    assert list_response.get_json()["summary"]["rule_counts"]["R4"]["WARN"] == 1
    assert list_response.get_json()["rows"][0]["audit_status"] == "WARN"
    assert (
        list_response.get_json()["rows"][0]["surface_values"]["broker"]["quantity"]
        == 1200
    )
    assert (
        list_response.get_json()["rows"][0]["evidence_sections"]["surfaces"][0]["key"]
        == "broker"
    )
    assert detail_response.status_code == 200
    assert detail_response.get_json()["symbol"] == "600000"
    assert detail_response.get_json()["reconciliation"]["state"] == "OBSERVING"
    assert detail_response.get_json()["rule_results"]["R4"]["status"] == "WARN"
    assert (
        detail_response.get_json()["evidence_sections"]["reconciliation"]["state"]
        == "OBSERVING"
    )
    assert workspace_response.status_code == 200
    assert workspace_response.get_json()["detail"]["symbol"] == "600000"
    assert workspace_response.get_json()["gaps"][0]["gap_id"] == "gap_1"
    assert (
        workspace_response.get_json()["resolutions"][0]["resolution_type"]
        == "auto_open_entry"
    )
    assert (
        workspace_response.get_json()["rejections"][0]["reason_code"]
        == "non_board_lot_quantity"
    )


def test_position_management_reconciliation_detail_route_returns_404_on_missing_symbol(
    monkeypatch,
):
    class FakeReadService:
        def get_symbol_detail(self, symbol):
            raise ValueError(f"{symbol} not found")

    monkeypatch.setattr(
        "freshquant.rear.position_management.routes._get_position_reconciliation_read_service",
        lambda: FakeReadService(),
    )

    client = _make_client()
    response = client.get("/api/position-management/reconciliation/600000")

    assert response.status_code == 404
    assert response.get_json()["error"] == "600000 not found"
