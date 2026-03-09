from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.position_management.models import PositionDecision


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


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
            decision_id="pmd_allow_1",
        )


def test_submit_order_emits_runtime_trace_steps():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    service = OrderSubmitService(
        repository=repository,
        queue_client=FakeQueueClient(),
        position_management_service=AllowingPositionService(),
        account_type_loader=lambda: "STOCK",
        runtime_logger=runtime_logger,
    )

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "Guardian",
            "trace_id": "trc_1",
            "intent_id": "int_1",
        }
    )

    nodes = [event["node"] for event in runtime_logger.events]
    assert nodes == [
        "intent_normalize",
        "credit_mode_resolve",
        "tracking_create",
        "queue_payload_build",
    ]
    assert runtime_logger.events[0]["trace_id"] == "trc_1"
    assert runtime_logger.events[0]["intent_id"] == "int_1"
    assert runtime_logger.events[2]["request_id"] == result["request_id"]
    assert runtime_logger.events[3]["internal_order_id"] == result["internal_order_id"]
