"""Read-only inventory for Guardian Grid price/CAP configuration."""

from __future__ import annotations

import json

from freshquant.db import DBfreshquant
from freshquant.strategy.guardian_buy_grid import BUY_LEVELS


def classify(document):
    prices = [document.get(level) for level in BUY_LEVELS]
    caps = document.get("max_position_amounts")
    has_prices = any(value not in (None, "") for value in prices)
    if not has_prices:
        return None
    if not isinstance(caps, list) or len(caps) != 3:
        return "missing_caps"
    try:
        parsed_prices = [float(value) for value in prices]
        parsed_caps = [float(value) for value in caps]
    except (TypeError, ValueError):
        return "invalid_values"
    if not (parsed_prices[0] > parsed_prices[1] > parsed_prices[2] > 0):
        return "invalid_price_order"
    if any(value <= 0 for value in parsed_caps) or not (
        parsed_caps[0] <= parsed_caps[1] <= parsed_caps[2]
    ):
        return "invalid_cap_order"
    return None


def main():
    rows = []
    collection = DBfreshquant["guardian_buy_grid_configs"]
    for document in collection.find({}):
        issue = classify(document)
        if issue:
            rows.append(
                {
                    "code": document.get("code"),
                    "issue": issue,
                    "buy_prices": [document.get(level) for level in BUY_LEVELS],
                    "max_position_amounts": document.get("max_position_amounts"),
                }
            )
    print(json.dumps({"count": len(rows), "items": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
