# -*- coding: utf-8 -*-

from datetime import date, datetime
from typing import Optional

import akshare as ak
import pydash
import pandas as pd
from freshquant.carnation.config import DT_FORMAT_DAY
from freshquant.database.cache import redis_cache


@redis_cache.memoize(expiration=86400)
def fq_trading_fetch_trade_dates(source="sina") -> pd.DataFrame:
    if source == "sina":
        return ak.tool_trade_date_hist_sina()
    return ak.tool_trade_date_hist_sina()


def query_current_trade_date() -> Optional[date]:
    trade_dates = fq_trading_fetch_trade_dates()
    trade_dates = trade_dates["trade_date"]
    now = datetime.now()
    value = (
        pydash.chain(trade_dates)
        .filter_(
            lambda trade_date: trade_date.strftime(DT_FORMAT_DAY)
            >= now.strftime(DT_FORMAT_DAY),
        )
        .take(1)
        .value()
    )
    return value[0] if len(value) > 0 else None


def query_prev_trade_date() -> Optional[date]:
    trade_dates = fq_trading_fetch_trade_dates()
    trade_dates = trade_dates["trade_date"]
    now = datetime.now()
    value = (
        pydash.chain(trade_dates)
        .filter_(
            lambda trade_date: trade_date.strftime(DT_FORMAT_DAY)
            < now.strftime(DT_FORMAT_DAY)
        )
        .take_right(1)
        .value()
    )
    return value[0] if len(value) > 0 else None


if __name__ == "__main__":
    prev_date = query_prev_trade_date()
    if prev_date:
        print(datetime.combine(prev_date, datetime.min.time()))
    else:
        print("No previous trade date found")
