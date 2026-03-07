import json

from flask import Flask

from freshquant.rear.tpsl.routes import tpsl_bp


class FakeTpslService:
    def __init__(self):
        self.calls = []

    def get_takeprofit_profile(self, symbol):
        self.calls.append(("get_takeprofit_profile", symbol))
        return {
            "symbol": symbol,
            "tiers": [
                {"level": 1, "price": 10.0, "manual_enabled": True},
                {"level": 2, "price": 11.0, "manual_enabled": False},
                {"level": 3, "price": 11.5, "manual_enabled": True},
            ],
            "state": {"armed_levels": {1: True, 2: False, 3: True}},
        }

    def save_takeprofit_profile(self, symbol, *, tiers, updated_by):
        self.calls.append(("save_takeprofit_profile", symbol, tiers, updated_by))
        return {"symbol": symbol, "tiers": tiers}

    def set_takeprofit_tier_enabled(self, symbol, *, level, enabled, updated_by):
        self.calls.append(
            ("set_takeprofit_tier_enabled", symbol, level, enabled, updated_by)
        )
        return {
            "symbol": symbol,
            "tiers": [
                {"level": level, "price": 10.0 + level, "manual_enabled": enabled}
            ],
        }

    def rearm_takeprofit(self, symbol, *, updated_by):
        self.calls.append(("rearm_takeprofit", symbol, updated_by))
        return {
            "symbol": symbol,
            "armed_levels": {1: True, 2: True, 3: True},
        }

    def list_events(self, *, symbol=None, limit=50):
        self.calls.append(("list_events", symbol, limit))
        return [{"event_id": "evt_1", "symbol": symbol or "000001"}]

    def get_batch_events(self, batch_id):
        self.calls.append(("get_batch_events", batch_id))
        return [{"event_id": "evt_1", "batch_id": batch_id}]


def _build_client(monkeypatch, service):
    monkeypatch.setattr(
        "freshquant.rear.tpsl.routes._get_tpsl_service",
        lambda: service,
    )
    app = Flask("tpsl")
    app.register_blueprint(tpsl_bp)
    return app.test_client()


def test_takeprofit_profile_route_reads_profile(monkeypatch):
    service = FakeTpslService()
    client = _build_client(monkeypatch, service)

    response = client.get("/api/tpsl/takeprofit/000001")

    assert response.status_code == 200
    assert response.get_json()["symbol"] == "000001"


def test_takeprofit_tier_enable_route_updates_manual_enabled(monkeypatch):
    service = FakeTpslService()
    client = _build_client(monkeypatch, service)

    response = client.post(
        "/api/tpsl/takeprofit/000001/tiers/2/enable",
        data=json.dumps({"updated_by": "api"}),
        content_type="application/json",
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["tiers"][0]["manual_enabled"] is True


def test_tpsl_events_route_returns_audit_rows(monkeypatch):
    service = FakeTpslService()
    client = _build_client(monkeypatch, service)

    response = client.get("/api/tpsl/events?symbol=000001&limit=20")

    assert response.status_code == 200
    assert response.get_json()[0]["event_id"] == "evt_1"


def test_tpsl_batch_route_returns_batch_events(monkeypatch):
    service = FakeTpslService()
    client = _build_client(monkeypatch, service)

    response = client.get("/api/tpsl/batches/tp_batch_1")

    assert response.status_code == 200
    assert response.get_json()[0]["batch_id"] == "tp_batch_1"
