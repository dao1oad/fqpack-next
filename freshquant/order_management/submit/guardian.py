# -*- coding: utf-8 -*-

from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.util.code import normalize_to_base_code


def _get_order_submit_service():
    return OrderSubmitService()


def submit_guardian_order(action, symbol, price, quantity, remark=None):
    strategy_name = _resolve_guardian_strategy_name()
    return _get_order_submit_service().submit_order(
        {
            "action": action,
            "symbol": normalize_to_base_code(symbol),
            "price": price,
            "quantity": quantity,
            "source": "strategy",
            "strategy_name": strategy_name,
            "remark": remark,
        }
    )


def _resolve_guardian_strategy_name():
    try:
        from freshquant.ordering.general import query_strategy_id

        return query_strategy_id("Guardian")
    except Exception:
        return "Guardian"
