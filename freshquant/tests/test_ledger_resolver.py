# -*- coding: utf-8 -*-
"""LedgerResolver 唯一归属判定入口测试（Issue #571 根治方案 v4）。"""

from __future__ import annotations

import pytest

from freshquant.order_management.ledger_resolver import (
    LEDGER_BASE,
    LEDGER_MIXED,
    LEDGER_T,
    LEDGER_UNSPECIFIED,
    InvalidLedgerIntentError,
    LedgerIntentConflictError,
    LedgerIntentMissingError,
    is_takeprofit_request,
    ledger_from_allocations,
    normalize_ledger_intent,
    resolve_buy_position_type,
    resolve_order_ledger,
)


def _request(ledger_intent=None, **extra):
    row = dict(extra)
    if ledger_intent is not None:
        row["ledger_intent"] = ledger_intent
    return row


def test_normalize_ledger_intent_accepts_canonical_values():
    assert normalize_ledger_intent("base") == "base"
    assert normalize_ledger_intent("T") == "t"
    assert normalize_ledger_intent("mixed") == "mixed"
    assert normalize_ledger_intent("-") == "-"
    assert normalize_ledger_intent(None) is None
    assert normalize_ledger_intent("") is None
    assert normalize_ledger_intent("unknown") is None


def test_buy_order_ledger_from_intent_base_and_t():
    assert resolve_order_ledger(side="buy", request_row=_request("base")) == "base"
    assert resolve_order_ledger(side="buy", request_row=_request("t")) == "t"


def test_buy_order_ledger_missing_intent_fails_closed():
    with pytest.raises(LedgerIntentMissingError):
        resolve_order_ledger(side="buy", request_row={})


def test_buy_order_ledger_invalid_intent_fails_closed():
    with pytest.raises(InvalidLedgerIntentError):
        resolve_order_ledger(side="buy", request_row=_request("mixed"))
    with pytest.raises(InvalidLedgerIntentError):
        resolve_order_ledger(side="buy", request_row=_request("-"))


def test_broker_only_buy_is_explicit_base():
    assert (
        resolve_order_ledger(side="buy", request_row=None, broker_only=True) == "base"
    )


def test_sell_ledger_from_intent_base_t_and_unspecified():
    assert resolve_order_ledger(side="sell", request_row=_request("base")) == "base"
    assert resolve_order_ledger(side="sell", request_row=_request("t")) == "t"
    assert resolve_order_ledger(side="sell", request_row=_request("-")) == "-"
    assert resolve_order_ledger(side="sell", request_row=_request("mixed")) == "mixed"


def test_sell_missing_intent_fails_closed():
    with pytest.raises(LedgerIntentMissingError):
        resolve_order_ledger(side="sell", request_row={})


def test_mixed_sell_wins_over_single_intent():
    allocations = [{"position_type": "base"}, {"position_type": "t"}]
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=_request("base"),
            exit_allocations=allocations,
        )
        == "mixed"
    )
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=_request("t"),
            exit_allocations=allocations,
        )
        == "mixed"
    )


def test_sell_unspecified_uses_allocation_truth_when_single_ledger():
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=_request("-"),
            exit_allocations=[{"position_type": "base"}],
        )
        == "base"
    )
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=_request("-"),
            exit_allocations=[{"position_type": "t"}],
        )
        == "t"
    )


def test_broker_only_sell_uses_allocation_truth_or_unspecified():
    assert resolve_order_ledger(side="sell", request_row=None, broker_only=True) == "-"
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=None,
            broker_only=True,
            exit_allocations=[{"position_type": "base"}],
        )
        == "base"
    )
    assert (
        resolve_order_ledger(
            side="sell",
            request_row=None,
            broker_only=True,
            exit_allocations=[{"position_type": "t"}, {"position_type": "base"}],
        )
        == "mixed"
    )


def test_unknown_side_is_unspecified():
    assert resolve_order_ledger(side="unknown", request_row={}) == "-"


def test_ledger_from_allocations_summary():
    assert ledger_from_allocations([]) is None
    assert ledger_from_allocations([{"position_type": "base"}]) == "base"
    assert ledger_from_allocations([{"position_type": "t"}]) == "t"
    assert (
        ledger_from_allocations([{"position_type": "base"}, {"position_type": "t"}])
        == "mixed"
    )
    assert ledger_from_allocations([{"position_type": "-"}]) is None
    assert ledger_from_allocations(None) is None


def test_resolve_buy_position_type():
    assert resolve_buy_position_type(request_row=_request("base")) == "base"
    assert resolve_buy_position_type(request_row=_request("t")) == "t"
    assert resolve_buy_position_type(broker_only=True) == "base"
    with pytest.raises(LedgerIntentMissingError):
        resolve_buy_position_type(request_row={})
    with pytest.raises(InvalidLedgerIntentError):
        resolve_buy_position_type(request_row=_request("-"))


def test_is_takeprofit_request_by_source_and_scope():
    assert is_takeprofit_request({"source": "tpsl_takeprofit"}) is True
    assert is_takeprofit_request({"scope_type": "takeprofit_batch"}) is True
    assert is_takeprofit_request({"source": "guardian"}) is False
    assert is_takeprofit_request(None) is False


def test_exports_include_conflict_error():
    assert issubclass(LedgerIntentConflictError, ValueError)


def test_constants():
    assert LEDGER_BASE == "base"
    assert LEDGER_T == "t"
    assert LEDGER_MIXED == "mixed"
    assert LEDGER_UNSPECIFIED == "-"
