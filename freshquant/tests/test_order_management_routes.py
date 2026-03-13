import json

from bson import ObjectId
from flask import Flask

from freshquant.order_management.read_service import OrderManagementReadService
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


def test_order_management_routes_jsonify_sanitized_documents(monkeypatch):
    class Repository:
        def __init__(self):
            self.orders = [
                {
                    "_id": ObjectId(),
                    "internal_order_id": "ord_1",
                    "request_id": "req_1",
                    "symbol": "600000",
                    "side": "buy",
                    "state": "FILLED",
                    "source_type": "strategy",
                    "updated_at": "2026-03-13T09:05:00+00:00",
                }
            ]
            self.order_requests = [
                {
                    "_id": ObjectId(),
                    "request_id": "req_1",
                    "symbol": "600000",
                    "source": "strategy",
                    "strategy_name": "Guardian",
                    "created_at": "2026-03-13T09:00:00+00:00",
                }
            ]
            self.order_events = [
                {
                    "_id": ObjectId(),
                    "event_id": "evt_1",
                    "internal_order_id": "ord_1",
                    "event_type": "accepted",
                    "state": "ACCEPTED",
                    "created_at": "2026-03-13T09:00:00+00:00",
                }
            ]
            self.trade_facts = [
                {
                    "_id": ObjectId(),
                    "trade_fact_id": "trade_1",
                    "internal_order_id": "ord_1",
                    "symbol": "600000",
                    "quantity": 100,
                    "price": 10.1,
                    "trade_time": 1710311100,
                }
            ]

        def list_orders(self, **_kwargs):
            return list(self.orders)

        def find_order(self, internal_order_id):
            return next(
                (
                    item
                    for item in self.orders
                    if item.get("internal_order_id") == internal_order_id
                ),
                None,
            )

        def find_order_request(self, request_id):
            return next(
                (
                    item
                    for item in self.order_requests
                    if item.get("request_id") == request_id
                ),
                None,
            )

        def list_order_requests(self, **_kwargs):
            return list(self.order_requests)

        def list_order_events(self, *, internal_order_ids=None):
            return [
                item
                for item in self.order_events
                if internal_order_ids is None
                or item.get("internal_order_id") in set(internal_order_ids)
            ]

        def list_trade_facts(self, symbol=None, internal_order_ids=None):
            return [
                item
                for item in self.trade_facts
                if (symbol is None or item.get("symbol") == symbol)
                and (
                    internal_order_ids is None
                    or item.get("internal_order_id") in set(internal_order_ids)
                )
            ]

    read_service = OrderManagementReadService(repository=Repository())
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_order_management_read_service",
        lambda: read_service,
    )

    app = Flask("test_order_management_routes_sanitized_payloads")
    app.register_blueprint(order_bp)
    client = app.test_client()

    list_response = client.get("/api/order-management/orders?symbol=600000")
    detail_response = client.get("/api/order-management/orders/ord_1")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert "_id" not in list_response.get_json()["rows"][0]
    assert "_id" not in detail_response.get_json()["request"]
    assert "_id" not in detail_response.get_json()["events"][0]
    assert "_id" not in detail_response.get_json()["trades"][0]
