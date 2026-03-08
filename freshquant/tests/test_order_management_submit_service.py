from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.position_management.models import PositionDecision


class FakeQueueClient:
    def __init__(self):
        self.messages = []

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))
        return len(self.messages)


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

    def find_order_by_request_id(self, request_id):
        for order in self.orders:
            if order["request_id"] == request_id:
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


class AllowingPositionService:
    def evaluate_strategy_order(self, payload, is_profitable=False):
        return PositionDecision(
            allowed=True,
            state="ALLOW_OPEN",
            reason_code="buy_allowed",
            reason_text="当前状态允许策略买入",
            decision_id="pmd_test_allow",
        )


def test_submit_service_enqueues_buy_and_marks_order_queued():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=AllowingPositionService(),
        account_type_loader=lambda: "STOCK",
    )

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "sz000001",
            "price": 10.12,
            "quantity": 500,
            "source": "strategy",
            "strategy_name": "Guardian",
            "remark": "pytest",
        }
    )

    assert result["request_id"] == repository.order_requests[0]["request_id"]
    assert result["internal_order_id"] == repository.orders[0]["internal_order_id"]
    assert repository.orders[0]["state"] == "QUEUED"
    assert repository.order_events[-1]["event_type"] == "queued"
    assert queue_client.messages[0][0] == "freshquant_order_queue"
    assert '"internal_order_id"' in queue_client.messages[0][1]
    assert '"symbol": "000001"' in queue_client.messages[0][1]
    assert '"position_management_state": "ALLOW_OPEN"' in queue_client.messages[0][1]


def test_submit_service_enqueues_cancel_and_preserves_cancel_requested_state():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        account_type_loader=lambda: "STOCK",
    )
    create_result = service.submit_order(
        {
            "action": "sell",
            "symbol": "600000.SH",
            "price": 9.8,
            "quantity": 300,
            "source": "api",
        }
    )
    repository.update_order(
        create_result["internal_order_id"],
        {"state": "SUBMITTED", "broker_order_id": "90001"},
    )

    cancel_result = service.cancel_order(
        {
            "internal_order_id": create_result["internal_order_id"],
            "source": "api",
            "remark": "cancel pytest",
        }
    )

    assert cancel_result["request_id"] == repository.order_requests[-1]["request_id"]
    assert repository.orders[0]["state"] == "CANCEL_REQUESTED"
    assert repository.order_events[-1]["event_type"] == "cancel_queued"
    assert '"action": "cancel"' in queue_client.messages[-1][1]
    assert '"broker_order_id": "90001"' in queue_client.messages[-1][1]


def test_credit_buy_persists_resolved_credit_metadata_and_queue_payload():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=AllowingPositionService(),
        account_type_loader=lambda: "CREDIT",
        credit_subject_lookup=lambda _symbol: {"fin_status": 48},
        credit_subjects_available=lambda: True,
    )

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "600000.SH",
            "price": 10.0,
            "quantity": 300,
            "source": "api",
        }
    )

    assert repository.order_requests[0]["account_type"] == "CREDIT"
    assert repository.order_requests[0]["credit_trade_mode"] == "auto"
    assert repository.order_requests[0]["price_mode"] == "auto"
    assert repository.orders[0]["credit_trade_mode_requested"] == "auto"
    assert repository.orders[0]["credit_trade_mode_resolved"] == "finance_buy"
    assert repository.orders[0]["broker_order_type"] == 27
    assert result["queue_payload"]["account_type"] == "CREDIT"
    assert result["queue_payload"]["credit_trade_mode"] == "auto"
    assert result["queue_payload"]["credit_trade_mode_resolved"] == "finance_buy"
    assert result["queue_payload"]["broker_order_type"] == 27
