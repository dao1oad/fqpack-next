# -*- coding: utf-8 -*-

from datetime import datetime

from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.policy import PositionPolicy
from freshquant.position_management.service import PositionManagementService


class FakeDecisionRepository:
    def __init__(self):
        self.current_state_doc = None
        self.decisions = []

    def get_current_state(self):
        return self.current_state_doc

    def insert_decision(self, document):
        self.decisions.append(document)
        return document


def _fixed_now():
    return datetime.fromisoformat("2026-03-07T12:00:00+08:00")


def test_bail_above_800k_allows_open():
    policy = PositionPolicy(allow_open_min_bail=800000, holding_only_min_bail=100000)

    assert policy.state_from_bail(800001) == ALLOW_OPEN


def test_bail_equal_800k_falls_into_holding_only():
    policy = PositionPolicy(allow_open_min_bail=800000, holding_only_min_bail=100000)

    assert policy.state_from_bail(800000) == HOLDING_ONLY


def test_bail_equal_100k_falls_into_force_profit_reduce():
    policy = PositionPolicy(allow_open_min_bail=800000, holding_only_min_bail=100000)

    assert policy.state_from_bail(100000) == FORCE_PROFIT_REDUCE


def test_missing_state_defaults_to_holding_only():
    policy = PositionPolicy(state_stale_after_seconds=15, default_state=HOLDING_ONLY)

    assert policy.effective_state(None, now_value=_fixed_now()) == HOLDING_ONLY


def test_stale_state_defaults_to_holding_only():
    policy = PositionPolicy(state_stale_after_seconds=15, default_state=HOLDING_ONLY)

    assert (
        policy.effective_state(
            {"state": ALLOW_OPEN, "evaluated_at": "2026-03-07T11:59:00+08:00"},
            now_value=_fixed_now(),
        )
        == HOLDING_ONLY
    )


def test_holding_only_blocks_new_symbol_buy_and_records_decision():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000002"],
        now_provider=_fixed_now,
    )

    decision = service.evaluate_strategy_order(
        payload={"source": "strategy", "action": "buy", "symbol": "000001"},
        current_state={
            "state": HOLDING_ONLY,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    assert decision.allowed is False
    assert decision.state == HOLDING_ONLY
    assert decision.reason_code == "new_position_blocked"
    assert repository.decisions[-1]["allowed"] is False


def test_holding_only_allows_existing_symbol_buy_after_symbol_normalization():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )

    decision = service.evaluate_strategy_order(
        payload={"source": "strategy", "action": "buy", "symbol": "sz000001"},
        current_state={
            "state": HOLDING_ONLY,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    assert decision.allowed is True
    assert decision.state == HOLDING_ONLY
    assert decision.reason_code == "holding_buy_allowed"


def test_force_profit_reduce_blocks_all_buys():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )

    decision = service.evaluate_strategy_order(
        payload={"source": "strategy", "action": "buy", "symbol": "000001"},
        current_state={
            "state": FORCE_PROFIT_REDUCE,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    assert decision.allowed is False
    assert decision.state == FORCE_PROFIT_REDUCE
    assert decision.reason_code == "buy_blocked_force_profit_reduce"


def test_stale_allow_open_state_blocks_new_symbol_buy():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: [],
        now_provider=_fixed_now,
        policy=PositionPolicy(state_stale_after_seconds=15, default_state=HOLDING_ONLY),
    )

    decision = service.evaluate_strategy_order(
        payload={"source": "strategy", "action": "buy", "symbol": "000001"},
        current_state={
            "state": ALLOW_OPEN,
            "evaluated_at": "2026-03-07T11:59:30+08:00",
        },
    )

    assert decision.allowed is False
    assert decision.state == HOLDING_ONLY
    assert decision.reason_code == "new_position_blocked"


def test_force_profit_reduce_allows_sell():
    repository = FakeDecisionRepository()
    service = PositionManagementService(
        repository=repository,
        holding_codes_provider=lambda: ["000001"],
        now_provider=_fixed_now,
    )

    decision = service.evaluate_strategy_order(
        payload={"source": "strategy", "action": "sell", "symbol": "000001"},
        current_state={
            "state": FORCE_PROFIT_REDUCE,
            "evaluated_at": "2026-03-07T12:00:00+08:00",
        },
    )

    assert decision.allowed is True
    assert decision.state == FORCE_PROFIT_REDUCE
    assert decision.reason_code == "sell_allowed"
