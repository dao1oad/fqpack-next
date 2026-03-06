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


def new_event_id() -> str:
    return _new_id("evt")


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
