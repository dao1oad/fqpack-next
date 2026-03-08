# -*- coding: utf-8 -*-

import pytest

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.position_management.errors import PositionManagementRejectedError
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


class RejectingPositionService:
    def __init__(self):
        self.calls = []

    def evaluate_strategy_order(self, payload, is_profitable=False):
        self.calls.append((payload, is_profitable))
        return PositionDecision(
            allowed=False,
            state="HOLDING_ONLY",
            reason_code="new_position_blocked",
            reason_text="当前状态不允许开新仓",
            decision_id="pmd_reject_1",
        )


class AllowingPositionService:
    def __init__(self):
        self.calls = []

    def evaluate_strategy_order(self, payload, is_profitable=False):
        self.calls.append((payload, is_profitable))
        return PositionDecision(
            allowed=True,
            state="ALLOW_OPEN",
            reason_code="buy_allowed",
            reason_text="当前状态允许策略买入",
            decision_id="pmd_allow_1",
        )


def test_strategy_order_is_blocked_before_tracking_when_position_management_rejects():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    position_management_service = RejectingPositionService()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=position_management_service,
    )

    with pytest.raises(PositionManagementRejectedError):
        service.submit_order(
            {
                "action": "buy",
                "symbol": "000001",
                "price": 10.0,
                "quantity": 100,
                "source": "strategy",
            }
        )

    assert len(position_management_service.calls) == 1
    assert repository.order_requests == []
    assert queue_client.messages == []


def test_api_order_bypasses_position_management():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    position_management_service = RejectingPositionService()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=position_management_service,
    )

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
        }
    )

    assert result["internal_order_id"]
    assert position_management_service.calls == []
    assert len(queue_client.messages) == 1


def test_allowed_strategy_order_carries_position_management_summary_to_queue():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    position_management_service = AllowingPositionService()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=position_management_service,
    )

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "Guardian",
        }
    )

    assert result["queue_payload"]["position_management_state"] == "ALLOW_OPEN"
    assert result["queue_payload"]["position_management_decision_id"] == "pmd_allow_1"
    assert len(position_management_service.calls) == 1


def test_strategy_order_persists_strategy_context_to_tracking_and_queue():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    position_management_service = AllowingPositionService()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=position_management_service,
    )
    strategy_context = {
        "guardian_buy_grid": {
            "path": "holding_add",
            "grid_level": "BUY-3",
            "hit_levels": ["BUY-1", "BUY-2", "BUY-3"],
            "multiplier": 4,
        }
    }

    result = service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "Guardian",
            "strategy_context": strategy_context,
        }
    )

    assert repository.order_requests[0]["strategy_context"] == strategy_context
    assert result["queue_payload"]["strategy_context"] == strategy_context
