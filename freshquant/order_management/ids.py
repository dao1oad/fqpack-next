# -*- coding: utf-8 -*-

from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def new_request_id() -> str:
    return _new_id("req")


def new_internal_order_id() -> str:
    return _new_id("ord")


def new_trade_fact_id() -> str:
    return _new_id("trade")


def new_execution_fill_id() -> str:
    return _new_id("fill")


def new_event_id() -> str:
    return _new_id("evt")


def new_reconciliation_gap_id() -> str:
    return _new_id("gap")


def new_reconciliation_resolution_id() -> str:
    return _new_id("resolution")


def new_position_entry_id() -> str:
    return _new_id("entry")


def new_entry_slice_id() -> str:
    return _new_id("entryslice")


def new_buy_lot_id() -> str:
    return _new_id("lot")


def new_lot_slice_id() -> str:
    return _new_id("slice")


def new_allocation_id() -> str:
    return _new_id("alloc")


def new_candidate_id() -> str:
    return _new_id("candidate")


def new_stoploss_binding_id() -> str:
    return _new_id("stoploss")
