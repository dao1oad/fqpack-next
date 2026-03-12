from datetime import datetime

import pydash

from freshquant.config import cfg
from freshquant.database.cache import redis_cache
from freshquant.trading.dt import fq_trading_fetch_trade_dates


@redis_cache.memoize(expiration=86400)
def tool_trade_date_hist_sina():
    return fq_trading_fetch_trade_dates(source="sina")


@redis_cache.memoize(expiration=15)
def tool_trade_date_seconds_to_start():
    seconds = 0
    trade_dates = tool_trade_date_hist_sina()
    trade_dates = trade_dates["trade_date"]
    now = datetime.now()
    trade_dates = pydash.filter_(
        trade_dates,
        lambda trade_date: trade_date.strftime(cfg.DT_FORMAT_DAY)
        >= now.strftime(cfg.DT_FORMAT_DAY),
    )
    if len(trade_dates) > 0:
        dt = trade_dates[0]
        dt1 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=9, minute=25)
        dt2 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=11, minute=35)
        dt3 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=12, minute=55)
        dt4 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=15, minute=5)
        if now < dt1:
            seconds = dt1.timestamp() - now.timestamp()
        elif dt2 < now < dt3:
            seconds = dt3.timestamp() - now.timestamp()
        elif now > dt4:
            dt = trade_dates[1] if len(trade_dates) > 1 else None
            if dt is not None:
                dt1 = datetime(
                    year=dt.year, month=dt.month, day=dt.day, hour=9, minute=25
                )
                seconds = dt1.timestamp() - now.timestamp()
    else:
        seconds = 3600
    return seconds


@redis_cache.memoize(expiration=15)
def tool_trade_date_last():
    """
    返回最近一个交易日
    如果当天是交易日，则返回当天；否则返回前一个交易日
    """
    trade_dates = tool_trade_date_hist_sina()["trade_date"]
    today = datetime.now().date()

    # 转换为date类型的列表（兼容datetime和date类型）
    trade_date_list = [td for td in trade_dates]

    # 如果今天是交易日，返回今天
    if today in trade_date_list:
        return today

    # 否则找到最近的前一个交易日
    for td in reversed(trade_date_list):
        if td < today:
            return td

    return None


@redis_cache.memoize(expiration=15)
def get_trade_dates_between(start_date, end_date):
    """
    获取指定开始日期和结束日期之间的交易日期（包含开始和结束日期）

    Args:
        start_date: 开始日期，可以是字符串（'YYYY-MM-DD'）或datetime对象
        end_date: 结束日期，可以是字符串（'YYYY-MM-DD'）或datetime对象

    Returns:
        list: 包含开始和结束日期在内的交易日期列表，格式为 datetime.date 对象列表

    Raises:
        ValueError: 当开始日期晚于结束日期时抛出异常
    """
    # 转换输入参数为date对象
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    elif isinstance(start_date, datetime):
        start_date = start_date.date()

    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    elif isinstance(end_date, datetime):
        end_date = end_date.date()

    # 检查日期范围的有效性
    if start_date > end_date:
        raise ValueError(f"开始日期 {start_date} 不能晚于结束日期 {end_date}")

    # 获取所有交易日期
    trade_dates = tool_trade_date_hist_sina()["trade_date"]

    # 筛选指定范围内的交易日期
    result_dates = []
    for trade_date in trade_dates:
        if start_date <= trade_date <= end_date:
            result_dates.append(trade_date)

    return result_dates


if __name__ == "__main__":
    print(tool_trade_date_last())

    # 测试新函数
    print(get_trade_dates_between('2024-01-01', '2024-01-31'))
