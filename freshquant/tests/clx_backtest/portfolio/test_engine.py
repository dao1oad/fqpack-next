from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from freshquant.backtest.clx.portfolio import (
    BlockedReason,
    MarketBar,
    OrderStatus,
    PortfolioConfig,
    Side,
    SignalDecision,
    SlippageModel,
    run_portfolio,
)

D1 = date(2024, 1, 2)
D2 = date(2024, 1, 3)
D3 = date(2024, 1, 4)
D4 = date(2024, 1, 5)
D5 = date(2024, 1, 8)
D6 = date(2024, 1, 9)
SESSIONS = (D1, D2, D3, D4, D5, D6)


def _bar(
    session: date,
    code: str,
    raw_open: str,
    raw_close: str,
    previous_raw_close: str,
    raw_volume: str = "1000",
) -> MarketBar:
    return MarketBar(
        session,
        code,
        Decimal(raw_open),
        Decimal(raw_close),
        Decimal(previous_raw_close),
        Decimal(raw_volume),
    )


def _fixture_result():
    bars = (
        _bar(D1, "600001", "9.80", "10.00", "9.70"),
        _bar(D1, "600002", "9.80", "10.00", "9.70"),
        _bar(D1, "600003", "4.90", "5.00", "4.80"),
        _bar(D2, "600001", "10.00", "10.00", "10.00"),
        _bar(D2, "600002", "11.00", "10.80", "10.00"),
        # 600003 deliberately has no D2 bar.
        _bar(D3, "600001", "9.00", "9.20", "10.00"),
        _bar(D4, "600001", "9.10", "9.10", "9.20", raw_volume="0"),
        # 600001 deliberately has no D5 bar.
        _bar(D6, "600001", "9.50", "9.60", "9.10"),
    )
    decisions = (
        SignalDecision("A_BUY", D1, "600001", 1, Decimal("3"), ("sf-a",)),
        SignalDecision("B_BUY", D1, "600002", 1, Decimal("2"), ("sf-b",)),
        SignalDecision("C_BUY", D1, "600003", 1, Decimal("1"), ("sf-c",)),
        SignalDecision("D_BUY", D1, "600004", 1, Decimal("9"), ("sf-d+",)),
        SignalDecision("D_VETO", D1, "600004", -1, Decimal("1"), ("sf-d-",)),
        SignalDecision("A_EXIT", D2, "600001", -1, Decimal("1"), ("sf-exit",)),
    )
    return run_portfolio(
        config=PortfolioConfig(
            run_id="fixture-run",
            combo_id="fixture-combo",
            initial_cash=Decimal("10000"),
            target_weight=Decimal("1"),
            max_holdings=3,
        ),
        sessions=SESSIONS,
        bars=bars,
        decisions=decisions,
    )


def test_daily_fixture_covers_t1_blocks_pending_sell_and_fifo_lots() -> None:
    result = _fixture_result()

    assert [
        (fill.side, fill.trade_date, fill.code, fill.qty) for fill in result.fills
    ] == [
        (Side.BUY, D2, "600001", 900),
        (Side.SELL, D6, "600001", 900),
    ]
    assert all(
        fill.trade_date > order.decision_date
        for fill in result.fills
        for order in result.orders
        if order.order_id == fill.order_id
    )
    assert all(fill.qty % 100 == 0 for fill in result.fills)

    buy_attempt = next(
        row for row in result.orders if row.side is Side.BUY and row.code == "600001"
    )
    assert buy_attempt.requested_qty == 1000
    assert buy_attempt.filled_qty == 900
    assert buy_attempt.status is OrderStatus.PARTIALLY_FILLED

    sell_attempts = [row for row in result.orders if row.side is Side.SELL]
    assert [
        (row.attempt_no, row.target_trade_date, row.status, row.blocked_reason)
        for row in sell_attempts
    ] == [
        (1, D3, OrderStatus.BLOCKED_PENDING, BlockedReason.LIMIT_DOWN),
        (2, D4, OrderStatus.BLOCKED_PENDING, BlockedReason.SUSPENDED),
        (3, D5, OrderStatus.BLOCKED_PENDING, BlockedReason.NO_BAR),
        (4, D6, OrderStatus.FILLED, None),
    ]
    assert result.pending_sell_order_ids == ()

    reasons = [row.reason for row in result.blocked]
    assert BlockedReason.LIMIT_UP in reasons
    assert BlockedReason.NO_BAR in reasons
    assert BlockedReason.LIMIT_DOWN in reasons
    assert BlockedReason.SUSPENDED in reasons
    assert BlockedReason.NEGATIVE_SIGNAL_VETO in reasons
    assert BlockedReason.NEGATIVE_SIGNAL_NO_POSITION in reasons

    assert [
        (row.event, row.trade_date, row.qty_delta, row.remaining_qty)
        for row in result.lots
    ] == [
        ("BUY_LOT_OPEN", D2, 900, 900),
        ("T1_RELEASE", D3, 0, 900),
        ("SELL_LOT_FIFO", D6, -900, 0),
    ]
    bought_position = next(row for row in result.positions if row.trade_date == D2)
    released_position = next(row for row in result.positions if row.trade_date == D3)
    stale_position = next(row for row in result.positions if row.trade_date == D5)
    assert (bought_position.qty, bought_position.available_qty) == (900, 0)
    assert (released_position.qty, released_position.available_qty) == (900, 900)
    assert stale_position.stale_price_sessions == 1


def test_fill_fees_slippage_and_cash_are_exact_hand_calculations() -> None:
    result = _fixture_result()
    buy, sell = result.fills

    assert (buy.raw_open, buy.slippage, buy.fill_price) == (
        Decimal("10.00"),
        Decimal("0.01"),
        Decimal("10.01"),
    )
    assert buy.gross_notional == Decimal("9009.00")
    assert (buy.commission, buy.minimum_commission_adjustment) == (
        Decimal("5"),
        Decimal("2.30"),
    )
    assert (buy.stamp_tax, buy.transfer_fee, buy.total_fee) == (
        Decimal("0.00"),
        Decimal("0.09"),
        Decimal("5.09"),
    )
    assert buy.cash_delta == Decimal("-9014.09")

    assert (sell.raw_open, sell.slippage, sell.fill_price) == (
        Decimal("9.50"),
        Decimal("-0.01"),
        Decimal("9.49"),
    )
    assert sell.gross_notional == Decimal("8541.00")
    assert (sell.commission, sell.minimum_commission_adjustment) == (
        Decimal("5"),
        Decimal("2.44"),
    )
    assert (sell.stamp_tax, sell.transfer_fee, sell.total_fee) == (
        Decimal("4.27"),
        Decimal("0.09"),
        Decimal("9.36"),
    )
    assert sell.cash_delta == Decimal("8531.64")
    assert result.equity[-1].cash == Decimal("9517.55")
    assert result.equity[-1].equity == Decimal("9517.55")

    assert buy.fee_schedule_id == "CN_A_FEES_V1_20260722"
    assert buy.stamp_tax_rule_id == "STAMP_20230828_5_BPS_SELL"
    assert buy.transfer_fee_rule_id == "TRANSFER_20220429_0_1_BPS"
    assert buy.limit_rule_id == "MAIN_BOARD_10_PERCENT_V1"
    assert buy.slippage_model_id == "RAW_OPEN_SYMMETRIC_10_BPS_TICK_V1"


def test_daily_dual_entry_and_quantity_reconciliation_never_hides_short_or_debt() -> (
    None
):
    result = _fixture_result()
    assert len(result.equity) == len(SESSIONS)
    for row in result.equity:
        assert row.balance_sheet_error == Decimal("0")
        assert row.cash_reconciliation_error == Decimal("0")
        assert row.quantity_reconciliation_ok is True
        assert row.cash >= 0
        assert abs(row.balance_sheet_error) <= row.reconciliation_tolerance
        assert abs(row.cash_reconciliation_error) <= row.reconciliation_tolerance
    assert all(row.qty > 0 and row.available_qty >= 0 for row in result.positions)
    assert all(
        row.side is not Side.SELL or row.code == "600001" for row in result.orders
    )
    assert len(result.institutional_approximations) == 4


def test_portfolio_id_changes_when_a_versioned_execution_input_changes() -> None:
    base = PortfolioConfig(
        run_id="run",
        combo_id="combo",
        initial_cash=Decimal("10000"),
    )
    changed = replace(
        base,
        slippage_model=SlippageModel("RAW_OPEN_20_BPS_V2", Decimal("20")),
    )
    assert base.portfolio_id != changed.portfolio_id
    assert base.portfolio_id == replace(base).portfolio_id


def test_shared_market_stream_is_field_exact_with_fixture_wrapper() -> None:
    bars = (
        _bar(D1, "600001", "9.80", "10.00", "9.70"),
        _bar(D2, "600001", "10.00", "10.20", "10.00"),
        _bar(D3, "600001", "10.30", "10.40", "10.20"),
        _bar(D4, "600001", "10.50", "10.60", "10.40"),
    )
    decisions = (
        SignalDecision("BUY", D1, "600001", 1, Decimal("1"), ("sf-buy",)),
        SignalDecision("SELL", D2, "600001", -1, Decimal("1"), ("sf-sell",)),
    )
    config = PortfolioConfig(
        run_id="shared-exact",
        combo_id="combo-exact",
        initial_cash=Decimal("10000"),
        target_weight=Decimal("1"),
    )
    fixture = run_portfolio(
        config=config,
        sessions=(D1, D2, D3, D4),
        bars=bars,
        decisions=decisions,
    )

    from freshquant.backtest.clx.portfolio import run_portfolios_shared

    streamed = run_portfolios_shared(
        configs=(config,),
        sessions=(D1, D2, D3, D4),
        session_bars=(
            (session, tuple(bar for bar in bars if bar.session == session))
            for session in (D1, D2, D3, D4)
        ),
        decisions_by_combo={config.combo_id: decisions},
    )[config.combo_id]
    assert streamed == fixture


def test_twenty_portfolios_consume_each_market_session_once() -> None:
    from freshquant.backtest.clx.portfolio import run_portfolios_shared

    sessions = (D1, D2, D3, D4)
    configs = tuple(
        PortfolioConfig(
            run_id="shared-scan",
            combo_id=f"combo-{index:02d}",
            initial_cash=Decimal("10000"),
        )
        for index in range(20)
    )
    consumed: list[date] = []

    def batches():
        for session in sessions:
            consumed.append(session)
            yield session, ()

    results = run_portfolios_shared(
        configs=configs,
        sessions=sessions,
        session_bars=batches(),
        decisions_by_combo={config.combo_id: () for config in configs},
    )
    assert consumed == list(sessions)
    assert len(results) == 20
    assert all(len(result.equity) == len(sessions) for result in results.values())


def _replacement_result(second_score: str):
    bars = tuple(
        _bar(session, code, raw_open, raw_close, previous)
        for session in (D1, D2, D3, D4)
        for code, raw_open, raw_close, previous in (
            ("600001", "9.80", "10.00", "9.70"),
            ("600002", "4.90", "5.00", "4.80"),
        )
    )
    decisions = (
        SignalDecision("FIRST_BUY", D1, "600001", 1, Decimal("1"), ("sf-1",)),
        SignalDecision("SECOND_BUY", D2, "600002", 1, Decimal(second_score), ("sf-2",)),
    )
    return run_portfolio(
        config=PortfolioConfig(
            run_id="replacement-run",
            combo_id="replacement-combo",
            initial_cash=Decimal("10000"),
            target_weight=Decimal("1"),
            max_holdings=1,
            replacement_policy="SCORE_REPLACE_WEAKEST_HOLDING",
        ),
        sessions=(D1, D2, D3, D4),
        bars=bars,
        decisions=decisions,
    )


def test_replacement_sells_weakest_holding_before_buying_stronger_signal() -> None:
    result = _replacement_result("2")

    assert [(fill.side, fill.trade_date, fill.code) for fill in result.fills] == [
        (Side.BUY, D2, "600001"),
        (Side.SELL, D3, "600001"),
        (Side.BUY, D3, "600002"),
    ]
    assert BlockedReason.MAX_HOLDINGS not in [row.reason for row in result.blocked]
    replacement_sell = next(
        row for row in result.orders if row.side is Side.SELL and row.code == "600001"
    )
    assert replacement_sell.status is OrderStatus.FILLED
    final_equity = result.equity[-1]
    assert final_equity.holdings_count == 1
    assert final_equity.balance_sheet_error == Decimal("0")
    assert final_equity.cash >= 0


def test_replacement_keeps_holdings_when_new_signal_is_not_stronger() -> None:
    result = _replacement_result("0.5")

    assert [(fill.side, fill.trade_date, fill.code) for fill in result.fills] == [
        (Side.BUY, D2, "600001"),
    ]
    assert BlockedReason.MAX_HOLDINGS in [row.reason for row in result.blocked]
    assert all(row.side is not Side.SELL for row in result.orders)


def test_replacement_policy_changes_portfolio_id_but_none_is_stable() -> None:
    base = PortfolioConfig(
        run_id="run",
        combo_id="combo",
        initial_cash=Decimal("10000"),
    )
    changed = replace(
        base, replacement_policy="SCORE_REPLACE_WEAKEST_HOLDING", max_holdings=40
    )
    assert base.portfolio_id != changed.portfolio_id
    assert base.portfolio_id == replace(base, replacement_policy="NONE").portfolio_id
