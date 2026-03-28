import json

from flask import Flask

from freshquant.order_management.stoploss.service import EntryStoplossService
from freshquant.rear.order.routes import order_bp


class InMemoryRepository:
    def __init__(self):
        self.buy_lots = []
        self.position_entries = []
        self.entry_stoploss_bindings = []
        self.stoploss_bindings = []

    def find_position_entry(self, entry_id):
        for item in self.position_entries:
            if item["entry_id"] == entry_id:
                return item
        return None

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

    def replace_position_entry(self, document):
        for index, item in enumerate(self.position_entries):
            if item["entry_id"] == document["entry_id"]:
                self.position_entries[index] = document
                return document
        self.position_entries.append(document)
        return document

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        rows = list(self.position_entries)
        if symbol is not None:
            rows = [item for item in rows if item["symbol"] == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item["entry_id"] in allowed]
        if status is not None:
            rows = [item for item in rows if item.get("status") == status]
        return rows

    def list_buy_lots(self, symbol=None):
        if symbol is None:
            return list(self.buy_lots)
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def upsert_entry_stoploss_binding(self, document):
        for index, item in enumerate(self.entry_stoploss_bindings):
            if item["entry_id"] == document["entry_id"]:
                self.entry_stoploss_bindings[index] = {**item, **document}
                return self.entry_stoploss_bindings[index]
        self.entry_stoploss_bindings.append(document)
        return document

    def list_entry_stoploss_bindings(self, symbol=None, enabled=None):
        rows = list(self.entry_stoploss_bindings)
        if symbol is not None:
            rows = [item for item in rows if item["symbol"] == symbol]
        if enabled is not None:
            rows = [item for item in rows if bool(item.get("enabled")) == enabled]
        return rows

    def find_entry_stoploss_binding(self, entry_id):
        for item in self.entry_stoploss_bindings:
            if item["entry_id"] == entry_id:
                return item
        return None

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
    repository.replace_position_entry(
        {
            "entry_id": "entry_1",
            "symbol": "000001",
            "entry_price": 10.0,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "status": "PARTIALLY_EXITED",
            "sell_history": [
                {
                    "allocation_id": "ealloc_1",
                    "allocated_quantity": 100,
                }
            ],
        }
    )
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
    return repository, EntryStoplossService(repository=repository)


def test_stoploss_binds_to_entry_not_projection_row():
    repository, service = _build_service()

    binding = service.bind_stoploss("entry_1", stop_price=9.2, ratio=None, enabled=True)

    assert binding["entry_id"] == "entry_1"
    assert binding["symbol"] == "000001"
    assert "fill_id" not in binding
    assert repository.find_entry_stoploss_binding("entry_1")["state"] == "active"


def test_stoploss_only_acts_on_remaining_quantity_of_partially_sold_entry():
    _, service = _build_service()
    service.bind_stoploss("entry_1", stop_price=9.2, ratio=None, enabled=True)

    requests = service.evaluate_stoploss("000001", price=9.1)

    assert len(requests) == 1
    assert requests[0]["quantity"] == 200
    assert requests[0]["scope_type"] == "position_entry"
    assert requests[0]["scope_ref_id"] == "entry_1"


def test_entry_detail_returns_sell_history_and_stoploss_state():
    _, service = _build_service()
    service.bind_stoploss("entry_1", stop_price=9.2, ratio=0.08, enabled=True)

    detail = service.get_entry_detail("entry_1")

    assert detail["entry_id"] == "entry_1"
    assert detail["remaining_quantity"] == 200
    assert len(detail["sell_history"]) == 1
    assert detail["stoploss"]["stop_price"] == 9.2


def test_entry_detail_api_returns_stoploss_and_sell_history(monkeypatch):
    _, service = _build_service()
    service.bind_stoploss("entry_1", stop_price=9.2, ratio=None, enabled=True)
    monkeypatch.setattr(
        "freshquant.rear.order.routes._get_stoploss_service",
        lambda: service,
    )

    app = Flask("test_order_stoploss_api")
    app.register_blueprint(order_bp)
    client = app.test_client()

    response = client.get("/api/order-management/entries/entry_1")

    assert response.status_code == 200
    assert response.get_json()["entry_id"] == "entry_1"


def test_stoploss_bind_api_uses_entry_id(monkeypatch):
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
        data=json.dumps({"entry_id": "entry_1", "stop_price": 9.2, "enabled": True}),
        content_type="application/json",
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["entry_id"] == "entry_1"
    assert body["state"] == "active"


def test_legacy_buy_lot_is_exposed_as_compat_entry():
    _, service = _build_service()
    service.bind_stoploss("lot_1", stop_price=9.2, ratio=None, enabled=True)

    detail = service.get_entry_detail("lot_1")

    assert detail["entry_id"] == "lot_1"
    assert detail["entry_type"] == "legacy_buy_lot"
    assert detail["stoploss"]["entry_id"] == "lot_1"
