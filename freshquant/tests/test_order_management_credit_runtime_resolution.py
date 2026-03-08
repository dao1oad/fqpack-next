# -*- coding: utf-8 -*-

from freshquant.carnation import xtconstant
from freshquant.order_management.submit.execution_bridge import (
    resolve_price_mode,
    resolve_runtime_credit_execution,
)


def test_credit_sell_uses_sell_repay_when_available_gt_10000_and_fin_debt_gt_0():
    result = resolve_runtime_credit_execution(
        account_type="CREDIT",
        action="sell",
        credit_detail={"m_dAvailable": 10001, "m_dFinDebt": 1},
    )

    assert result["credit_trade_mode_resolved"] == "sell_repay"
    assert result["broker_order_type"] == xtconstant.CREDIT_SELL_SECU_REPAY


def test_credit_sell_uses_collateral_sell_when_threshold_not_met():
    result = resolve_runtime_credit_execution(
        account_type="CREDIT",
        action="sell",
        credit_detail={"m_dAvailable": 10000, "m_dFinDebt": 1},
    )

    assert result["credit_trade_mode_resolved"] == "collateral_sell"
    assert result["broker_order_type"] == xtconstant.CREDIT_SELL


def test_auto_quote_uses_sh_convert_5_cancel_during_continuous_auction():
    result = resolve_price_mode(
        symbol="600000.SH",
        action="buy",
        price_mode="auto",
        input_price=10.0,
        continuous_auction=True,
    )

    assert result["price_mode_resolved"] == "market_5_cancel"
    assert result["broker_price_type"] == xtconstant.MARKET_SH_CONVERT_5_CANCEL
    assert result["price_to_use"] == 10.08


def test_auto_quote_uses_limit_when_not_in_continuous_auction():
    result = resolve_price_mode(
        symbol="000001.SZ",
        action="sell",
        price_mode="auto",
        input_price=10.0,
        continuous_auction=False,
    )

    assert result["price_mode_resolved"] == "limit"
    assert result["broker_price_type"] == xtconstant.FIX_PRICE
    assert result["price_to_use"] == 10.0
