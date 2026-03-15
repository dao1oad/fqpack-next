# -*- coding: utf-8 -*-

from types import SimpleNamespace

import pytest

from freshquant.carnation import xtconstant
from freshquant.order_management.submit.credit_order_resolver import (
    build_credit_subject_lookup,
    get_configured_account_type,
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


def test_get_configured_account_type_reads_system_settings_provider():
    account_type = get_configured_account_type(
        settings_provider=SimpleNamespace(
            xtquant=SimpleNamespace(account_type="credit")
        )
    )

    assert account_type == "CREDIT"


def test_build_credit_subject_lookup_scopes_to_system_settings_account():
    seen = {}

    class FakeRepository:
        def find_by_symbol(self, symbol, account_id=None):
            seen["symbol"] = symbol
            seen["account_id"] = account_id
            return {"symbol": symbol, "account_id": account_id}

    lookup = build_credit_subject_lookup(
        repository=FakeRepository(),
        settings_provider=SimpleNamespace(xtquant=SimpleNamespace(account="acct-2")),
    )

    assert lookup("000001") == {"symbol": "000001", "account_id": "acct-2"}
    assert seen == {"symbol": "000001", "account_id": "acct-2"}
