import json

from flask import Flask


def _make_client():
    from freshquant.rear.subject_management.routes import subject_management_bp

    app = Flask("test_subject_management_routes")
    app.register_blueprint(subject_management_bp)
    return app.test_client()


def test_subject_management_overview_route_returns_rows(monkeypatch):
    class FakeDashboardService:
        def get_overview(self):
            return [{"symbol": "600000", "name": "浦发银行"}]

    monkeypatch.setattr(
        "freshquant.rear.subject_management.routes._get_dashboard_service",
        lambda: FakeDashboardService(),
    )

    client = _make_client()
    response = client.get("/api/subject-management/overview")

    assert response.status_code == 200
    assert response.get_json()["rows"][0]["symbol"] == "600000"


def test_subject_management_detail_route_returns_detail(monkeypatch):
    class FakeDashboardService:
        def get_detail(self, symbol):
            return {
                "subject": {"symbol": symbol, "name": "浦发银行"},
                "must_pool": {"lot_amount": 50000},
            }

    monkeypatch.setattr(
        "freshquant.rear.subject_management.routes._get_dashboard_service",
        lambda: FakeDashboardService(),
    )

    client = _make_client()
    response = client.get("/api/subject-management/600000")

    assert response.status_code == 200
    assert response.get_json()["subject"]["symbol"] == "600000"


def test_subject_management_must_pool_route_updates_subject_config(monkeypatch):
    captured = {}

    class FakeWriteService:
        def update_must_pool(self, symbol, payload):
            captured["call"] = (symbol, payload)
            return {"symbol": symbol, **payload}

    monkeypatch.setattr(
        "freshquant.rear.subject_management.routes._get_write_service",
        lambda: FakeWriteService(),
    )

    client = _make_client()
    response = client.post(
        "/api/subject-management/600000/must-pool",
        data=json.dumps(
            {
                "category": "银行",
                "stop_loss_price": 9.2,
                "initial_lot_amount": 80000,
                "lot_amount": 50000,
                "forever": True,
                "updated_by": "pytest",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert captured["call"] == (
        "600000",
        {
            "category": "银行",
            "stop_loss_price": 9.2,
            "initial_lot_amount": 80000,
            "lot_amount": 50000,
            "forever": True,
            "updated_by": "pytest",
        },
    )


def test_subject_management_guardian_route_returns_400_for_validation_error(
    monkeypatch,
):
    class FakeWriteService:
        def update_guardian_buy_grid(self, symbol, payload):
            raise ValueError("buy_1 must be numeric")

    monkeypatch.setattr(
        "freshquant.rear.subject_management.routes._get_write_service",
        lambda: FakeWriteService(),
    )

    client = _make_client()
    response = client.post(
        "/api/subject-management/600000/guardian-buy-grid",
        data=json.dumps({"buy_1": "bad"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "buy_1 must be numeric"
