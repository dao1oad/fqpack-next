from __future__ import annotations

from datetime import date
from decimal import Decimal

from freshquant.backtest.clx.portfolio import (
    DEFAULT_FEE_SCHEDULE,
    DEFAULT_LIMIT_SCHEDULE,
    DEFAULT_SLIPPAGE_MODEL,
    BlockedReason,
    MarketBar,
    Side,
)


def test_historical_stamp_tax_and_transfer_fee_boundaries_are_versioned() -> None:
    old = DEFAULT_FEE_SCHEDULE.calculate(
        trade_date=date(2007, 6, 1),
        code="600001",
        side=Side.BUY,
        notional=Decimal("100000"),
    )
    assert old.stamp_tax_rule_id == "STAMP_20070530_30_BPS_BOTH"
    assert old.stamp_tax == Decimal("300.00")
    assert old.transfer_fee_rule_id == "TRANSFER_PRE_20150801_APPROX"
    assert old.transfer_fee == Decimal("60.00")

    before_cut = DEFAULT_FEE_SCHEDULE.calculate(
        trade_date=date(2023, 8, 27),
        code="600001",
        side=Side.SELL,
        notional=Decimal("100000"),
    )
    after_cut = DEFAULT_FEE_SCHEDULE.calculate(
        trade_date=date(2023, 8, 28),
        code="600001",
        side=Side.SELL,
        notional=Decimal("100000"),
    )
    assert before_cut.stamp_tax_rule_id == "STAMP_20080919_10_BPS_SELL"
    assert before_cut.stamp_tax == Decimal("100.00")
    assert after_cut.stamp_tax_rule_id == "STAMP_20230828_5_BPS_SELL"
    assert after_cut.stamp_tax == Decimal("50.00")
    assert after_cut.transfer_fee_rule_id == "TRANSFER_20220429_0_1_BPS"
    assert after_cut.transfer_fee == Decimal("1.00")


def test_minimum_commission_and_current_fee_lines_are_hand_calculable() -> None:
    buy = DEFAULT_FEE_SCHEDULE.calculate(
        trade_date=date(2024, 1, 3),
        code="600001",
        side=Side.BUY,
        notional=Decimal("9009.00"),
    )
    assert buy.commission == Decimal("5")
    assert buy.minimum_commission_adjustment == Decimal("2.30")
    assert buy.stamp_tax == Decimal("0.00")
    assert buy.transfer_fee == Decimal("0.09")
    assert buy.total_fee == Decimal("5.09")

    sell = DEFAULT_FEE_SCHEDULE.calculate(
        trade_date=date(2024, 1, 9),
        code="600001",
        side=Side.SELL,
        notional=Decimal("8541.00"),
    )
    assert sell.commission == Decimal("5")
    assert sell.minimum_commission_adjustment == Decimal("2.44")
    assert sell.stamp_tax == Decimal("4.27")
    assert sell.transfer_fee == Decimal("0.09")
    assert sell.total_fee == Decimal("9.36")


def test_symmetric_slippage_rounds_to_the_a_share_price_tick() -> None:
    assert DEFAULT_SLIPPAGE_MODEL.apply(Decimal("10"), Side.BUY) == Decimal("10.01")
    assert DEFAULT_SLIPPAGE_MODEL.apply(Decimal("9.50"), Side.SELL) == Decimal("9.49")


def test_open_limit_check_uses_raw_open_and_previous_raw_close() -> None:
    limit_up_bar = MarketBar(
        date(2024, 1, 3),
        "600001",
        Decimal("11.00"),
        Decimal("20.00"),
        Decimal("10.00"),
        Decimal("1000"),
    )
    buy_check = DEFAULT_LIMIT_SCHEDULE.check(limit_up_bar, Side.BUY)
    assert buy_check.blocked_reason is BlockedReason.LIMIT_UP
    assert buy_check.limit_price == Decimal("11.00")

    limit_down_bar = MarketBar(
        date(2024, 1, 3),
        "600001",
        Decimal("9.00"),
        Decimal("1.00"),
        Decimal("10.00"),
        Decimal("1000"),
    )
    sell_check = DEFAULT_LIMIT_SCHEDULE.check(limit_down_bar, Side.SELL)
    assert sell_check.blocked_reason is BlockedReason.LIMIT_DOWN
    assert sell_check.limit_price == Decimal("9.00")

    suspended = MarketBar(
        date(2024, 1, 3),
        "600001",
        Decimal("10"),
        Decimal("10"),
        Decimal("10"),
        Decimal("0"),
    )
    assert (
        DEFAULT_LIMIT_SCHEDULE.check(suspended, Side.BUY).blocked_reason
        is BlockedReason.SUSPENDED
    )
    assert (
        DEFAULT_LIMIT_SCHEDULE.check(None, Side.BUY).blocked_reason
        is BlockedReason.NO_BAR
    )
