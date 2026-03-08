# -*- coding: utf-8 -*-

from datetime import datetime

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.position_management.models import FORCE_PROFIT_REDUCE, PositionDecision
from freshquant.position_management.service import PositionManagementService


class FakeDecisionRepository:
    def __init__(self, current_state=None):
        self.current_state = current_state
        self.decisions = []

    def get_current_state(self):
        return self.current_state

    def insert_decision(self, document):
        self.decisions.append(document)
        return document


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


class PlaceholderPositionService:
    def evaluate_strategy_order(self, payload, is_profitable=False):
        return PositionDecision(
            allowed=True,
            state=FORCE_PROFIT_REDUCE,
            reason_code="sell_allowed",
            reason_text="当前状态允许卖出持仓",
            decision_id="pmd_guardian_placeholder",
            meta={
                "force_profit_reduce": True,
                "profit_reduce_mode": "guardian_placeholder",
            },
        )


def _fixed_now():
    return datetime.fromisoformat("2026-03-07T12:00:00+08:00")


def test_force_profit_reduce_profitable_guardian_sell_marks_placeholder():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )

    decision = service.evaluate_strategy_order(
        payload={
            "source": "strategy",
            "strategy_name": "Guardian",
            "action": "sell",
            "symbol": "000001",
        },
        current_state={
            "state": FORCE_PROFIT_REDUCE,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
        is_profitable=True,
    )

    assert decision.allowed is True
    assert decision.meta["force_profit_reduce"] is True
    assert decision.meta["profit_reduce_mode"] == "guardian_placeholder"


def test_submit_service_carries_guardian_placeholder_meta_to_queue():
    repository = InMemoryRepository()
    queue_client = FakeQueueClient()
    service = OrderSubmitService(
        repository=repository,
        queue_client=queue_client,
        position_management_service=PlaceholderPositionService(),
        account_type_loader=lambda: "STOCK",
    )

    result = service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "Guardian",
        }
    )

    assert result["queue_payload"]["position_management_force_profit_reduce"] is True
    assert (
        result["queue_payload"]["position_management_profit_reduce_mode"]
        == "guardian_placeholder"
    )


def test_submit_service_marks_placeholder_for_guardian_strategy_identifier(
    monkeypatch,
):
    decision_repository = FakeDecisionRepository(
        current_state={
            "state": FORCE_PROFIT_REDUCE,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        }
    )
    position_service = PositionManagementService(
        repository=decision_repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )
    submit_service = OrderSubmitService(
        repository=InMemoryRepository(),
        queue_client=FakeQueueClient(),
        position_management_service=position_service,
        account_type_loader=lambda: "STOCK",
    )
    monkeypatch.setattr(
        "freshquant.position_management.service._resolve_guardian_strategy_identifier",
        lambda: "strategy::Guardian",
    )

    result = submit_service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "strategy::Guardian",
            "position_management_is_profitable": True,
        }
    )

    assert result["queue_payload"]["position_management_force_profit_reduce"] is True
    assert (
        result["queue_payload"]["position_management_profit_reduce_mode"]
        == "guardian_placeholder"
    )
