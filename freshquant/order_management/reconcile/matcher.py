# -*- coding: utf-8 -*-


def match_candidate_to_trade(candidate, normalized_trade, max_window_seconds=300):
    if candidate["symbol"] != normalized_trade["symbol"]:
        return False
    if candidate["side"] != normalized_trade["side"]:
        return False
    if int(candidate["quantity_delta"]) != int(normalized_trade["quantity"]):
        return False

    detected_at = int(candidate["detected_at"])
    trade_time = int(normalized_trade["trade_time"])
    return (
        detected_at
        <= trade_time
        <= int(candidate["pending_until"]) + max_window_seconds
    )
