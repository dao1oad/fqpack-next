# -*- coding: utf-8 -*-
"""OrderStateService 终态门禁与迟到回报语义测试（Issue #571 #6）。"""

from __future__ import annotations

import pytest

from freshquant.order_management.tracking.order_state import (
    LATE_ORDER_REPORT_EVENT_TYPE,
    LATE_TRADE_EVENT_TYPE,
    OrderStateService,
    is_terminal_state,
)
from freshquant.order_management.tracking.state_machine import InvalidOrderTransition


def _service():
    return OrderStateService()


def test_order_report_terminal_filled_never_regresses():
    service = _service()
    next_state, absorbed, late_alert = service.apply_order_report(
        "FILLED", "PARTIAL_FILLED"
    )
    assert next_state == "FILLED"
    assert absorbed is True
    assert late_alert is True

    next_state, absorbed, late_alert = service.apply_order_report("FILLED", "CANCELED")
    assert next_state == "FILLED"
    assert absorbed is True
    assert late_alert is True


def test_order_report_terminal_canceled_never_regresses():
    service = _service()
    next_state, absorbed, late_alert = service.apply_order_report(
        "CANCELED", "PARTIAL_FILLED"
    )
    assert next_state == "CANCELED"
    assert absorbed is True
    assert late_alert is True

    next_state, absorbed, late_alert = service.apply_order_report("CANCELED", "FILLED")
    assert next_state == "CANCELED"
    assert absorbed is True
    assert late_alert is True


def test_order_report_same_terminal_state_is_noop():
    service = _service()
    next_state, absorbed, late_alert = service.apply_order_report("FILLED", "FILLED")
    assert next_state == "FILLED"
    assert absorbed is True
    assert late_alert is False


def test_order_report_normal_transition_uses_state_machine():
    service = _service()
    next_state, absorbed, late_alert = service.apply_order_report("SUBMITTED", "FILLED")
    assert next_state == "FILLED"
    assert absorbed is False
    assert late_alert is False


def test_order_report_non_terminal_invalid_transition_raises():
    service = _service()
    with pytest.raises(InvalidOrderTransition):
        service.apply_order_report("ACCEPTED", "FILLED")


def test_fill_aggregate_keeps_terminal_state_with_alert():
    service = _service()
    state, late_alert = service.apply_fill_aggregate_state(
        "CANCELED", next_quantity=100, requested_quantity=100
    )
    assert state == "CANCELED"
    assert late_alert is True

    state, late_alert = service.apply_fill_aggregate_state(
        "FILLED", next_quantity=100, requested_quantity=100
    )
    assert state == "FILLED"
    assert late_alert is True


def test_fill_aggregate_partial_then_filled():
    service = _service()
    state, late_alert = service.apply_fill_aggregate_state(
        "SUBMITTED", next_quantity=50, requested_quantity=100
    )
    assert state == "PARTIAL_FILLED"
    assert late_alert is False

    state, late_alert = service.apply_fill_aggregate_state(
        "PARTIAL_FILLED", next_quantity=100, requested_quantity=100
    )
    assert state == "FILLED"
    assert late_alert is False


def test_fill_aggregate_missing_requested_stays_partial():
    service = _service()
    state, late_alert = service.apply_fill_aggregate_state(
        "SUBMITTED", next_quantity=100, requested_quantity=None
    )
    assert state == "PARTIAL_FILLED"
    assert late_alert is False


def test_terminal_helpers_and_event_types():
    assert is_terminal_state("FILLED") is True
    assert is_terminal_state("CANCELED") is True
    assert is_terminal_state("PARTIAL_FILLED") is False
    assert LATE_ORDER_REPORT_EVENT_TYPE == "late_order_report_after_terminal"
    assert LATE_TRADE_EVENT_TYPE == "late_trade_after_terminal"
