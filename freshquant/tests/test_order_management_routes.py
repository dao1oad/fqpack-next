import json

from flask import Flask

from freshquant.rear.order.routes import order_bp


def test_stock_order_compat_route_translates_amount_to_buy_quantity(monkeypatch):
    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {"request_id": "req_1", "internal_order_id": "ord_1"}

    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_submit_service",
        lambda: FakeService(),
    )

    app = Flask("test_order_routes")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.post(
        "/api/stock_order",
        data=json.dumps({"symbol": "sz000001", "amount": 5100, "price": 10.1}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert captured["action"] == "buy"
    assert captured["symbol"] == "000001"
    assert captured["quantity"] == 500


def test_order_cancel_route_passes_internal_order_id(monkeypatch):
    captured = {}

    class FakeService:
        def cancel_order(self, payload):
            captured.update(payload)
            return {
                "request_id": "req_cancel_1",
                "internal_order_id": payload["internal_order_id"],
            }

    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_submit_service",
        lambda: FakeService(),
    )

    app = Flask("test_order_cancel_route")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.post(
        "/api/order/cancel",
        data=json.dumps({"internal_order_id": "ord_123", "remark": "pytest"}),
        content_type="application/json",
    )

    body = response.get_json()
    assert response.status_code == 200
    assert captured["internal_order_id"] == "ord_123"
    assert body["request_id"] == "req_cancel_1"
