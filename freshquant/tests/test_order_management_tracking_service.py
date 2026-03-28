from freshquant.order_management.tracking.service import OrderTrackingService
from freshquant.order_management.tracking.state_machine import (
    InvalidOrderTransition,
    OrderStateMachine,
)


class InMemoryRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.broker_orders = []
        self.order_events = []
        self.trade_facts = []
        self.execution_fills = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def upsert_broker_order(self, document, unique_keys):
        for existing in self.broker_orders:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                existing.update(document)
                return existing, False
        saved = dict(document)
        self.broker_orders.append(saved)
        return saved, True

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def upsert_execution_fill(self, document, unique_keys):
        for existing in self.execution_fills:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        saved = dict(document)
        self.execution_fills.append(saved)
        return saved, True

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
                return order
        return None

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
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
    assert repository.broker_orders[0]["internal_order_id"] == repository.orders[0][
        "internal_order_id"
    ]
    assert repository.broker_orders[0]["requested_quantity"] == 100
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


def test_ingest_trade_report_preserves_date_and_time_fields():
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
        "broker_trade_id": "T-002",
        "symbol": "000001",
        "side": "buy",
        "quantity": 100,
        "price": 12.30,
        "trade_time": 1710000000,
        "date": 20240309,
        "time": "09:31:00",
        "source": "xt_trade_callback",
    }

    created = service.ingest_trade_report(report)

    assert created["date"] == 20240309
    assert created["time"] == "09:31:00"


def test_ingest_trade_report_with_meta_returns_created_flag():
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
        "broker_trade_id": "T-003",
        "symbol": "000001",
        "side": "buy",
        "quantity": 100,
        "price": 12.30,
        "trade_time": 1710000000,
        "source": "xt_trade_callback",
    }

    first = service.ingest_trade_report_with_meta(report)
    second = service.ingest_trade_report_with_meta(report)

    assert first["created"] is True
    assert second["created"] is False
    assert first["trade_fact"]["trade_fact_id"] == second["trade_fact"]["trade_fact_id"]


def test_ingest_trade_report_aggregates_execution_fills_into_one_broker_order():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 200,
            "source": "strategy",
            "internal_order_id": "ord_exec_agg_1",
        }
    )
    service.ingest_order_report(
        {
            "internal_order_id": "ord_exec_agg_1",
            "broker_order_id": "B-EXEC-1",
            "state": "QUEUED",
            "event_type": "xt_order_reported",
        }
    )

    first = service.ingest_trade_report_with_meta(
        {
            "internal_order_id": "ord_exec_agg_1",
            "broker_order_id": "B-EXEC-1",
            "broker_trade_id": "T-EXEC-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 12.30,
            "trade_time": 1710000000,
            "source": "xt_trade_callback",
        }
    )
    second = service.ingest_trade_report_with_meta(
        {
            "internal_order_id": "ord_exec_agg_1",
            "broker_order_id": "B-EXEC-1",
            "broker_trade_id": "T-EXEC-2",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 12.50,
            "trade_time": 1710000005,
            "source": "xt_trade_callback",
        }
    )

    assert first["created"] is True
    assert second["created"] is True
    assert len(repository.execution_fills) == 2
    aggregate = repository.find_broker_order("ord_exec_agg_1")
    assert aggregate["broker_order_id"] == "B-EXEC-1"
    assert aggregate["filled_quantity"] == 200
    assert aggregate["fill_count"] == 2
    assert aggregate["avg_filled_price"] == 12.4
    assert aggregate["first_fill_time"] == 1710000000
    assert aggregate["last_fill_time"] == 1710000005
    assert aggregate["state"] == "FILLED"
    assert repository.order_events[-1]["event_type"] == "trade_reported"
    assert repository.order_events[-1]["state"] == "FILLED"


def test_ingest_trade_report_duplicate_trade_does_not_double_count_broker_order():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_exec_dup_1",
        }
    )

    first = service.ingest_trade_report_with_meta(
        {
            "internal_order_id": "ord_exec_dup_1",
            "broker_trade_id": "T-DUP-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 12.30,
            "trade_time": 1710000000,
            "source": "xt_trade_callback",
        }
    )
    second = service.ingest_trade_report_with_meta(
        {
            "internal_order_id": "ord_exec_dup_1",
            "broker_trade_id": "T-DUP-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 12.30,
            "trade_time": 1710000000,
            "source": "xt_trade_callback",
        }
    )

    assert first["created"] is True
    assert second["created"] is False
    assert len(repository.execution_fills) == 1
    aggregate = repository.find_broker_order("ord_exec_dup_1")
    assert aggregate["filled_quantity"] == 100
    assert aggregate["fill_count"] == 1


def test_ingest_trade_report_keeps_known_orders_on_internal_broker_order_key():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_exec_alias_1",
        }
    )

    service.ingest_trade_report_with_meta(
        {
            "internal_order_id": "ord_exec_alias_1",
            "broker_order_key": "border_exec_alias_1",
            "broker_order_id": "B-EXEC-ALIAS-1",
            "broker_trade_id": "T-EXEC-ALIAS-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 12.30,
            "trade_time": 1710000010,
            "source": "xt_trade_callback",
        }
    )

    aggregate = repository.find_broker_order("ord_exec_alias_1")
    assert aggregate["internal_order_id"] == "ord_exec_alias_1"
    assert aggregate["broker_order_id"] == "B-EXEC-ALIAS-1"
    assert aggregate["state"] == "FILLED"
    assert repository.execution_fills[0]["broker_order_key"] == "ord_exec_alias_1"


def test_ingest_order_report_is_idempotent_when_state_is_unchanged():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_same_state_1",
        }
    )
    repository.update_order(
        "ord_same_state_1",
        {
            "state": "FILLED",
            "broker_order_id": "B-001",
        },
    )
    existing_event_count = len(repository.order_events)

    current_order = service.ingest_order_report(
        {
            "internal_order_id": "ord_same_state_1",
            "broker_order_id": "B-001",
            "state": "FILLED",
            "event_type": "xt_order_reported",
        }
    )

    assert current_order["state"] == "FILLED"
    assert len(repository.order_events) == existing_event_count


def test_ingest_order_report_syncs_broker_order_report_fields():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_sync_report_1",
        }
    )

    service.ingest_order_report(
        {
            "internal_order_id": "ord_sync_report_1",
            "broker_order_id": "B-SYNC-1",
            "submitted_at": "2026-03-28T09:31:00+00:00",
            "state": "QUEUED",
            "event_type": "xt_order_reported",
        }
    )

    aggregate = repository.find_broker_order("ord_sync_report_1")
    assert aggregate["broker_order_id"] == "B-SYNC-1"
    assert aggregate["submitted_at"] == "2026-03-28T09:31:00+00:00"
    assert aggregate["state"] == "QUEUED"


def test_ingest_order_report_absorbs_terminal_replay_snapshots():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_terminal_replay_1",
        }
    )
    repository.update_order(
        "ord_terminal_replay_1",
        {
            "state": "FILLED",
            "broker_order_id": "B-terminal-1",
        },
    )
    existing_event_count = len(repository.order_events)

    current_order = service.ingest_order_report(
        {
            "internal_order_id": "ord_terminal_replay_1",
            "broker_order_id": "B-terminal-1",
            "state": "CANCELED",
            "event_type": "xt_order_reported",
        }
    )

    assert current_order["state"] == "FILLED"
    assert len(repository.order_events) == existing_event_count


def test_order_state_machine_rejects_invalid_transition():
    state_machine = OrderStateMachine()

    try:
        state_machine.transition("ACCEPTED", "FILLED")
    except InvalidOrderTransition as error:
        assert "ACCEPTED" in str(error)
        assert "FILLED" in str(error)
    else:
        raise AssertionError("Expected InvalidOrderTransition")


def test_ingest_order_report_allows_broker_bypassed_transition():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_bypass_state_1",
        }
    )
    repository.update_order("ord_bypass_state_1", {"state": "SUBMITTING"})

    service.ingest_order_report(
        {
            "internal_order_id": "ord_bypass_state_1",
            "state": "BROKER_BYPASSED",
            "event_type": "broker_submit_bypassed",
        }
    )

    assert repository.find_order("ord_bypass_state_1")["state"] == "BROKER_BYPASSED"
    assert repository.order_events[-1]["event_type"] == "broker_submit_bypassed"


def test_cancel_order_allows_transition_from_broker_bypassed():
    repository = InMemoryRepository()
    service = OrderTrackingService(repository=repository)
    service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 12.34,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_bypass_cancel_1",
        }
    )
    repository.update_order("ord_bypass_cancel_1", {"state": "BROKER_BYPASSED"})

    service.cancel_order(
        {
            "internal_order_id": "ord_bypass_cancel_1",
            "source": "api",
        }
    )

    assert repository.find_order("ord_bypass_cancel_1")["state"] == "CANCEL_REQUESTED"
