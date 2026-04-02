import sys
import types

import pytest

from freshquant.carnation import xtconstant
from freshquant.order_management.submit import execution_bridge
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


def test_finalize_submit_execution_marks_order_broker_bypassed_in_observe_only_mode():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_submit_bypass_1",
        }
    )
    repository.update_order("ord_submit_bypass_1", {"state": "SUBMITTING"})

    result = finalize_submit_execution(
        {"internal_order_id": "ord_submit_bypass_1"},
        broker_order_id=None,
        repository=repository,
        tracking_service=tracking_service,
        broker_submit_mode="observe_only",
    )

    order = repository.find_order("ord_submit_bypass_1")
    assert result["status"] == "broker_bypassed"
    assert order["state"] == "BROKER_BYPASSED"
    assert order["broker_order_id"] is None


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


def test_dispatch_cancel_execution_bypasses_broker_in_observe_only_mode():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_cancel_bypass_1",
        }
    )
    repository.update_order(
        "ord_cancel_bypass_1",
        {
            "state": "CANCEL_REQUESTED",
            "broker_order_id": None,
        },
    )

    executor_called = {"value": False}

    result = dispatch_cancel_execution(
        {
            "internal_order_id": "ord_cancel_bypass_1",
            "action": "cancel",
            "broker_order_id": None,
        },
        cancel_executor=lambda broker_order_id: executor_called.__setitem__(
            "value", True
        ),
        repository=repository,
        tracking_service=tracking_service,
        broker_submit_mode="observe_only",
    )

    assert result["status"] == "cancel_bypassed"
    assert executor_called["value"] is False
    assert repository.find_order("ord_cancel_bypass_1")["state"] == "CANCELED"


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


def test_default_credit_detail_loader_accepts_credit_detail_object(monkeypatch):
    detail = types.SimpleNamespace(m_dAvailable=10001, m_dFinDebt=1)
    fake_module = types.ModuleType("freshquant.position_management.credit_client")

    class FakeClient:
        def query_credit_detail(self):
            return detail

    fake_module.PositionCreditClient = FakeClient
    monkeypatch.setitem(
        sys.modules,
        "freshquant.position_management.credit_client",
        fake_module,
    )

    assert execution_bridge._default_credit_detail_loader() is detail


def test_default_continuous_auction_provider_returns_true_during_morning_session(
    monkeypatch,
):
    real_datetime = execution_bridge.datetime

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 3, 31, 9, 41, 30, tzinfo=tz)

    monkeypatch.setattr(execution_bridge, "datetime", FixedDateTime)

    assert execution_bridge._default_continuous_auction_provider() is True


def test_prepare_submit_execution_rejects_credit_auto_sell_when_credit_detail_missing():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_runtime_sell_missing_credit_detail",
            "account_type": "CREDIT",
            "credit_trade_mode": "auto",
            "price_mode": "auto",
        }
    )
    repository.update_order(
        "ord_runtime_sell_missing_credit_detail",
        {
            "state": "QUEUED",
            "account_type": "CREDIT",
            "credit_trade_mode_requested": "auto",
            "price_mode_requested": "auto",
        },
    )

    with pytest.raises(RuntimeError, match="credit detail"):
        prepare_submit_execution(
            {
                "internal_order_id": "ord_runtime_sell_missing_credit_detail",
                "action": "sell",
                "symbol": "600000",
                "price": 10.0,
                "quantity": 100,
            },
            repository=repository,
            tracking_service=tracking_service,
            credit_detail_loader=lambda: None,
            continuous_auction_provider=lambda: True,
        )


def test_prepare_submit_execution_rejects_credit_auto_price_when_auction_state_missing():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_runtime_sell_missing_auction_state",
            "account_type": "CREDIT",
            "credit_trade_mode": "auto",
            "price_mode": "auto",
        }
    )
    repository.update_order(
        "ord_runtime_sell_missing_auction_state",
        {
            "state": "QUEUED",
            "account_type": "CREDIT",
            "credit_trade_mode_requested": "auto",
            "price_mode_requested": "auto",
        },
    )

    with pytest.raises(RuntimeError, match="continuous auction"):
        prepare_submit_execution(
            {
                "internal_order_id": "ord_runtime_sell_missing_auction_state",
                "action": "sell",
                "symbol": "600000",
                "price": 10.0,
                "quantity": 100,
            },
            repository=repository,
            tracking_service=tracking_service,
            credit_detail_loader=lambda: {"m_dAvailable": 10001, "m_dFinDebt": 1},
            continuous_auction_provider=lambda: (_ for _ in ()).throw(
                RuntimeError("clock unavailable")
            ),
        )


def test_prepare_submit_execution_skips_auction_probe_for_explicit_limit_price():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_runtime_sell_limit_price",
            "account_type": "CREDIT",
            "credit_trade_mode": "auto",
            "price_mode": "limit",
        }
    )
    repository.update_order(
        "ord_runtime_sell_limit_price",
        {
            "state": "QUEUED",
            "account_type": "CREDIT",
            "credit_trade_mode_requested": "auto",
            "price_mode_requested": "limit",
        },
    )

    result = prepare_submit_execution(
        {
            "internal_order_id": "ord_runtime_sell_limit_price",
            "action": "sell",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
        },
        repository=repository,
        tracking_service=tracking_service,
        credit_detail_loader=lambda: {"m_dAvailable": 10001, "m_dFinDebt": 1},
        continuous_auction_provider=lambda: (_ for _ in ()).throw(
            AssertionError("continuous_auction_provider should not be called")
        ),
    )

    assert result["status"] == "execute"
    assert result["order_message"]["broker_price_type"] == xtconstant.FIX_PRICE


def test_prepare_submit_execution_loads_credit_detail_for_finance_buy():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "002123",
            "price": 10.0,
            "quantity": 5000,
            "source": "strategy",
            "internal_order_id": "ord_runtime_finance_buy_1",
            "account_type": "CREDIT",
            "credit_trade_mode": "finance_buy",
            "price_mode": "limit",
        }
    )
    repository.update_order(
        "ord_runtime_finance_buy_1",
        {
            "state": "QUEUED",
            "account_type": "CREDIT",
            "credit_trade_mode_requested": "finance_buy",
            "credit_trade_mode_resolved": "finance_buy",
            "broker_order_type": None,
            "price_mode_requested": "limit",
            "broker_price_type": None,
        },
    )
    observed = {"loader_calls": 0}

    result = prepare_submit_execution(
        {
            "internal_order_id": "ord_runtime_finance_buy_1",
            "action": "buy",
            "symbol": "002123",
            "price": 10.0,
            "quantity": 5000,
        },
        repository=repository,
        tracking_service=tracking_service,
        credit_detail_loader=lambda: observed.__setitem__(
            "loader_calls", observed["loader_calls"] + 1
        )
        or {"m_dEnableBailBalance": 60000, "m_dAvailable": 12000},
    )

    assert result["status"] == "execute"
    assert observed["loader_calls"] == 1
    assert result["order_message"]["broker_order_type"] == xtconstant.CREDIT_FIN_BUY
    assert result["order_message"]["credit_available_bail_balance"] == 60000.0
    assert result["order_message"]["credit_available_amount"] == 12000.0
