# -*- coding: utf-8 -*-


def match_candidate_to_trade(
    candidate,
    normalized_trade,
    max_window_seconds=300,
    *,
    allow_partial=False,
):
    if candidate["symbol"] != normalized_trade["symbol"]:
        return False
    if candidate["side"] != normalized_trade["side"]:
        return False
    candidate_quantity = int(candidate["quantity_delta"])
    trade_quantity = int(normalized_trade["quantity"])
    if allow_partial:
        if candidate_quantity < trade_quantity:
            return False
    elif candidate_quantity != trade_quantity:
        return False

    detected_at = int(candidate["detected_at"])
    trade_time = int(normalized_trade["trade_time"])
    return (
        detected_at
        <= trade_time
        <= int(candidate["pending_until"]) + max_window_seconds
    )
