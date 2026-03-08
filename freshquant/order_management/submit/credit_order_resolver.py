# -*- coding: utf-8 -*-

from freshquant.carnation import xtconstant
from freshquant.carnation.param import queryParam
from freshquant.order_management.credit_subjects.repository import (
    CreditSubjectRepository,
)

AUTO_CREDIT_TRADE_MODE = "auto"
COLLATERAL_BUY_MODE = "collateral_buy"
FINANCE_BUY_MODE = "finance_buy"


def resolve_submit_credit_order(
    account_type,
    action,
    symbol,
    requested_mode=None,
    credit_subject_lookup=None,
    credit_subjects_available=None,
):
    account_type_value = _normalize_account_type(account_type)
    requested_mode_value = _normalize_credit_trade_mode(requested_mode)
    action_value = str(action or "").strip().lower()
    result = {
        "account_type": account_type_value,
        "credit_trade_mode_requested": requested_mode_value,
        "credit_trade_mode_resolved": None,
        "broker_order_type": None,
    }
    if account_type_value != "CREDIT":
        return result
    if action_value != "buy":
        return result

    if requested_mode_value == AUTO_CREDIT_TRADE_MODE:
        if credit_subjects_available is not None and not credit_subjects_available():
            raise ValueError("credit subjects unavailable")
        subject = credit_subject_lookup(symbol) if credit_subject_lookup else None
        if _is_financing_subject(subject):
            result["credit_trade_mode_resolved"] = FINANCE_BUY_MODE
            result["broker_order_type"] = xtconstant.CREDIT_FIN_BUY
            return result
        result["credit_trade_mode_resolved"] = COLLATERAL_BUY_MODE
        result["broker_order_type"] = xtconstant.CREDIT_BUY
        return result

    if requested_mode_value == FINANCE_BUY_MODE:
        result["credit_trade_mode_resolved"] = FINANCE_BUY_MODE
        result["broker_order_type"] = xtconstant.CREDIT_FIN_BUY
        return result

    if requested_mode_value == COLLATERAL_BUY_MODE:
        result["credit_trade_mode_resolved"] = COLLATERAL_BUY_MODE
        result["broker_order_type"] = xtconstant.CREDIT_BUY
        return result

    raise ValueError(f"unsupported credit_trade_mode: {requested_mode_value}")


def get_configured_account_type(query_param=None):
    query_param = query_param or queryParam
    try:
        configured_value = query_param("xtquant.account_type", "STOCK")
    except Exception:
        configured_value = "STOCK"
    return _normalize_account_type(configured_value)


def build_credit_subject_lookup(repository=None, account_id=None, query_param=None):
    repository = repository or CreditSubjectRepository()
    configured_account_id = account_id or _get_configured_account_id(query_param)

    def _lookup(symbol):
        return repository.find_by_symbol(symbol, account_id=configured_account_id)

    return _lookup


def build_credit_subjects_available(
    repository=None,
    account_id=None,
    query_param=None,
):
    repository = repository or CreditSubjectRepository()
    configured_account_id = account_id or _get_configured_account_id(query_param)

    def _available():
        return repository.has_any_subjects(account_id=configured_account_id)

    return _available


def _get_configured_account_id(query_param=None):
    query_param = query_param or queryParam
    try:
        raw_value = query_param("xtquant.account", "")
    except Exception:
        raw_value = ""
    value = str(raw_value or "").strip()
    return value or None


def _normalize_account_type(account_type):
    value = str(account_type or "STOCK").strip().upper()
    return value or "STOCK"


def _normalize_credit_trade_mode(requested_mode):
    value = str(requested_mode or AUTO_CREDIT_TRADE_MODE).strip().lower()
    return value or AUTO_CREDIT_TRADE_MODE


def _is_financing_subject(subject):
    if not subject:
        return False
    try:
        return int(subject.get("fin_status", 0)) == 48
    except (AttributeError, TypeError, ValueError):
        return False
