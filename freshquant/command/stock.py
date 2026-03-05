import click
from QUANTAXIS.QASU.main import (
    QA_SU_save_stock_block,
    QA_SU_save_stock_day,
    QA_SU_save_stock_list,
    QA_SU_save_stock_min,
    QA_SU_save_stock_xdxr,
)
from typing import List, Tuple
from freshquant.data.astock import pre_pool
from freshquant.data.astock import pool
from freshquant.data.astock import must_pool
from freshquant.data.astock import fill
from freshquant.db import DBfreshquant
from datetime import datetime
import asyncio
import webbrowser
from freshquant.screening.strategies.clxs import ClxsStrategy
from freshquant.screening.strategies.chanlun_service import ChanlunServiceStrategy
from freshquant.trading.dt import query_current_trade_date, query_prev_trade_date
from freshquant.util.code import fq_util_code_append_market_code
from rich.table import Table
from rich.console import Console
from rich.padding import Padding

@click.group(name="stock.list")
def stock_list_command_group():
    pass

@stock_list_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_list_save_command(engine: str):
    QA_SU_save_stock_list(engine=engine)

@click.group(name="stock.block")
def stock_block_command_group():
    pass

@stock_block_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_block_save_command(engine: str):
    QA_SU_save_stock_block(engine=engine)

@click.group(name="stock.day")
def stock_day_command_group():
    pass

@stock_day_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_day_save_command(engine: str):
    QA_SU_save_stock_day(engine=engine)

@click.group(name="stock.min")
def stock_min_command_group():
    pass

@stock_min_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_min_save_command(engine: str):
    QA_SU_save_stock_min(engine=engine)

@click.group(name="stock.xdxr")
def stock_xdxr_command_group():
    pass

@stock_xdxr_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_xdxr_save_command(engine: str):
    QA_SU_save_stock_xdxr(engine=engine)

@click.group(name="stock")
def stock_command_group():
    pass

@stock_command_group.command(name="save")
@click.option("-e", "--engine", type=str, default="tdx")
def stock_save_command(engine: str, args: Tuple[str, ...] = ()):
    QA_SU_save_stock_list(engine=engine)
    # QA_SU_save_stock_block(engine=engine)
    QA_SU_save_stock_day(engine=engine)
    QA_SU_save_stock_min(engine=engine)
    QA_SU_save_stock_xdxr(engine=engine)

@stock_command_group.command(name="browse")
@click.argument("code")
@click.option("-p", "--period", type=str, default="1m", help="K线周期，如 1m/5m/15m/30m/1h/1d")
def stock_browse_command(code: str, period: str):
    """打开浏览器查看指定股票的K线图"""
    # 处理股票代码前缀
    code = fq_util_code_append_market_code(code)
    end_date = datetime.now().strftime("%Y-%m-%d")

    url = f"http://127.0.0.1/kline-big?symbol={code}&period={period}&endDate={end_date}"
    webbrowser.open(url)

@stock_command_group.command(name="screen")
@click.option("-d", "--days", type=int, default=1, help="扫描最近N天的信号")
@click.option("-c", "--code", type=str, default=None, help="股票代码（如 sh600000）")
@click.option("-p", "--period", type=str, default=None, help="单个周期（30m/60m/1d）")
@click.option("-wo", "--wave-opt", type=int, default=1560, help="CLXS 波动参数")
@click.option("-so", "--stretch-opt", type=int, default=0, help="CLXS 拉伸参数")
@click.option("-to", "--trend-opt", type=int, default=1, help="CLXS 趋势参数")
@click.option("-mo", "--model-opt", type=int, default=10001, help="CLXS 模型参数")
@click.argument("model", default="clxs")
def stock_screen_command(
    model: str,
    days: int = 1,
    code: str = None,
    period: str = None,
    wave_opt: int = 1560,
    stretch_opt: int = 0,
    trend_opt: int = 1,
    model_opt: int = 10001,
):
    """执行选股策略

    可用策略: clxs, chanlun
    """
    # 根据模型名称选择策略
    if model == "clxs":
        strategy = ClxsStrategy(
            wave_opt=wave_opt,
            stretch_opt=stretch_opt,
            trend_opt=trend_opt,
            model_opt=model_opt
        )
        asyncio.run(strategy.screen(days=days, code=code))
    elif model in ("chanlun", "chanlun_service"):
        strategy = ChanlunServiceStrategy(days=days)
        asyncio.run(strategy.screen(symbol=code, period=period))
    else:
        raise click.BadParameter(f"未知策略: {model}，可用策略: clxs, chanlun")

@click.group(name="stock.must-pool")
def stock_must_pool_command_group():
    pass

@stock_must_pool_command_group.command(name="list")
@click.option("--category", type=str, default=None, help="Category for fuzzy matching")
def stock_must_pool_list_command(category: str):
    list_stock_pool(category, "must-pool")

@stock_must_pool_command_group.command(name="copy")
@click.option("--category", type=str)
def stock_must_pool_copy_command(category: str):
    codes = must_pool.copy(category)
    click.echo(",".join(codes))
    click.echo(f"已复制{len(codes)}个股票代码到剪贴板")

@stock_must_pool_command_group.command(name="import")
@click.option("-c", "--code", type=str, required=True)
@click.option("-cat", "--category", type=str, required=True, default="自选股")
@click.option("-slp", "--stop-loss-price", type=float, required=True)
@click.option("-d", "--days", type=int, default=89)
@click.option("-ila", "--initial-lot-amount", type=float, help="第一次买入的金额")
@click.option("-la", "--lot-amount", type=float, help="每次买入的金额")
@click.option("--forever", type=bool, default=False)
def stock_must_pool_import_command(category: str, days: int, code: str,
                   stop_loss_price: float = None, initial_lot_amount: float = None, lot_amount: float = None, forever: bool = False):
    if not all([code, category, stop_loss_price]):
        raise ValueError("--code, --category, --stop_loss_price 参数必须提供")
    must_pool.import_pool(code, category, stop_loss_price, initial_lot_amount, lot_amount, forever)
    list_stock_pool(category, "must-pool")

@stock_must_pool_command_group.command(name="rm")
@click.option("--category", type=str)
@click.option("--code", "codes", type=str, multiple=True)
@click.option("--id", type=str)
def stock_must_pool_rm_command(category: str, codes: List[str], id: str):
    if not category and not codes and not id:
        raise click.UsageError("必须提供 --category 或 --code 或 --id 参数")
    if len(codes) > 0:
        # 将逗号分隔的字符串展开为多个code
        expanded_codes = []
        for code in codes:
            expanded_codes.extend([c.strip() for c in code.split(',') if c.strip()])
        codes = expanded_codes
    if id:
        must_pool.remove(id=id)
    else:
        must_pool.remove(category=category, codes=codes)
    list_stock_pool(category, "must-pool")

@stock_must_pool_command_group.command(name="update")
@click.argument("code", nargs=-1, required=False)
@click.option("--code", "codes", type=str, multiple=True, help="股票代码(支持多个或逗号分隔)")
@click.option("--set", "set_fields", type=str, multiple=True, help="设置的字段，格式为 field=value")
def stock_must_pool_update_command(code: Tuple[str], codes: List[str], set_fields: List[str]):
    """
    更新必买股票池中的股票字段值
    Args:
        codes (List[str]): 股票代码列表
        set_fields (List[str]): 字段名和字段值，格式为 field=value，可以更新的字段有：
            - lot_amount: 每次买入的金额
            - initial_lot_amount: 第一次买入的金额
            - forever: 是否永久交易
            - disabled: 是否禁用
            - stop_loss_price: 止损价格
            - category: 分类名称
    """
    # 合并位置参数和选项参数中的code
    all_codes = []
    if code:  # 处理位置参数
        all_codes.extend(code)
    if codes:  # 处理选项参数
        all_codes.extend(codes)

    if not all_codes:
        raise click.UsageError("必须提供至少一个股票代码(通过位置参数或--code选项)")
    if not set_fields:
        raise click.UsageError("必须提供--set参数来指定要更新的字段")

    # 解析设置字段（支持逗号分隔多个字段）
    update_fields = {}
    valid_fields = {'lot_amount', 'initial_lot_amount', 'forever', 'disabled', 'stop_loss_price', 'enabled', 'category'}

    # 展开所有用逗号分隔的字段
    all_fields = []
    for field_group in set_fields:
        all_fields.extend(f.strip() for f in field_group.split(',') if f.strip())

    for field in all_fields:
        if '=' not in field:
            raise click.BadParameter(f"无效的字段格式: {field}，应使用 field=value 格式（多个字段可用逗号分隔）")
        key, value = (s.strip() for s in field.split('=', 1))
        key = key.strip()
        if key not in valid_fields:
            raise click.BadParameter(f"无效字段: {key}，可用字段: {', '.join(valid_fields)}")

        # 类型转换
        if key in {'lot_amount', 'initial_lot_amount', 'stop_loss_price'}:
            try:
                value = float(value)
            except ValueError:
                raise click.BadParameter(f"{key} 需要浮点数")
        elif key in {'forever', 'disabled', 'enabled'}:
            value = value.lower() in ('true', '1', 'yes')

        # 处理enabled字段，转换为disabled
        if key == 'enabled':
            update_fields['disabled'] = not value
        else:
            update_fields[key] = value

    # 展开逗号分隔的code
    expanded_codes = []
    for c in all_codes:
        expanded_codes.extend([code.strip() for code in c.split(',') if code.strip()])

    # 执行更新
    result = DBfreshquant["must_pool"].update_many(
        {"code": {"$in": expanded_codes}},
        {"$set": {**update_fields, "updated_at": datetime.now()}}
    )

    click.echo(f"成功更新 {result.modified_count} 条记录")
    list_stock_pool(None, "must-pool")

@click.group(name="stock.pool")
def stock_pool_command_group():
    pass

@stock_pool_command_group.command(name="list")
@click.option("--category", type=str, default=None, help="Category for fuzzy matching")
def stock_pool_list_command(category: str):
    list_stock_pool(category, "pool")

@stock_pool_command_group.command(name="copy")
@click.option("--category", type=str)
def stock_pool_copy_command(category: str):
    codes = pool.copy(category)
    click.echo(",".join(codes))
    click.echo(f"已复制{len(codes)}个股票代码到剪贴板")

@stock_pool_command_group.command(name="import")
@click.option("-f", "--file", type=str)
@click.option("-cat", "--category", type=str, default="自选股")
@click.option("-d", "--days", type=int, default=89)
@click.option("-c", "--code", "codes", type=str, multiple=True)
def stock_pool_import_command(file: str, category: str, days: int, codes: List[str]):
    if not file and not codes:
        raise click.UsageError("必须提供 --file 或 --code 参数")
    pool.import_pool(file, category, days, codes)
    list_stock_pool(category, "pool")

@stock_pool_command_group.command(name="rm")
@click.option("--category", type=str)
@click.option("--code", "codes", type=str, multiple=True)
@click.option("--id", type=str)
def stock_pool_rm_command(category: str, codes: List[str], id: str):
    if not category and not codes and not id:
        raise click.UsageError("必须提供 --category 或 --code 或 --id 参数")
    if len(codes) > 0:
        # 将逗号分隔的字符串展开为多个code
        expanded_codes = []
        for code in codes:
            expanded_codes.extend([c.strip() for c in code.split(',') if c.strip()])
        codes = expanded_codes
    if id:
        pool.remove(id=id)
    else:
        pool.remove(category=category, codes=codes)
    list_stock_pool(category, "pool")

@click.group(name="stock.pre-pool")
def stock_pre_pool_command_group():
    pass

@stock_pre_pool_command_group.command(name="list")
@click.option("--category", type=str, default=None, help="Category for fuzzy matching")
def stock_pre_pool_list_command(category: str):
    list_stock_pool(category, "pre-pool")

@stock_pre_pool_command_group.command(name="copy")
@click.option("--category", type=str)
def stock_pre_pool_copy_command(category: str):
    codes = pre_pool.copy(category)
    click.echo(",".join(codes))
    click.echo(f"已复制{len(codes)}个股票代码到剪贴板")

@stock_pre_pool_command_group.command(name="import")
@click.option("-f", "--file", type=str)
@click.option("-cat", "--category", type=str)
@click.option("-d", "--days", type=int, default=89)
@click.option("-c", "--code", "codes", type=str, multiple=True)
def stock_pre_pool_import_command(file: str, category: str, days: int, codes: List[str]):
    pre_pool.import_pool(file, category, days, codes)
    list_stock_pool(category, "pre-pool")

@stock_pre_pool_command_group.command(name="rm")
@click.option("--category", type=str)
@click.option("--code", "codes", type=str, multiple=True)
@click.option("--id", type=str)
def stock_pre_pool_rm_command(category: str, codes: List[str], id: str):
    if not category and not codes and not id:
        raise click.UsageError("必须提供 --category 或 --code 或 --id 参数")
    if len(codes) > 0:
        # 将逗号分隔的字符串展开为多个code
        expanded_codes = []
        for code in codes:
            expanded_codes.extend([c.strip() for c in code.split(',') if c.strip()])
        codes = expanded_codes
    if id:
        pre_pool.remove(id=id)
    else:
        pre_pool.remove(category=category, codes=codes)
    list_stock_pool(category, "pre-pool")

def list_stock_pool(category: str, pool_name: str):

    query = {"category": {"$regex": category, "$options": "i"}} if category else {}
    if pool_name == "pre-pool":
        records = list(DBfreshquant["stock_pre_pools"].find(query).sort([('code', 1), ('datetime', 1)]))
    elif pool_name == "pool":
        records = list(DBfreshquant["stock_pools"].find(query).sort([('code', 1), ('datetime', 1)]))
    elif pool_name == "must-pool":
        records = list(DBfreshquant["must_pool"].find(query).sort([('code', 1)]))
    else:
        print("可用的资源类型: pre-pool, pool, must-pool")
        return

    # 创建Rich表格
    table = Table(show_header=True, header_style="bold magenta", show_lines=True,
                 title=f"{pool_name} 股票池", title_style="bold")

    # 定义列样式
    column_definitions = {
        "id": {"style": "dim", "overflow": "fold"},
        "code": {"overflow": "fold"},
        "name": {"overflow": "fold"},
        "category": {"overflow": "fold"},
        "instrument_type": {"overflow": "fold"},
        "lot_amount": {"justify": "right", "overflow": "fold"},
        "initial_lot_amount": {"justify": "right", "overflow": "fold"},
        "forever": {"justify": "center", "overflow": "fold"},
        "stop_loss_price": {"justify": "right", "overflow": "fold"},
        "disabled": {"justify": "center", "overflow": "fold"},
        "created_at": {"overflow": "fold"},
        "expire_at": {"overflow": "fold"}
    }

    # 字段名到中文的映射
    field_to_chinese = {
        "id": "ID",
        "code": "股票代码",
        "name": "股票名称",
        "category": "分类",
        "instrument_type": "类型",
        "lot_amount": "每次金额",
        "initial_lot_amount": "首次金额",
        "forever": "永久",
        "stop_loss_price": "止损价",
        "disabled": "禁用",
        "created_at": "创建时间",
        "expire_at": "过期时间"
    }

    # 根据池类型添加列
    if pool_name == "must-pool":
        fields = ['id', 'code', 'name', 'category', 'instrument_type',
                 'lot_amount', 'initial_lot_amount', 'forever', 'stop_loss_price', 'disabled', 'created_at']
    else:
        fields = ['id', 'code', 'name', 'category', 'created_at', 'expire_at']

    for field in fields:
        table.add_column(field_to_chinese[field], **column_definitions[field])

    # 添加数据行
    for record in records:
        row_data = []
        for field in fields:
            if field == "id":
                row_data.append(str(record.get('_id', "")))
            elif field == "created_at":
                dt = record.get('datetime') or record.get('created_at')
                if dt:
                    try:
                        dt = datetime.strftime(dt, '%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        dt = 'N/A'
                else:
                    dt = 'N/A'
                row_data.append(dt)
            elif field == "expire_at":
                expire = record.get('expire_at')
                if expire:
                    try:
                        expire = datetime.strftime(expire, '%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        expire = 'N/A'
                else:
                    expire = 'N/A'
                row_data.append(expire)
            elif field in ["lot_amount", "initial_lot_amount", "stop_loss_price"]:
                value = record.get(field)
                row_data.append(f"{value:.2f}" if value is not None else "N/A")
            elif field == "forever":
                value = record.get(field, False)
                row_data.append("是" if value else "否")
            elif field == "disabled":
                value = record.get(field, False)
                row_data.append("是" if value else "否")
            else:
                row_data.append(str(record.get(field, "N/A")))

        table.add_row(*row_data)

    # 打印表格
    console = Console()
    t = Padding(table, (1, 0, 0, 0))
    console.print(t)


@click.group(name="stock.fill")
def stock_fill_command_group():
    pass

@stock_fill_command_group.command(name="list")
@click.option("-c", "--code", type=str)
@click.option("-dt", "--date", type=str)
def stock_fill_list_command(code: str, date: str):
    fill.list_fill(code, date)

@stock_fill_command_group.command(name="rm")
@click.option("--id", type=str)
@click.option("--code", type=str)
def stock_fill_rm_command(id: str, code: str):
    if not id and not code:
        raise click.UsageError("必须提供 --id 或 --code 参数")
    if id:
        fill.remove_fill(id=id)
    else:
        fill.remove_fill(code=code)

@stock_fill_command_group.command(name="import")
@click.argument("op", type=click.Choice(["buy", "sell"]))
@click.argument("code", required=False)
@click.option("-c", "--code", "code_option", type=str)
@click.option("-q", "--quantity", type=int, required=True)
@click.option("-p", "--price", type=float, required=True)
@click.option("-a", "--amount", type=float)
@click.option("-dt", "--date", type=str)
def stock_fill_import_command(op: str, code: str, code_option: str, quantity: int, price: float, amount: float, date: str):
    # 合并code参数，优先使用--code选项
    code = code_option if code_option else code

    if not code:
        raise click.UsageError("必须提供股票代码，可以通过位置参数或--code选项")

    if not date:
        current_trade_date = query_current_trade_date()
        prev_trade_date = query_prev_trade_date()
        now = datetime.now()
        if current_trade_date.strftime('%Y-%m-%d') == now.strftime('%Y-%m-%d'):
            if now.time() >= datetime.strptime('09:25', '%H:%M').time() and now.time() <= datetime.strptime('11:30', '%H:%M').time():
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            elif now.time() > datetime.strptime('11:30', '%H:%M').time() and now.time() <= datetime.strptime('13:00', '%H:%M').time():
                dt = current_trade_date.strftime('%Y-%m-%d 11:30:00')
            elif now.time() > datetime.strptime('13:00', '%H:%M').time() and now.time() <= datetime.strptime('15:00', '%H:%M').time():
                dt = now.strftime('%Y-%m-%d %H:%M:%S')
            elif now.time() > datetime.strptime('15:00', '%H:%M').time():
                dt = current_trade_date.strftime('%Y-%m-%d 15:00:00')
            else:
                dt = prev_trade_date.strftime('%Y-%m-%d 15:00:00')
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
    fill.import_fill(op, code, quantity, price, amount, standardized_date)
