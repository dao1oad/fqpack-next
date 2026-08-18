# -*- coding: utf-8 -*-
"""Issue #659：卖出提交清仓零股分支测试。"""

from __future__ import annotations

import sys
import types

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

from freshquant.order_management.sell_constraints import (
    resolve_sell_submission_quantity,
)

sys.modules.pop("freshquant.message", None)


def test_normal_board_lot_unchanged():
    result = resolve_sell_submission_quantity(
        requested_quantity=800,
        can_use_volume=1000,
        code="000001",
    )
    assert result["status"] == "ready"
    assert result["quantity"] == 800


def test_partial_request_floors_to_board_lot():
    result = resolve_sell_submission_quantity(
        requested_quantity=260,
        can_use_volume=1000,
        code="000001",
    )
    assert result["status"] == "ready"
    assert result["quantity"] == 200


def test_odd_lot_clear_when_request_covers_all_available():
    result = resolve_sell_submission_quantity(
        requested_quantity=60,
        can_use_volume=60,
        code="000001",
    )
    assert result["status"] == "ready"
    assert result["quantity"] == 60


def test_odd_lot_not_cleared_when_request_is_partial():
    result = resolve_sell_submission_quantity(
        requested_quantity=60,
        can_use_volume=160,
        code="000001",
    )
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "board_lot"
    assert result["quantity"] == 0


def test_star_board_lot_is_200():
    # 科创板：≥200 保持原值（1 股递增），<200 清仓才放行。
    result = resolve_sell_submission_quantity(
        requested_quantity=150,
        can_use_volume=150,
        code="688772",
    )
    assert result["status"] == "ready"
    assert result["quantity"] == 150

    partial = resolve_sell_submission_quantity(
        requested_quantity=250,
        can_use_volume=250,
        code="688772",
    )
    assert partial["status"] == "ready"
    assert partial["quantity"] == 250

    blocked = resolve_sell_submission_quantity(
        requested_quantity=150,
        can_use_volume=600,
        code="688772",
    )
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == "board_lot"


def test_zero_quantity_blocked():
    result = resolve_sell_submission_quantity(
        requested_quantity=0,
        can_use_volume=60,
        code="000001",
    )
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "quantity"
