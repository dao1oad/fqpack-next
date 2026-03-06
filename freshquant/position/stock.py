# coding: utf-8

from typing import Dict, List

from freshquant.data.astock.holding import get_stock_positions
from freshquant.database.mongodb import DBfreshquant


def query_stock_position_pct(virtual: bool = False) -> float:
    xt_assets = list(DBfreshquant.xt_assets.find({}))
    if len(xt_assets) > 0 and xt_assets[0].get("position_pct"):
        if virtual:
            frozen_cash = xt_assets[0].get("frozen_cash")
            market_value = xt_assets[0].get("market_value")
            total_asset = xt_assets[0].get("total_asset")
            return float((frozen_cash + market_value) / total_asset * 100)
        else:
            return float(xt_assets[0].get("position_pct"))
    return 0


def query_stock_positions() -> List[Dict]:
    """
    查询持仓的股票，包含债券和ETF
    """
    positions = get_stock_positions()
    for item in positions:
        quantity = item.get("quantity", 0)
        amount = abs(float(item.get("amount", 0)))
        item["price"] = round(amount / quantity, 2) if quantity else None
        item["exchange"] = (
            item["stock_code"].split(".")[-1] if item.get("stock_code") else ""
        )
        item["instrument_type"] = "stock"
        item["decimal_point"] = 2
    return positions


if __name__ == "__main__":
    print(query_stock_positions())
    print(query_stock_position_pct(True))
