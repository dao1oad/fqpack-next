from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.order_management.tracking.state_machine import (
    InvalidOrderTransition,
    OrderStateMachine,
)


class InMemoryRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.order_events = []
        self.trade_facts = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
                return order
        return None

    def update_order(self, internal_order_id, updates):
        order = self.find_order(internal_order_id)
        if order is None:
            return None
        order.update(updates)
        return order


def test_submit_order_creates_request_order_and_accepted_event():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)

    request_id = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "Guardian",
        }
    )

    assert request_id == repository.order_requests[0]["request_id"]
    assert repository.order_requests[0]["state"] == "ACCEPTED"
    assert repository.orders[0]["request_id"] == request_id
    assert repository.orders[0]["state"] == "ACCEPTED"
    assert repository.order_events[0]["event_type"] == "accepted"


def test_cancel_order_creates_cancel_request_and_event():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    request_id = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
        }
    )
    internal_order_id = repository.orders[0]["internal_order_id"]

    cancel_request_id = service.cancel_order(
        {
            "internal_order_id": internal_order_id,
            "source": "api",
            "request_id": request_id,
        }
    )

    assert cancel_request_id == repository.order_requests[-1]["request_id"]
    assert repository.order_requests[-1]["action"] == "cancel"
    assert repository.orders[0]["state"] == "CANCEL_REQUESTED"
    assert repository.order_events[-1]["event_type"] == "cancel_requested"


def test_ingest_trade_report_is_idempotent_by_broker_trade_id():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
        }
    )
    internal_order_id = repository.orders[0]["internal_order_id"]
    report = {
        "internal_order_id": internal_order_id,
        "broker_trade_id": "T-001",
        "symbol": "000001",
        "side": "buy",
        "quantity": 100,
        "price": 12.30,
        "trade_time": 1710000000,
        "source": "xt_trade_callback",
    }

    created_first = service.ingest_trade_report(report)
    created_second = service.ingest_trade_report(report)

    assert created_first["trade_fact_id"] == created_second["trade_fact_id"]
    assert len(repository.trade_facts) == 1


def test_order_state_machine_rejects_invalid_transition():
    state_machine = OrderStateMachine()

    try:
        state_machine.transition("ACCEPTED", "FILLED")
    except InvalidOrderTransition as error:
        assert "ACCEPTED" in str(error)
        assert "FILLED" in str(error)
    else:
        raise AssertionError("Expected InvalidOrderTransition")
