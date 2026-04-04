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
    strategy_context=None,
    trace_id=None,
    intent_id=None,
):
    normalized_symbol = normalize_to_base_code(symbol)
    strategy_name = _resolve_guardian_strategy_name()
    payload = {
        "action": action,
        "symbol": normalized_symbol,
        "price": price,
        "quantity": quantity,
        "source": "strategy",
        "strategy_name": strategy_name,
        "remark": remark,
        "strategy_context": strategy_context,
        "trace_id": trace_id,
        "intent_id": intent_id,
    }
    if is_profitable is not None:
        payload["position_management_is_profitable"] = bool(is_profitable)
    result = _get_order_submit_service().submit_order(payload)
    _mark_guardian_buy_grid_after_accept(
        action=action,
        symbol=normalized_symbol,
        strategy_context=strategy_context,
    )
    return result


def _resolve_guardian_strategy_name():
    try:
        from freshquant.ordering.general import query_strategy_id

        return query_strategy_id("Guardian")
    except Exception:
        return "Guardian"


def _get_guardian_buy_grid_service():
    from freshquant.strategy.guardian_buy_grid import get_guardian_buy_grid_service

    return get_guardian_buy_grid_service()


def _mark_guardian_buy_grid_after_accept(*, action, symbol, strategy_context):
    if str(action).lower() != "buy":
        return
    context = dict(strategy_context or {})
    guardian_buy_grid = dict(context.get("guardian_buy_grid") or {})
    hit_levels = list(guardian_buy_grid.get("hit_levels") or [])
    if not hit_levels:
        return
    _get_guardian_buy_grid_service().mark_buy_order_accepted(
        symbol,
        hit_levels=hit_levels,
        grid_level=guardian_buy_grid.get("grid_level"),
        source_price=guardian_buy_grid.get("source_price"),
        signal_time=guardian_buy_grid.get("signal_time"),
    )
