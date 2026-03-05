# coding: utf-8

import pickle
from typing import Dict, List, Union

import numpy as np
import pandas as pd

from freshquant.database.mongodb import DBfreshquant
from freshquant.instrument.general import query_instrument_info


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
    records = pd.DataFrame(
        list(DBfreshquant.stock_fills.find({}).sort([("date", 1), ("time", 1)]))
    )

    def func(group):
        stock_code: str = ''
        name: str = ''
        amount: float = 0.0
        quantity: int = 0
        price: float = np.nan
        for _, row in group.iterrows():
            stock_code = row['stock_code']
            name = row['name']
            if '买' in row['op']:
                quantity = quantity + row['quantity']
                amount = amount + row['amount']
            elif '卖' in row['op']:
                quantity = quantity - row['quantity']
                amount = amount - row['amount']
        instrument_info = query_instrument_info(stock_code)
        decimal_point = instrument_info.get('decimal_point', 2)
        sse = instrument_info.get('sse', '')
        instrument_type = instrument_info.get('sec', '')
        if quantity > 0:
            price = round(amount / quantity, decimal_point)
        if quantity > 0 or amount > 0:
            return pd.DataFrame(
                {
                    'stock_code': [stock_code],
                    'name': [name],
                    'amount': [amount],
                    'quantity': [quantity],
                    'price': [price],
                    'decimal_point': [decimal_point],
                    'instrument_type': [instrument_type],
                    'exchange': [sse],
                }
            )
        else:
            return None

    return (
        records.groupby('stock_code')
        .apply(func)
        .reset_index(drop=True)
        .to_dict(orient="records")
    )


if __name__ == "__main__":
    print(query_stock_positions())
    print(query_stock_position_pct(True))
