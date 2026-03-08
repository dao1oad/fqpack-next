from freshquant.carnation import xtconstant
from freshquant.order_management.submit.execution_bridge import (
    dispatch_cancel_execution,
    finalize_submit_execution,
    prepare_submit_execution,
)
from freshquant.order_management.tracking.service import OrderTrackingService


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

    def find_order_by_broker_order_id(self, broker_order_id):
        for order in self.orders:
            if str(order.get("broker_order_id")) == str(broker_order_id):
                return order
        return None

    def update_order(self, internal_order_id, updates):
        order = self.find_order(internal_order_id)
        if order is None:
            return None
        order.update(updates)
        return order


def test_prepare_submit_execution_skips_canceled_order_before_submit():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_skip_1",
        }
    )
    repository.update_order("ord_skip_1", {"state": "CANCEL_REQUESTED"})

    result = prepare_submit_execution(
        {"internal_order_id": "ord_skip_1", "action": "buy"},
        repository=repository,
        tracking_service=tracking_service,
    )

    assert result["status"] == "skipped"
    assert repository.find_order("ord_skip_1")["state"] == "CANCELED"


def test_finalize_submit_execution_marks_order_submitted_with_broker_order_id():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_submit_1",
        }
    )
    repository.update_order("ord_submit_1", {"state": "SUBMITTING"})

    finalize_submit_execution(
        {"internal_order_id": "ord_submit_1"},
        broker_order_id=123456,
        repository=repository,
        tracking_service=tracking_service,
    )

    order = repository.find_order("ord_submit_1")
    assert order["state"] == "SUBMITTED"
    assert order["broker_order_id"] == "123456"


def test_dispatch_cancel_execution_cancels_locally_when_broker_order_missing():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_cancel_1",
        }
    )
    repository.update_order("ord_cancel_1", {"state": "CANCEL_REQUESTED"})

    result = dispatch_cancel_execution(
        {"internal_order_id": "ord_cancel_1", "action": "cancel"},
        cancel_executor=lambda broker_order_id: 0,
        repository=repository,
        tracking_service=tracking_service,
    )

    assert result["status"] == "canceled_before_submit"
    assert repository.find_order("ord_cancel_1")["state"] == "CANCELED"


def test_dispatch_cancel_execution_is_idempotent_for_already_canceled_order():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_cancel_2",
        }
    )
    repository.update_order("ord_cancel_2", {"state": "CANCELED"})

    result = dispatch_cancel_execution(
        {"internal_order_id": "ord_cancel_2", "action": "cancel"},
        cancel_executor=lambda broker_order_id: 0,
        repository=repository,
        tracking_service=tracking_service,
    )

    assert result["status"] == "already_canceled"
    assert repository.find_order("ord_cancel_2")["state"] == "CANCELED"


def test_prepare_submit_execution_resolves_credit_sell_order_before_submit():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_runtime_sell_1",
            "account_type": "CREDIT",
            "credit_trade_mode": "auto",
            "price_mode": "auto",
        }
    )
    repository.update_order(
        "ord_runtime_sell_1",
        {
            "state": "QUEUED",
            "account_type": "CREDIT",
            "credit_trade_mode_requested": "auto",
            "price_mode_requested": "auto",
        },
    )

    result = prepare_submit_execution(
        {
            "internal_order_id": "ord_runtime_sell_1",
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
        },
        repository=repository,
        tracking_service=tracking_service,
        credit_detail_loader=lambda: {"m_dAvailable": 10001, "m_dFinDebt": 1},
        continuous_auction_provider=lambda: True,
    )

    order = repository.find_order("ord_runtime_sell_1")
    assert result["status"] == "execute"
    assert (
        result["order_message"]["broker_order_type"]
        == xtconstant.CREDIT_SELL_SECU_REPAY
    )
    assert (
        result["order_message"]["broker_price_type"]
        == xtconstant.MARKET_SH_CONVERT_5_CANCEL
    )
    assert result["order_message"]["price"] == 9.92
    assert order["broker_order_type"] == xtconstant.CREDIT_SELL_SECU_REPAY
    assert order["broker_price_type"] == xtconstant.MARKET_SH_CONVERT_5_CANCEL
