# coding: utf-8

import argparse

import pandas as pd
from loguru import logger

from freshquant.order_management.manual.service import OrderManagementManualWriteService


def _get_manual_write_service():
    return OrderManagementManualWriteService()


def _normalize_op(op):
    value = str(op).strip()
    if value in {"买", "买入", "buy", "BUY"}:
        return "buy"
    if value in {"卖", "卖出", "sell", "SELL"}:
        return "sell"
    return value


def main():
    parser = argparse.ArgumentParser(description="import deals")
    parser.add_argument(
        "--file",
        type=str,
        required=False,
        help="file to import",
    )
    args = parser.parse_args()
    df = pd.read_excel(args.file)
    service = _get_manual_write_service()
    for _, row in df.iterrows():
        date = row["成交日期"]
        time = row["成交时间"]
        op = _normalize_op(row["操作"])
        price = row["成交价格"]
        symbol = str(row["证券代码"]).zfill(6)
        stock_code = symbol + (".SZ" if row["交易市场"] == "深A" else ".SH")
        name = row["证券名称"]
        quantity = row["成交数量"]
        amount = row["成交金额"]
        source = "deal"
        logger.info((date, time, op, price, symbol, stock_code, name, quantity, source))
        service.import_fill(
            op=op,
            code=symbol,
            quantity=quantity,
            price=price,
            amount=amount,
            dt=f"{date} {time}",
            instrument={"name": name, "stock_code": stock_code},
            source=source,
        )


if __name__ == "__main__":
    main()
