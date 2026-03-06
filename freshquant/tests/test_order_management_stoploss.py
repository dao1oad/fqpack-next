import json

from flask import Flask

from freshquant.order_management.stoploss.service import BuyLotStoplossService
from freshquant.rear.order.routes import order_bp


class InMemoryRepository:
    def __init__(self):
        self.buy_lots = []
        self.stoploss_bindings = []

    def find_buy_lot(self, buy_lot_id):
        for item in self.buy_lots:
            if item["buy_lot_id"] == buy_lot_id:
                return item
        return None

    def replace_buy_lot(self, document):
        for index, item in enumerate(self.buy_lots):
            if item["buy_lot_id"] == document["buy_lot_id"]:
                self.buy_lots[index] = document
                return document
        self.buy_lots.append(document)
        return document

    def list_buy_lots(self, symbol=None):
        if symbol is None:
            return list(self.buy_lots)
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def upsert_stoploss_binding(self, document):
        for index, item in enumerate(self.stoploss_bindings):
            if item["buy_lot_id"] == document["buy_lot_id"]:
                self.stoploss_bindings[index] = {**item, **document}
                return self.stoploss_bindings[index]
        self.stoploss_bindings.append(document)
        return document

    def find_stoploss_binding(self, buy_lot_id):
        for item in self.stoploss_bindings:
            if item["buy_lot_id"] == buy_lot_id:
                return item
        return None


def _build_service():
    repository = InMemoryRepository()
    repository.replace_buy_lot(
        {
            "buy_lot_id": "lot_1",
            "symbol": "000001",
            "buy_price_real": 10.0,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "status": "partial",
            "sell_history": [
                {
                    "allocation_id": "alloc_1",
                    "allocated_quantity": 100,
                    "sell_trade_fact_id": "trade_sell_1",
                }
            ],
        }
    )
    return repository, BuyLotStoplossService(repository=repository)


def test_stoploss_binds_to_buy_lot_not_projection_row():
    repository, service = _build_service()

    binding = service.bind_stoploss("lot_1", stop_price=9.2, ratio=None, enabled=True)

    assert binding["buy_lot_id"] == "lot_1"
    assert binding["symbol"] == "000001"
    assert "fill_id" not in binding
    assert repository.find_stoploss_binding("lot_1")["state"] == "active"


def test_stoploss_only_acts_on_remaining_quantity_of_partially_sold_lot():
    _, service = _build_service()
    service.bind_stoploss("lot_1", stop_price=9.2, ratio=None, enabled=True)

    requests = service.evaluate_stoploss("000001", price=9.1)

    assert len(requests) == 1
    assert requests[0]["quantity"] == 200
    assert requests[0]["scope_type"] == "buy_lot"
    assert requests[0]["scope_ref_id"] == "lot_1"


def test_buy_lot_detail_returns_sell_history_and_stoploss_state():
    _, service = _build_service()
    service.bind_stoploss("lot_1", stop_price=9.2, ratio=0.08, enabled=True)

    detail = service.get_buy_lot_detail("lot_1")

    assert detail["buy_lot_id"] == "lot_1"
    assert detail["remaining_quantity"] == 200
    assert len(detail["sell_history"]) == 1
    assert detail["stoploss"]["stop_price"] == 9.2


def test_buy_lot_detail_api_returns_stoploss_and_sell_history(monkeypatch):
    _, service = _build_service()
    service.bind_stoploss("lot_1", stop_price=9.2, ratio=None, enabled=True)
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_stoploss_service",
        lambda: service,
    )

    app = Flask("test_order_stoploss_api")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.get("/api/order-management/buy-lots/lot_1")

    assert response.status_code == 200
    assert response.get_json()["buy_lot_id"] == "lot_1"


def test_stoploss_bind_api_uses_buy_lot_id(monkeypatch):
    _, service = _build_service()
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_stoploss_service",
        lambda: service,
    )

    app = Flask("test_order_stoploss_bind_api")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.post(
        "/api/order-management/stoploss/bind",
        data=json.dumps({"buy_lot_id": "lot_1", "stop_price": 9.2, "enabled": True}),
        content_type="application/json",
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["buy_lot_id"] == "lot_1"
    assert body["state"] == "active"
