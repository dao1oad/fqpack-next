import json

from flask import Flask


def _make_client():
    from freshquant.rear.system_config.routes import system_config_bp

    app = Flask("test_system_config_routes")
    app.register_blueprint(system_config_bp)
    return app.test_client()


def test_system_config_dashboard_route_returns_service_payload(monkeypatch):
    class FakeService:
        def get_dashboard(self):
            return {
                "bootstrap": {
                    "file_path": "D:/fqpack/config/freshquant_bootstrap.yaml"
                },
                "settings": {"sections": [{"key": "guardian"}]},
            }

    monkeypatch.setattr(
        "freshquant.rear.system_config.routes._get_system_config_service",
        lambda: FakeService(),
    )

    client = _make_client()
    response = client.get("/api/system-config/dashboard")

    assert response.status_code == 200
    assert response.get_json()["bootstrap"]["file_path"].endswith(
        "freshquant_bootstrap.yaml"
    )


def test_system_config_update_routes_forward_payloads(monkeypatch):
    calls = []

    class FakeService:
        def update_bootstrap(self, payload):
            calls.append(("bootstrap", payload))
            return {"values": {"mongodb": {"host": payload["mongodb"]["host"]}}}

        def update_settings(self, payload):
            calls.append(("settings", payload))
            return {"values": {"xtquant": {"account": payload["xtquant"]["account"]}}}

    monkeypatch.setattr(
        "freshquant.rear.system_config.routes._get_system_config_service",
        lambda: FakeService(),
    )

    client = _make_client()
    bootstrap_response = client.post(
        "/api/system-config/bootstrap",
        data=json.dumps({"mongodb": {"host": "10.0.0.1"}}),
        content_type="application/json",
    )
    settings_response = client.post(
        "/api/system-config/settings",
        data=json.dumps({"xtquant": {"account": "068000076370"}}),
        content_type="application/json",
    )

    assert bootstrap_response.status_code == 200
    assert settings_response.status_code == 200
    assert calls == [
        ("bootstrap", {"mongodb": {"host": "10.0.0.1"}}),
        ("settings", {"xtquant": {"account": "068000076370"}}),
    ]


def test_system_config_update_routes_surface_validation_errors(monkeypatch):
    class FakeService:
        def update_bootstrap(self, payload):
            raise ValueError("mongodb.host is required")

        def update_settings(self, payload):
            raise ValueError("guardian.stock.lot_amount must be an integer")

    monkeypatch.setattr(
        "freshquant.rear.system_config.routes._get_system_config_service",
        lambda: FakeService(),
    )

    client = _make_client()
    bootstrap_response = client.post(
        "/api/system-config/bootstrap",
        data=json.dumps({"mongodb": {}}),
        content_type="application/json",
    )
    settings_response = client.post(
        "/api/system-config/settings",
        data=json.dumps({"guardian": {}}),
        content_type="application/json",
    )

    assert bootstrap_response.status_code == 400
    assert bootstrap_response.get_json()["error"] == "mongodb.host is required"
    assert settings_response.status_code == 400
    assert (
        settings_response.get_json()["error"]
        == "guardian.stock.lot_amount must be an integer"
    )
