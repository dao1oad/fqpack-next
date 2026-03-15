# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta

import pandas as pd
import pymongo
from bson.codec_options import CodecOptions
from QUANTAXIS.QAData.data_resample import (
    QA_data_day_resample,
    QA_data_futureday_resample,
    QA_data_futuremin_resample,
    QA_data_stockmin_resample,
)

from freshquant.config import cfg
from freshquant.data.future.db import fq_data_future_fetch_day, fq_data_future_fetch_min
from freshquant.data.stock import (
    fq_data_stock_fetch_day,
    fq_data_stock_fetch_min,
    fq_data_stock_resample_90min,
    fq_data_stock_resample_120min,
    fqDataStockResample3min,
)
from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant

time_delta_maps = [
    {
        '1m': -25,
        '3m': -25 * 3,
        '5m': -25 * 5,
        '15m': -25 * 15,
        '30m': -25 * 30,
        '60m': -25 * 60,
        '180m': -5 * 180,
        '1d': -1000,
        '3d': -1000,
    },
    {
        '1m': -25,
        '3m': -5 * 3,
        '5m': -5 * 5,
        '15m': -5 * 15,
        '30m': -5 * 30,
        '60m': -5 * 60,
        '180m': -3 * 180,
        '240m': -3 * 180,
        '1d': -1000,
        '3d': -3000,
    },
]


@in_memory_cache.memoize(expiration=3)
def getFutureData(symbol, period, endDate, cache_stamp=int(datetime.now().timestamp())):
    return None


@in_memory_cache.memoize(expiration=3)
def get_future_data_v2(symbol, period, endDate=None, monitor=1):
    if endDate is None or endDate == "":
        end = datetime.now() + timedelta(1)
    else:
        end = datetime.strptime(endDate, "%Y-%m-%d")
    end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=cfg.TZ)
    if monitor == 0:
        current_time_delta = time_delta_maps[0]
    else:
        current_time_delta = time_delta_maps[1]
    start_date = end + timedelta(current_time_delta[period])
    code = symbol
    realtime = 1
    if end < datetime.now().replace(
        hour=23, minute=59, second=59, microsecond=999, tzinfo=cfg.TZ
    ):
        # print("历史数据",end)
        realtime = 0
    else:
        # print("实时数据",end)
        realtime = 1
    if period == "1m":
        kline_data = fq_data_future_fetch_min(code, "1min", start_date, end, realtime)
    elif period == "3m":
        kline_data = fq_data_future_fetch_min(code, "1min", start_date, end, realtime)
        kline_data = QA_data_futuremin_resample(kline_data, '3min')
        kline_data['time'] = kline_data.index.to_series().apply(
            lambda value: value[0].timestamp() - 8 * 3600
        )
        kline_data["time_stamp"] = kline_data['time']
        kline_data.reset_index(inplace=True)
        kline_data.set_index("datetime", inplace=True, drop=False)
    elif period == "5m":
        kline_data = fq_data_future_fetch_min(code, "5min", start_date, end, realtime)
    elif period == "15m":
        kline_data = fq_data_future_fetch_min(code, "15min", start_date, end, realtime)
    elif period == "30m":
        kline_data = fq_data_future_fetch_min(code, "30min", start_date, end, realtime)
    elif period == "60m":
        kline_data = fq_data_future_fetch_min(code, "60min", start_date, end, realtime)
    elif period == "180m":
        kline_data = fq_data_future_fetch_min(code, "60min", start_date, end, realtime)
        kline_data = QA_data_futuremin_resample(kline_data, '180min')
        kline_data['time'] = kline_data.index.to_series().apply(
            lambda value: value[0].timestamp() - 8 * 3600
        )
        kline_data["time_stamp"] = kline_data['time']
        kline_data.reset_index(inplace=True)
        kline_data.set_index("datetime", inplace=True, drop=False)
    elif period == "240m" or period == "1d":
        kline_data = fq_data_future_fetch_day(code, start_date, end)
    elif period == "3d":
        kline_data = fq_data_future_fetch_day(code, start_date, end)
        kline_data = QA_data_futureday_resample(kline_data, "w")
        kline_data.reset_index(inplace=True)
        kline_data['datetime'] = kline_data['date'].apply(
            lambda x: datetime.combine(x, time())
        )
        kline_data['date_stamp'] = kline_data['datetime'].apply(lambda x: x.timestamp())
        kline_data['time_stamp'] = kline_data['date_stamp']
        kline_data["time"] = kline_data['time_stamp']
        kline_data.reset_index(inplace=True)
        kline_data.set_index('datetime', drop=False, inplace=True)
    kline_data.fillna(0, inplace=True)
    kline_data = kline_data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    kline_data['datetime'] = kline_data.index
    return kline_data


@in_memory_cache.memoize(expiration=3)
def get_stock_data(
    symbol,
    period,
    endDate=None,
    bar_count=0,
):
    if endDate is None or endDate == "":
        end = datetime.now() + timedelta(1)
    else:
        end = datetime.strptime(endDate, "%Y-%m-%d")
    end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=cfg.TZ)
    start = end + timedelta(days=_resolve_stock_history_days(period, bar_count))
    code = symbol[2:]

    kline_data = None
    if period == "1m":
        kline_data = fq_data_stock_fetch_min(code, "1min", start, end)
    elif period == "3m":
        kline_data = fq_data_stock_fetch_min(code, "1min", start, end)
        kline_data = fqDataStockResample3min(kline_data)
    elif period == "5m":
        kline_data = fq_data_stock_fetch_min(code, "5min", start, end)
    elif period == "15m":
        kline_data = fq_data_stock_fetch_min(code, "15min", start, end)
    elif period == "30m":
        kline_data = fq_data_stock_fetch_min(code, "30min", start, end)
    elif period == "60m":
        kline_data = fq_data_stock_fetch_min(code, "60min", start, end)
    elif period == "90m":
        kline_data = fq_data_stock_fetch_min(code, "30min", start, end)
        kline_data = fq_data_stock_resample_90min(kline_data)
    elif period == "120m":
        kline_data = fq_data_stock_fetch_min(code, "60min", start, end)
        kline_data = fq_data_stock_resample_120min(kline_data)
    elif period == "1d":
        kline_data = fq_data_stock_fetch_day(code, start, end)
    elif period == "1w":
        kline_data = fq_data_stock_fetch_day(code, start, end)
        kline_data = QA_data_day_resample(kline_data, "w")
        kline_data['time_stamp'] = kline_data.index.to_series().apply(
            lambda value: value[0].timestamp()
        )
    if kline_data is not None:
        kline_data.fillna(0, inplace=True)
        if bar_count and len(kline_data) > int(bar_count):
            kline_data = kline_data.iloc[-int(bar_count) :].copy()
    kline_data['datetime'] = kline_data.index
    return kline_data


def _resolve_stock_history_days(period, bar_count=0):
    default_days = int(cfg.TIME_DELTA[period])
    if not bar_count:
        return default_days

    try:
        requested_bars = max(int(bar_count), 0)
    except (TypeError, ValueError):
        return default_days
    if requested_bars <= 0:
        return default_days

    minute_map = {
        '1m': 1,
        '3m': 3,
        '5m': 5,
        '15m': 15,
        '30m': 30,
        '60m': 60,
        '90m': 90,
        '120m': 120,
        '180m': 180,
    }
    if period in minute_map:
        bars_per_day = max(1, int(240 / minute_map[period]))
        requested_days = int(((requested_bars / bars_per_day) + 60) * 1.35)
        return -max(abs(default_days), requested_days)

    if period == '1d':
        requested_days = int((requested_bars + 30) * 1.2)
        return -max(abs(default_days), requested_days)

    if period == '1w':
        requested_days = int((requested_bars * 7 + 60) * 1.2)
        return -max(abs(default_days), requested_days)

    return default_days


@in_memory_cache.memoize(expiration=3)
def getGlobalFutureData(
    symbol,
    period,
    endDate,
):
    if endDate is None or endDate == "":
        end = datetime.now() + timedelta(1)
    else:
        end = datetime.strptime(endDate, "%Y-%m-%d")
    end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=cfg.TZ)
    timeDeltaMap = {
        '1m': -3,
        '3m': -3 * 3,
        '5m': -3 * 5,
        '15m': -3 * 15,
        '30m': -3 * 30,
        '60m': -3 * 60,
        '180m': -3 * 180,
        '1d': -1000,
        '3d': -3000,
    }
    start_date = end + timedelta(timeDeltaMap[period])
    code = "%s_%s" % (symbol, period)
    data_list = (
        DBfreshquant[code]
        .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
        .find({"_id": {"$gte": start_date, "$lte": end}})
        .sort("_id", pymongo.ASCENDING)
    )
    data_list = list(data_list)
    if len(data_list) == 0:
        return None
    kline_data = pd.DataFrame(data_list)
    kline_data['time_stamp'] = kline_data['_id'].apply(lambda value: value.timestamp())
    kline_data.fillna(0, inplace=True)
    return kline_data


def current_minute(symbol):
    return None
