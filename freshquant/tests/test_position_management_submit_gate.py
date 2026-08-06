# -*- coding: utf-8 -*-

import pytest

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.position_management.errors import PositionManagementRejectedError
from freshquant.position_management.models import PositionDecision
from freshquant.position_management.service import PositionManagementService


class FakeQueueClient:
    def __init__(self):
        self.messages = []

    def lpush(self, queue_name, payload):
        self.messages.append((queue_name, payload))
        return len(self.messages)


class FakeRuntimeLogger:
    def emit(self, _event):
        return True


class InMemoryRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.broker_orders = []
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

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
                return order
        return None

    def claim_broker_order_owner(self, document):
        existing = self.find_broker_order(document["broker_order_key"])
        if existing is None:
            saved = dict(document)
            self.broker_orders.append(saved)
            return saved, True
        for field in (
            "internal_order_id",
            "request_id",
            "broker_correlation_token",
            "account_id",
            "trading_day",
            "order_sysid",
            "broker_order_id",
            "symbol",
            "side",
            "source_type",
        ):
            if field in document:
                existing[field] = document.get(field)
        return existing, False

    def update_broker_order_fields(self, broker_order_key, updates):
        order = self.find_broker_order(broker_order_key)
        if order is None:
            return None
        order.update(updates)
        return order

    def move_broker_order_key(self, old_key, new_key, document):
        order = self.find_broker_order(old_key)
        if order is None:
            order = dict(document)
            self.broker_orders.append(order)
        order.update(document)
        order["broker_order_key"] = new_key
        return order

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
        account_type_loader=lambda: "STOCK",
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
        account_type_loader=lambda: "STOCK",
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
        account_type_loader=lambda: "STOCK",
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
        account_type_loader=lambda: "STOCK",
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


def test_default_position_management_service_injects_symbol_position_loader(
    monkeypatch,
):
    import freshquant.order_management.submit.service as submit_service_module

    captured = {}

    class FakePositionManagementService:
        def __init__(
            self,
            repository=None,
            runtime_logger=None,
            symbol_position_loader=None,
        ):
            captured["repository"] = repository
            captured["runtime_logger"] = runtime_logger
            captured["symbol_position_loader"] = symbol_position_loader

    monkeypatch.setattr(
        "freshquant.position_management.service.PositionManagementService",
        FakePositionManagementService,
    )

    service = submit_service_module._load_position_management_service(
        runtime_logger="runtime-logger"
    )

    assert isinstance(service, FakePositionManagementService)
    assert captured["repository"] is not None
    assert captured["runtime_logger"] == "runtime-logger"
    assert callable(captured["symbol_position_loader"])


class FakePositionRepository:
    def __init__(self, *, limit=800000.0, snapshot=None):
        self.limit = limit
        self.snapshot = snapshot
        self.decisions = []

    def get_symbol_snapshot(self, _symbol):
        return self.snapshot

    def get_current_state(self):
        return {
            "state": "ALLOW_OPEN",
            "evaluated_at": "2099-03-22T10:00:00+08:00",
        }

    def get_config(self):
        return {
            "thresholds": {
                "single_symbol_position_limit": self.limit,
            }
        }

    def insert_decision(self, document):
        self.decisions.append(document)
        return document


class FakeXtPositionsCollection:
    def __init__(self, rows):
        self.rows = list(rows)

    def find(self, _query):
        return list(self.rows)


def _build_submit_service_with_default_position_loader(
    monkeypatch,
    *,
    xt_positions,
    limit,
    snapshot=None,
):
    import freshquant.order_management.submit.service as submit_service_module

    position_repository = FakePositionRepository(limit=limit, snapshot=snapshot)
    monkeypatch.setattr(
        "freshquant.position_management.repository.PositionManagementRepository",
        lambda: position_repository,
    )
    monkeypatch.setattr(
        "freshquant.position_management.service._default_holding_codes_provider",
        lambda: [],
    )
    monkeypatch.setattr(
        "freshquant.db.DBfreshquant",
        {"xt_positions": FakeXtPositionsCollection(xt_positions)},
    )
    runtime_logger = FakeRuntimeLogger()
    position_service = submit_service_module._load_position_management_service(
        runtime_logger=runtime_logger
    )
    submit_service = OrderSubmitService(
        repository=InMemoryRepository(),
        queue_client=FakeQueueClient(),
        position_management_service=position_service,
        account_type_loader=lambda: "STOCK",
        runtime_logger=runtime_logger,
    )
    return submit_service, position_repository


def test_default_submit_gate_prefers_persisted_symbol_snapshot(monkeypatch):
    service, position_repository = _build_submit_service_with_default_position_loader(
        monkeypatch,
        xt_positions=[],
        limit=2000.0,
        snapshot={
            "symbol": "000001",
            "market_value": 500.0,
            "market_value_source": "persisted_test_snapshot",
        },
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

    assert result["internal_order_id"]
    decision = position_repository.decisions[-1]
    assert decision["allowed"] is True
    assert decision["meta"]["symbol_market_value"] == 500.0
    assert decision["meta"]["symbol_market_value_source"] == "persisted_test_snapshot"
    assert decision["meta"]["projected_market_value"] == 1500.0


def test_default_submit_gate_allows_confirmed_empty_position_within_limit(
    monkeypatch,
):
    service, position_repository = _build_submit_service_with_default_position_loader(
        monkeypatch,
        xt_positions=[],
        limit=2000.0,
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

    assert result["internal_order_id"]
    decision = position_repository.decisions[-1]
    assert decision["allowed"] is True
    assert decision["meta"]["symbol_market_value"] == 0.0
    assert decision["meta"]["symbol_market_value_source"] == "no_broker_position"
    assert decision["meta"]["projected_market_value"] == 1000.0


def test_default_submit_gate_rejects_position_without_market_value(monkeypatch):
    service, position_repository = _build_submit_service_with_default_position_loader(
        monkeypatch,
        xt_positions=[{"symbol": "000001", "volume": 100}],
        limit=2000.0,
    )

    with pytest.raises(PositionManagementRejectedError):
        service.submit_order(
            {
                "action": "buy",
                "symbol": "000001",
                "price": 10.0,
                "quantity": 100,
                "source": "strategy",
                "strategy_name": "Guardian",
            }
        )

    decision = position_repository.decisions[-1]
    assert decision["allowed"] is False
    assert decision["reason_code"] == "symbol_position_unavailable"
    assert decision["meta"]["symbol_market_value"] is None
    assert decision["meta"]["symbol_market_value_source"] == "unavailable"


def test_default_submit_gate_rejects_projected_position_above_limit(monkeypatch):
    service, position_repository = _build_submit_service_with_default_position_loader(
        monkeypatch,
        xt_positions=[],
        limit=900.0,
    )

    with pytest.raises(PositionManagementRejectedError):
        service.submit_order(
            {
                "action": "buy",
                "symbol": "000001",
                "price": 10.0,
                "quantity": 100,
                "source": "strategy",
                "strategy_name": "Guardian",
            }
        )

    decision = position_repository.decisions[-1]
    assert decision["allowed"] is False
    assert decision["reason_code"] == "symbol_position_limit_blocked"
    assert decision["meta"]["symbol_market_value"] == 0.0
    assert decision["meta"]["projected_market_value"] == 1000.0


def test_position_gate_prefers_symbol_override_limit_over_default_limit():
    class FakeRepository:
        def __init__(self):
            self.decisions = []

        def get_current_state(self):
            return {
                "state": "ALLOW_OPEN",
                "evaluated_at": "2026-03-22T10:00:00+08:00",
            }

        def get_config(self):
            return {
                "thresholds": {
                    "single_symbol_position_limit": 800000.0,
                },
                "symbol_position_limits": {
                    "overrides": {
                        "600000": {
                            "limit": 500000.0,
                        }
                    }
                },
            }

        def insert_decision(self, document):
            self.decisions.append(document)
            return document

    repository = FakeRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: [],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 520000.0,
            "market_value_source": "xt_positions.market_value",
        },
    )

    decision = service.evaluate_strategy_order(
        {
            "action": "buy",
            "symbol": "600000",
            "source": "strategy",
        },
        current_state={
            "state": "ALLOW_OPEN",
            "evaluated_at": "2099-03-22T10:00:00+08:00",
        },
    )

    assert decision.allowed is False
    assert decision.reason_code == "symbol_position_limit_blocked"
    assert decision.meta["symbol_position_limit_default"] == 800000.0
    assert decision.meta["symbol_position_limit_override"] == 500000.0
    assert decision.meta["symbol_position_limit_effective"] == 500000.0
    assert decision.meta["symbol_position_limit_blocked"] is True
