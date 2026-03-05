import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_future_day_all,
    QA_SU_save_future_list,
    QA_SU_save_future_min_all,
)
from freshquant.data.future import fill
from freshquant.trading.dt import query_current_trade_date, query_prev_trade_date
from datetime import datetime


@click.group(name="future")
def future_command_group():
    pass

@future_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def future_save_command(engine: str):
    try:
        QA_SU_save_future_list(engine)
        QA_SU_save_future_day_all(engine)
        QA_SU_save_future_min_all(engine)
    except Exception as e:
        click.echo(f"Error saving future: {str(e)}", err=True)

@click.group(name="future.list")
def future_list_command_group():
    pass

@future_list_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def future_list_save_command(engine):
    try:
        QA_SU_save_future_list(engine)
    except Exception as e:
        click.echo(f"Error saving list: {str(e)}", err=True)

@click.group(name="future.day")
def future_day_command_group():
    pass

@future_day_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def future_day_save_command(engine):
    try:
        QA_SU_save_future_day_all(engine)
    except Exception as e:
        click.echo(f"Error saving day: {str(e)}", err=True)

@click.group(name="future.min")
def future_min_command_group():
    pass

@future_min_command_group.command(name="save")
@click.option("--engine", type=str, default="tdx")
def future_min_save_command(engine):
    try:
        QA_SU_save_future_min_all(engine)
    except Exception as e:
        click.echo(f"Error saving min: {str(e)}", err=True)
        
@click.group(name="future.fill")
def future_fill_command_group():
    pass

@future_fill_command_group.command(name="list")
@click.option("-c", "--code", type=str)
@click.option("-dt", "--date", type=str)
def stock_fill_list_command(code: str, date: str):
    fill.list_fill(code, date)
    
@future_fill_command_group.command(name="rm")
@click.option("--id", type=str)
@click.option("--instrument-id", type=str)
def stock_fill_rm_command(id: str, instrument_id: str):
    if not id and not instrument_id:
        raise click.UsageError("必须提供 --id 或 --instrument-id 参数")
    if id:
        fill.remove_fill(id=id)
    else:
        fill.remove_fill(instrument_id=instrument_id)

@future_fill_command_group.command(name="import")
@click.argument("op", type=click.Choice(["buy_open", "sell_close", "sell_open", "buy_close"]))
@click.option("--instrument-id", type=str, required=True)
@click.option("-v", "--volume", type=int, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-dt", "--date", type=str)
def stock_fill_import_command(op: str, instrument_id: str, volume: int, price: float, date: str):
    if not date:
        current_trade_date = query_current_trade_date()
        prev_trade_date = query_prev_trade_date()
        now = datetime.now()
        current_time = now.time()
        
        # 定义交易时段
        night_start = datetime.strptime('21:00', '%H:%M').time()
        night_end = datetime.strptime('02:30', '%H:%M').time()
        morning_start = datetime.strptime('09:00', '%H:%M').time()
        morning_end = datetime.strptime('10:15', '%H:%M').time()
        morning_resume = datetime.strptime('10:30', '%H:%M').time()
        noon_end = datetime.strptime('11:30', '%H:%M').time()
        afternoon_start = datetime.strptime('13:30', '%H:%M').time()
        afternoon_end = datetime.strptime('15:00', '%H:%M').time()
        
        if current_trade_date.strftime('%Y-%m-%d') == now.strftime('%Y-%m-%d'):
            # 夜盘时段 (21:00-23:59)
            if current_time >= night_start:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            # 日盘时段
            elif current_time >= morning_start and current_time <= morning_end:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            elif current_time > morning_end and current_time < morning_resume:
                dt = current_trade_date.strftime('%Y-%m-%d 10:15:00')
            elif current_time >= morning_resume and current_time <= noon_end:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            elif current_time > noon_end and current_time < afternoon_start:
                dt = current_trade_date.strftime('%Y-%m-%d 11:30:00')
            elif current_time >= afternoon_start and current_time <= afternoon_end:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            elif current_time > afternoon_end:
                dt = current_trade_date.strftime('%Y-%m-%d 15:00:00')
            # 凌晨夜盘时段 (00:00-02:30)
            elif current_time <= night_end:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            else:
                dt = prev_trade_date.strftime('%Y-%m-%d 15:00:00')
        else:
            # 非交易日，检查是否在凌晨夜盘时段
            if current_time <= night_end:
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            else:
                dt = prev_trade_date.strftime('%Y-%m-%d 15:00:00')
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
