# -*- coding: utf-8 -*-

from datetime import datetime, timezone


def build_credit_subject_document(subject, account_id=None, updated_at=None):
    instrument_id = str(getattr(subject, "instrument_id", "") or "").strip().upper()
    if not instrument_id:
        raise ValueError("instrument_id is required")

    symbol, exchange = split_instrument_id(instrument_id)
    exchange_id = str(getattr(subject, "exchange_id", "") or exchange).strip().upper()
    return {
        "instrument_id": instrument_id,
        "symbol": symbol,
        "exchange": exchange_id or exchange,
        "account_id": _normalize_account_id(account_id),
        "fin_status": getattr(subject, "fin_status", None),
        "slo_status": getattr(subject, "slo_status", None),
        "fin_ratio": getattr(subject, "fin_ratio", None),
        "slo_ratio": getattr(subject, "slo_ratio", None),
        "updated_at": updated_at or _utc_now_iso(),
    }


def split_instrument_id(instrument_id):
    raw_value = str(instrument_id or "").strip().upper()
    if not raw_value:
        raise ValueError("instrument_id is required")
    if "." not in raw_value:
        return raw_value, ""
    symbol, exchange = raw_value.split(".", 1)
    return symbol, exchange


def _normalize_account_id(account_id):
    value = str(account_id or "").strip()
    return value or None


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
