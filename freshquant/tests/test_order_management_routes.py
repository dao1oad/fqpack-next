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


def test_stock_order_compat_route_rejects_non_numeric_quantity(monkeypatch):
    class FakeService:
        def submit_order(self, payload):
            raise AssertionError("submit_order should not be called")

    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_submit_service",
        lambda: FakeService(),
    )

    app = Flask("test_order_routes_invalid_quantity")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.post(
        "/api/stock_order",
        data=json.dumps({"symbol": "sz000001", "quantity": "abc", "price": 10.1}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "quantity must be numeric"}


class FakeOrderManagementReadService:
    def __init__(self):
        self.calls = []

    def list_orders(self, **filters):
        self.calls.append(("list_orders", filters))
        return {
            "rows": [
                {
                    "internal_order_id": "ord_1",
                    "request_id": "req_1",
                    "symbol": "600000",
                    "side": "buy",
                    "state": "FILLED",
                    "strategy_name": "Guardian",
                }
            ],
            "total": 1,
            "page": filters["page"],
            "size": filters["size"],
        }

    def get_order_detail(self, internal_order_id):
        self.calls.append(("get_order_detail", internal_order_id))
        if internal_order_id == "missing":
            raise ValueError("order not found")
        return {
            "order": {
                "internal_order_id": internal_order_id,
                "request_id": "req_1",
                "symbol": "600000",
                "side": "buy",
                "state": "FILLED",
            },
            "request": {"request_id": "req_1", "source": "strategy"},
            "events": [{"event_id": "evt_1", "event_type": "accepted"}],
            "trades": [{"trade_fact_id": "trade_1"}],
            "identifiers": {"trace_id": "trc_1"},
        }

    def get_stats(self, **filters):
        self.calls.append(("get_stats", filters))
        return {
            "total": 2,
            "side_distribution": {"buy": 1, "sell": 1},
            "state_distribution": {"FILLED": 1, "QUEUED": 1},
            "missing_broker_order_count": 1,
            "latest_updated_at": "2026-03-13T10:05:00+00:00",
        }


def test_order_management_orders_route_returns_filtered_rows(monkeypatch):
    read_service = FakeOrderManagementReadService()
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_management_read_service",
        lambda: read_service,
    )

    app = Flask("test_order_management_orders_route")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.get(
        "/api/order-management/orders"
        "?symbol=600000&state=FILLED&strategy_name=Guardian&missing_broker_only=true&page=2&size=10"
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["rows"][0]["internal_order_id"] == "ord_1"
    assert read_service.calls[-1] == (
        "list_orders",
        {
            "symbol": "600000",
            "side": None,
            "state": "FILLED",
            "source": None,
            "strategy_name": "Guardian",
            "account_type": None,
            "internal_order_id": None,
            "request_id": None,
            "broker_order_id": None,
            "date_from": None,
            "date_to": None,
            "time_field": "updated_at",
            "missing_broker_only": True,
            "page": 2,
            "size": 10,
        },
    )


def test_order_management_detail_route_returns_404_for_missing_order(monkeypatch):
    read_service = FakeOrderManagementReadService()
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_management_read_service",
        lambda: read_service,
    )

    app = Flask("test_order_management_detail_route")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.get("/api/order-management/orders/missing")

    assert response.status_code == 404
    assert response.get_json()["error"] == "order not found"


def test_order_management_stats_route_returns_aggregated_counts(monkeypatch):
    read_service = FakeOrderManagementReadService()
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_management_read_service",
        lambda: read_service,
    )

    app = Flask("test_order_management_stats_route")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.get("/api/order-management/stats?symbol=600000&source=web")

    assert response.status_code == 200
    assert response.get_json()["missing_broker_order_count"] == 1
    assert read_service.calls[-1] == (
        "get_stats",
        {
            "symbol": "600000",
            "side": None,
            "state": None,
            "source": "web",
            "strategy_name": None,
            "account_type": None,
            "internal_order_id": None,
            "request_id": None,
            "broker_order_id": None,
            "date_from": None,
            "date_to": None,
            "time_field": "updated_at",
            "missing_broker_only": False,
        },
    )
