# -*- coding: utf-8 -*-

import pytest

from freshquant.carnation import xtconstant
from freshquant.order_management.submit.credit_order_resolver import (
    resolve_submit_credit_order,
)


def test_credit_buy_uses_finance_buy_when_symbol_is_margin_target():
    result = resolve_submit_credit_order(
        account_type="CREDIT",
        action="buy",
        symbol="600000",
        credit_subject_lookup=lambda _symbol: {"fin_status": 48},
        credit_subjects_available=lambda: True,
    )

    assert result["credit_trade_mode_requested"] == "auto"
    assert result["credit_trade_mode_resolved"] == "finance_buy"
    assert result["broker_order_type"] == xtconstant.CREDIT_FIN_BUY


def test_credit_buy_uses_collateral_buy_when_symbol_not_margin_target():
    result = resolve_submit_credit_order(
        account_type="CREDIT",
        action="buy",
        symbol="000001",
        credit_subject_lookup=lambda _symbol: None,
        credit_subjects_available=lambda: True,
    )

    assert result["credit_trade_mode_requested"] == "auto"
    assert result["credit_trade_mode_resolved"] == "collateral_buy"
    assert result["broker_order_type"] == xtconstant.CREDIT_BUY


def test_credit_buy_rejects_when_credit_subjects_have_never_been_synced():
    with pytest.raises(ValueError, match="credit subjects unavailable"):
        resolve_submit_credit_order(
            account_type="CREDIT",
            action="buy",
            symbol="600000",
            credit_subject_lookup=lambda _symbol: None,
            credit_subjects_available=lambda: False,
        )
