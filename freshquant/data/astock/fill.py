import json
from typing import Optional

from bson import ObjectId
from prettytable import PrettyTable

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info, query_instrument_type
from freshquant.KlineDataTool import get_stock_data
from freshquant.order_management.manual.service import OrderManagementManualWriteService
from freshquant.order_management.projection.stock_fills_compat import (
    StockFillsCompatibilityService,
)
from freshquant.order_management.projection.stock_fills import build_raw_fills_view
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.quote.etf import queryEtfCandleSticks


def _get_manual_write_service():
    return OrderManagementManualWriteService()


def _get_stock_fills_compat_service():
    return StockFillsCompatibilityService()


def list_fill(code: Optional[str] = None, dt: Optional[str] = None):
    if code:
        repository = OrderManagementRepository()
        results = build_raw_fills_view(repository.list_trade_facts(code))
    else:
        collection = DBfreshquant.stock_fills
        query = {}
        if dt:
            query["date"] = int(dt.replace("-", "").replace(".", ""))

        fields = {
            "_id": 1,
            "op": 1,
            "symbol": 1,
            "stock_code": 1,
            "name": 1,
            "quantity": 1,
            "price": 1,
            "amount": 1,
            "date": 1,
            "time": 1,
        }
        results = list(collection.find(query, fields))

    table = PrettyTable()
    table.field_names = [
        "ID",
        "操作",
        "代码",
        "股票代码",
        "名称",
        "数量",
        "价格",
        "金额",
        "日期",
        "时间",
    ]

    for result in results:
        table.add_row(
            [
                result.get("_id"),
                result.get("op"),
                result.get("symbol"),
                result.get("stock_code"),
                result.get("name"),
                result.get("quantity"),
                round(float(result.get("price", 0)), 3),
                result.get("amount"),
                result.get("date"),
                result.get("time"),
            ]
        )

    print(table)

    if code and len(results) > 0:
        total_quantity = 0
        total_cost = 0.0
        current_quantity = 0
        current_cost = 0.0
        last_trade_price = 0.0
        stock_code = results[-1].get("stock_code") or query_instrument_info(code).get(
            "code"
        )
        for result in results:
            last_trade_price = float(result.get("price", 0))
            if result.get("op") == "买":
                total_quantity += int(result.get("quantity", 0))
                total_cost += float(result.get("amount", 0))
                if int(result.get("quantity", 0)) > 0:
                    current_quantity += int(result.get("quantity", 0))
                    current_cost += float(result.get("amount", 0))
            elif result.get("op") == "卖":
                total_quantity -= int(result.get("quantity", 0))
                total_cost -= float(result.get("amount", 0))
                if int(result.get("quantity", 0)) > 0:
                    current_quantity -= int(result.get("quantity", 0))
                    current_cost -= float(result.get("amount", 0))

        if total_quantity > 0:
            avg_price = total_cost / total_quantity
            print(
                f"当前持股数量: {total_quantity}, 占用资金: {round(total_cost, 2)}, 成本价: {round(avg_price, 3)}"
            )
            instrumentType = query_instrument_type(code.lower())
            if instrumentType == InstrumentType.STOCK_CN:
                get_instrument_data = get_stock_data
            elif instrumentType == InstrumentType.ETF_CN:
                get_instrument_data = queryEtfCandleSticks
            else:
                get_instrument_data = None
            if get_instrument_data is not None and stock_code:
                a = stock_code.split(".")
                if len(a) == 2:
                    kline_data = get_instrument_data(a[1] + a[0], "1m")
                    if len(kline_data) > 0 and last_trade_price > 0:
                        change_ratio = (
                            kline_data.close[-1] - last_trade_price
                        ) / last_trade_price
                        print(
                            f"当前价格: {kline_data.close[-1]}, 涨跌比率: {round(change_ratio * 100, 2)}%"
                        )
                        profit_ratio = (kline_data.close[-1] - avg_price) / avg_price
                        profit_amount = (
                            kline_data.close[-1] - avg_price
                        ) * total_quantity
                        print(
                            f"盈亏比率: {round(profit_ratio * 100, 2)}%, 累计盈亏金额: {round(profit_amount, 2)}"
                        )
                        if current_quantity > 0:
                            current_avg_price = current_cost / current_quantity
                            current_profit_amount = (
                                kline_data.close[-1] - current_avg_price
                            ) * current_quantity
                            print(f"当前盈亏金额: {round(current_profit_amount, 2)}")
        else:
            print(
                f"当前持股数量: {total_quantity}, 累计盈亏金额: {round(-total_cost, 2)}, 当前盈亏金额: {round(-current_cost, 2)}"
            )


def remove_fill(id=None, code=None):
    """Deprecated raw legacy mutator; prefer stock.fill rebuild/compare for compat maintenance."""
    if id is None and code is None:
        raise ValueError("必须提供id或code参数")

    collection = DBfreshquant.stock_fills
    query = {}

    if id is not None:
        query["_id"] = ObjectId(id)
    elif code is not None:
        query["symbol"] = code

    result = collection.delete_many(query)

    if result.deleted_count == 0:
        print("未找到匹配的记录")
    else:
        print(f"成功删除{result.deleted_count}条记录")


def import_fill(
    op: str,
    code: str,
    quantity: float,
    price: float,
    amount: float,
    dt: str,
):
    instrument = query_instrument_info(code)
    _get_manual_write_service().import_fill(
        op=op,
        code=code,
        quantity=quantity,
        price=price,
        amount=amount,
        dt=dt,
        instrument=instrument,
        source="manual_import",
    )
    print(f"成功导入{code}的{op}操作记录")
    list_fill(code)


def rebuild_fill_compat(*, code: Optional[str] = None, all_symbols: bool = False):
    service = _get_stock_fills_compat_service()
    if all_symbols:
        result = service.sync_symbols()
    else:
        if not code:
            raise ValueError("必须提供 code 或 all_symbols=True")
        normalized = str(code or "").strip()
        rows = service.sync_symbol(normalized)
        result = {
            "synced_symbols": [normalized],
            "rows_by_symbol": {normalized: len(rows)},
        }
    print(json.dumps(result, ensure_ascii=False, default=str))
    return result


def compare_fill_compat(code: str):
    result = _get_stock_fills_compat_service().compare_symbol(code)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return result
