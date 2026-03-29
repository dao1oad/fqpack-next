from bson import ObjectId
from rich.console import Console
from rich.table import Table

from freshquant.db import DBfreshquant
from freshquant.instrument.code import convert_code_to_tdx, convert_code_to_tq
from freshquant.instrument.general import query_instrument_info
from freshquant.KlineDataTool import (
    get_future_data_v2,
)
from freshquant.order_management.time_helpers import beijing_datetime_from_epoch


def list_fill(instrument_id: str = None, dt: str = None):
    collection = DBfreshquant.future_fills
    query = {}
    if instrument_id:
        instrument_id = convert_code_to_tq(instrument_id)
        query['instrument_id'] = instrument_id
    if dt:
        query['date'] = int(dt.replace('-', '').replace('.', ''))

    fields = {
        '_id': 1,
        'direction': 1,
        'offset': 1,
        'instrument_id': 1,
        'volume': 1,
        'price': 1,
        'trade_date_time': 1,
    }

    results = list(collection.find(query, fields))

    # 创建Rich表格
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim")
    table.add_column("方向")
    table.add_column("操作")
    table.add_column("代码")
    table.add_column("数量")
    table.add_column("价格")
    table.add_column("时间")

    for result in results:
        # 将时间戳转换为可读的日期时间格式
        readable_time = beijing_datetime_from_epoch(result['trade_date_time']).strftime(
            '%Y-%m-%d %H:%M:%S'
        )
        table.add_row(
            str(result['_id']),
            result['direction'],
            result['offset'],
            result['instrument_id'],
            str(result['volume']),
            f"{float(result['price']):.3f}",
            readable_time,  # 使用转换后的时间
        )

    # 创建控制台实例并打印表格
    console = Console()
    console.print(table)

    if instrument_id and len(results) > 0:
        total_long_quantity = 0
        total_short_quantity = 0
        total_long_cost = 0.0
        total_short_cost = 0.0
        last_trade_price = 0.0

        for result in results:
            last_trade_price = result['price']
            if result['direction'] == 'BUY' and result['offset'] == 'OPEN':
                total_long_quantity += result['volume']
                total_long_cost += result['volume'] * result['price']
            elif result['direction'] == 'SELL' and result['offset'] == 'CLOSE':
                total_long_quantity -= result['volume']
                total_long_cost -= result['volume'] * result['price']
            elif result['direction'] == 'SELL' and result['offset'] == 'OPEN':
                total_short_quantity += result['volume']
                total_short_cost += result['volume'] * result['price']
            elif result['direction'] == 'BUY' and result['offset'] == 'CLOSE':
                total_short_quantity -= result['volume']
                total_short_cost -= result['volume'] * result['price']

        if total_long_quantity > 0:
            avg_long_price = total_long_cost / total_long_quantity
            print(
                f"当前多头持仓数量: {total_long_quantity}, 占用资金: {round(total_long_cost, 2)}, 成本价: {round(avg_long_price, 3)}"
            )
            kline_data = get_future_data_v2(convert_code_to_tdx(instrument_id), "1m")
            if len(kline_data) > 0:
                change_ratio = (
                    kline_data.close[-1] - last_trade_price
                ) / last_trade_price
                print(
                    f"当前价格: {kline_data.close[-1]}, 涨跌比率: {round(change_ratio * 100, 2)}%"
                )
                profit_ratio = (kline_data.close[-1] - avg_long_price) / avg_long_price
                profit_amount = (
                    kline_data.close[-1] - avg_long_price
                ) * total_long_quantity
                print(
                    f"盈亏比率: {round(profit_ratio * 100, 2)}%, 盈亏金额: {round(profit_amount, 2)}"
                )
        else:
            print(
                f"当前多头持仓数量: {total_long_quantity}, 盈亏金额: {round(-total_long_cost, 2)}"
            )

        if total_short_quantity > 0:
            avg_short_price = total_short_cost / total_short_quantity
            print(
                f"当前空头持仓数量: {total_short_quantity}, 占用资金: {round(total_short_cost, 2)}, 成本价: {round(avg_short_price, 3)}"
            )
            kline_data = get_future_data_v2(convert_code_to_tdx(instrument_id), "1m")
            if len(kline_data) > 0:
                change_ratio = (
                    kline_data.close[-1] - last_trade_price
                ) / last_trade_price
                print(
                    f"当前价格: {kline_data.close[-1]}, 涨跌比率: {round(change_ratio * 100, 2)}%"
                )
                profit_ratio = (
                    avg_short_price - kline_data.close[-1]
                ) / avg_short_price
                profit_amount = (
                    avg_short_price - kline_data.close[-1]
                ) * total_short_quantity
                print(
                    f"盈亏比率: {round(profit_ratio * 100, 2)}%, 盈亏金额: {round(profit_amount, 2)}"
                )
        else:
            print(
                f"当前空头持仓数量: {total_short_quantity}, 盈亏金额: {round(-total_short_cost, 2)}"
            )
        print("这是没有考虑杠杆的情况，只做参考，以后会考虑算入杠杆的情况")


def remove_fill(id=None, instrument_id=None):
    if id is None and instrument_id is None:
        raise ValueError("必须提供id或instrument_id参数")

    collection = DBfreshquant.future_fills
    query = {}

    if id is not None:
        query['_id'] = ObjectId(id)
    elif instrument_id is not None:
        instrument_id = convert_code_to_tq(instrument_id)
        query['instrument_id'] = instrument_id

    result = collection.delete_many(query)

    if result.deleted_count == 0:
        print("未找到匹配的记录")
    else:
        print(f"成功删除{result.deleted_count}条记录")


def import_fill(op: str, instrument_id: str, volume: float, price: float, dt: str):
    instrument = query_instrument_info(convert_code_to_tdx(instrument_id))
    instrument_id = convert_code_to_tq(instrument_id)
    if instrument is None:
        raise ValueError(f"未找到代码为 {instrument_id} 的期货合约信息")
    # op的输入是buy_open, sell_close, sell_open, buy_close，
    # 要按_拆分，前面就是direction，后面就是offset，并且转成大写
    direction, offset = op.split("_")
    direction = direction.upper()
    offset = offset.upper()

    # 把dt转成时间戳timestamp，保存在trade_date_time字段
    trade_date_time = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S').timestamp()

    # 构建插入文档
    document = {
        'instrument_id': instrument_id,
        'direction': direction,
        'offset': offset,
        'name': instrument.get("name"),
        'volume': volume,
        'price': price,
        'trade_date_time': trade_date_time,
    }

    # 插入数据库
    DBfreshquant.future_fills.insert_one(document)
    print(f"成功导入{instrument_id}的{op}操作记录")
    list_fill(instrument_id)
