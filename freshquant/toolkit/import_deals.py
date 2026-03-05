# coding: utf-8

import argparse

import pandas as pd
from loguru import logger

from freshquant.database.mongodb import DBfreshquant


def main():
    parser = argparse.ArgumentParser(description="import deals")
    parser.add_argument(
        "--file",
        type=str,
        required=False,
        help="file to import",
    )
    args = parser.parse_args()
    args.file
    df = pd.read_excel(args.file)
    for _, row in df.iterrows():
        date = row['成交日期']
        time = row['成交时间']
        op = row['操作']
        price = row['成交价格']
        symbol = str(row['证券代码'])
        # symbol补全6位
        symbol = symbol.zfill(6)
        stock_code = symbol + ('.SZ' if row['交易市场'] == '深A' else '.SH')
        name = row['证券名称']
        quantity = row['成交数量']
        amount = row['成交金额']
        source = 'deal'
        logger.info((date, time, op, price, symbol, stock_code, name, quantity, source))
        DBfreshquant['stock_fills'].update_one(
            {
                "date": date,
                "time": time,
                "symbol": symbol,
                "op": op,
            },
            {
                "$set": {
                    "date": date,
                    "time": time,
                    "symbol": symbol,
                    "stock_code": stock_code,
                    "name": name,
                    "op": op,
                    "quantity": quantity,
                    "price": price,
                    "amount": amount,
                    "source": source,
                }
            },
            upsert=True,
        )


if __name__ == '__main__':
    main()
