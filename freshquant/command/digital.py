from datetime import datetime

import click

from freshquant.data.digital import fill


@click.group(name="digital.fill")
def digital_fill_command_group():
    pass


@digital_fill_command_group.command(name="list")
@click.option("-c", "--code", type=str)
@click.option("-dt", "--date", type=str)
def digital_fill_list_command(code: str, date: str):
    fill.list_fill(code, date)


@digital_fill_command_group.command(name="rm")
@click.option("--id", type=str)
@click.option("--instrument-id", type=str)
def digital_fill_rm_command(id: str, instrument_id: str):
    if not id and not instrument_id:
        raise click.UsageError("必须提供 --id 或 --instrument-id 参数")
    if id:
        fill.remove_fill(id=id)
    else:
        fill.remove_fill(instrument_id=instrument_id)


@digital_fill_command_group.command(name="import")
@click.argument("op", type=click.Choice(["buy_open", "sell_close", "sell_open", "buy_close"]))
@click.option("--instrument-id", type=str, required=True)
@click.option("-v", "--volume", type=float, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-dt", "--date", type=str)
def digital_fill_import_command(op: str, instrument_id: str, volume: float, price: float, date: str):
    # 数字货币市场24小时交易，没有提供日期时直接使用当前时间
    if not date:
        dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    else:
        dt = date

    # 尝试解析多种日期格式
    date_formats = [
        '%Y-%m-%d %H:%M:%S',  # 标准格式
        '%Y/%m/%d %H:%M:%S',  # 斜杠分隔
        '%Y%m%d %H%M%S',      # 紧凑格式
        '%Y-%m-%d %H:%M',     # 不带秒
        '%Y-%m-%d',           # 仅日期
        '%Y/%m/%d',           # 斜杠分隔仅日期
        '%Y%m%d',             # 紧凑格式仅日期
        '%H:%M:%S',           # 仅时间
        '%H:%M'               # 仅时间不带秒
    ]

    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(dt, fmt)
            break
        except ValueError:
            continue

    if not parsed_date:
        raise ValueError("无法解析日期格式，请使用以下格式之一：\n" +
                        "YYYY-MM-DD HH:MM:SS\n" +
                        "YYYY/MM/DD HH:MM:SS\n" +
                        "YYYYMMDD HHMMSS\n" +
                        "YYYY-MM-DD HH:MM\n" +
                        "YYYY-MM-DD\n" +
                        "YYYY/MM/DD\n" +
                        "YYYYMMDD\n" +
                        "HH:MM:SS\n" +
                        "HH:MM")

    # 如果只提供了时间，则使用当天日期
    if not any(c in dt for c in ['-', '/']):  # 没有日期部分
        today = datetime.now().strftime('%Y-%m-%d')
        parsed_date = datetime.strptime(f"{today} {parsed_date.strftime('%H:%M:%S')}", '%Y-%m-%d %H:%M:%S')

    # 标准化日期格式
    standardized_date = parsed_date.strftime('%Y-%m-%d %H:%M:%S')
    fill.import_fill(op, instrument_id, volume, price, standardized_date)
