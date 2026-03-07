# -*- coding: utf-8 -*-

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code


def _get_order_submit_service():
    return OrderSubmitService()


def submit_guardian_order(
    action,
    symbol,
    price,
    quantity,
    remark=None,
    is_profitable=None,
):
    strategy_name = _resolve_guardian_strategy_name()
    payload = {
        "action": action,
        "symbol": normalize_to_base_code(symbol),
        "price": price,
        "quantity": quantity,
        "source": "strategy",
        "strategy_name": strategy_name,
        "remark": remark,
    }
    if is_profitable is not None:
        payload["position_management_is_profitable"] = bool(is_profitable)
    return _get_order_submit_service().submit_order(payload)


def _resolve_guardian_strategy_name():
    try:
        from freshquant.ordering.general import query_strategy_id

        return query_strategy_id("Guardian")
    except Exception:
        return "Guardian"
