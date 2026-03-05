from bson import ObjectId
from prettytable import PrettyTable

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info, query_instrument_type
from freshquant.KlineDataTool import (
    get_stock_data,
)
from freshquant.quote.etf import queryEtfCandleSticks


def list_fill(code: str = None, dt: str = None):
    collection = DBfreshquant.stock_fills

    query = {}
    if code:
        query['symbol'] = code
    if dt:
        query['date'] = int(dt.replace('-', '').replace('.', ''))

    fields = {
        '_id': 1,
        'op': 1,
        'symbol': 1,
        'stock_code': 1,
        'name': 1,
        'quantity': 1,
        'price': 1,
        'amount': 1,
        'date': 1,
        'time': 1,
    }

    results = list(collection.find(query, fields))

    table = PrettyTable()
    table.field_names = [
        'ID',
        '操作',
        '代码',
        '股票代码',
        '名称',
        '数量',
        '价格',
        '金额',
        '日期',
        '时间',
    ]

    for result in results:
        table.add_row(
            [
                result['_id'],
                result['op'],
                result['symbol'],
                result['stock_code'],
                result['name'],
                result['quantity'],
                round(result['price'], 3),
                result['amount'],
                result['date'],
                result['time'],
            ]
        )

    print(table)

    if code and len(results) > 0:
        total_quantity = 0
        total_cost = 0.0
        current_quantity = 0
        current_cost = 0.0
        last_trade_price = 0.0
        for result in results:
            stock_code = result['stock_code']
            last_trade_price = result['price']
            if result['op'] == '买':
                total_quantity += result['quantity']
                if result['quantity'] > 0 and result['price'] > 0:
                    total_cost += result['quantity'] * result['price']
                else:
                    total_cost += result['amount']
                # 当前盈亏计算：排除 quantity=0 的记录
                if result['quantity'] > 0:
                    current_quantity += result['quantity']
                    if result['price'] > 0:
                        current_cost += result['quantity'] * result['price']
                    else:
                        current_cost += result['amount']
            elif result['op'] == '卖':
                total_quantity -= result['quantity']
                total_cost -= result['quantity'] * result['price']
                # 当前盈亏计算：排除 quantity=0 的记录
                if result['quantity'] > 0:
                    current_quantity -= result['quantity']
                    current_cost -= result['quantity'] * result['price']

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
            a = stock_code.split(".")
            kline_data = get_instrument_data(a[1] + a[0], "1m")
            if len(kline_data) > 0:
                change_ratio = (
                    kline_data.close[-1] - last_trade_price
                ) / last_trade_price
                print(
                    f"当前价格: {kline_data.close[-1]}, 涨跌比率: {round(change_ratio * 100, 2)}%"
                )
                profit_ratio = (kline_data.close[-1] - avg_price) / avg_price
                profit_amount = (kline_data.close[-1] - avg_price) * total_quantity
                print(
                    f"盈亏比率: {round(profit_ratio * 100, 2)}%, 累计盈亏金额: {round(profit_amount, 2)}"
                )
                # 当前盈亏金额计算（排除 quantity=0 的记录）
                if current_quantity > 0:
                    current_avg_price = current_cost / current_quantity
                    current_profit_amount = (kline_data.close[-1] - current_avg_price) * current_quantity
                    print(
                        f"当前盈亏金额: {round(current_profit_amount, 2)}"
                    )
        else:
            print(f"当前持股数量: {total_quantity}, 累计盈亏金额: {round(-total_cost, 2)}, 当前盈亏金额: {round(-current_cost, 2)}")


def remove_fill(id=None, code=None):
    if id is None and code is None:
        raise ValueError("必须提供id或code参数")

    collection = DBfreshquant.stock_fills
    query = {}

    if id is not None:
        query['_id'] = ObjectId(id)
    elif code is not None:
        query['symbol'] = code

    result = collection.delete_many(query)

    if result.deleted_count == 0:
        print("未找到匹配的记录")
    else:
        print(f"成功删除{result.deleted_count}条记录")


def import_fill(op: str, code: str, quantity: float, price: float, amount: float, dt: str):
    # 获取股票名称
    instrument = query_instrument_info(code)
    stock_code = f'{instrument.get("code")}.{instrument.get("sse")}'.upper()
    # 生成当前时间
    a = dt.split(" ")
    date = a[0]
    time = a[1]

    if op == 'buy':
        op_chinese = '买'
    elif op == 'sell':
        op_chinese = '卖'
    else:
        raise ValueError("op参数必须是'buy'或'sell'")
    # 构建插入文档
    document = {
        'op': op_chinese,
        'symbol': code,
        'stock_code': stock_code,
        'name': instrument.get("name"),
        'quantity': quantity,
        'price': price,
        'amount': amount if amount is not None else quantity * price,
        'date': int(date.replace("-", "").replace("/", "")),
        'time': time,
        'source': "import",
    }

    # 插入数据库
    DBfreshquant.stock_fills.insert_one(document)
    print(f"成功导入{code}的{op}操作记录")
    list_fill(code)
