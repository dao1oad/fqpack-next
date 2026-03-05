# -*- coding: utf-8 -*-

from datetime import datetime

import akshare as ak
import pydash
from fqxtrade.config import cfg
from fqxtrade.database.cache import redis_cache


@redis_cache.memoize(expiration=86400)
def tool_trade_date_hist_sina():
    return ak.tool_trade_date_hist_sina()


@redis_cache.memoize(expiration=900)
def toolCurrentTradeDate():
    trade_dates = tool_trade_date_hist_sina()
    trade_dates = trade_dates["trade_date"]
    now = datetime.now()
    return pydash.filter_(
        trade_dates,
        lambda trade_date: trade_date.strftime(cfg.DT_FORMAT_DAY)
        >= now.strftime(cfg.DT_FORMAT_DAY),
    )


def tool_trade_date_seconds_to_start():
    seconds = 0
    now = datetime.now()
    trade_dates = toolCurrentTradeDate()
    if len(trade_dates) > 0:
        dt = trade_dates[0]
        dt1 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=9, minute=15)
        dt2 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=11, minute=45)
        dt3 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=12, minute=45)
        dt4 = datetime(year=dt.year, month=dt.month, day=dt.day, hour=15, minute=15)
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
