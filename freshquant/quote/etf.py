# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta

import pandas as pd
import pymongo
from QUANTAXIS import QA_fetch_index_day_adv, QA_fetch_index_min_adv
from QUANTAXIS.QAData.data_resample import QA_data_day_resample
from QUANTAXIS.QAUtil.QADate import QA_util_datetime_to_strdatetime, QA_util_time_stamp

from freshquant.carnation.config import TIME_DELTA, TZ
from freshquant.database.cache import in_memory_cache, redis_cache
from freshquant.db import DBfreshquant
from freshquant.quote.general import resample3min, resampleStockOrIndex120min
from freshquant.util.code import fq_util_code_append_market_code


@in_memory_cache.memoize(expiration=3)
def queryEtfCandleSticks(code: str, period: str, endDate=None):
    if endDate is None or endDate == "":
        end = datetime.now() + timedelta(1)
    else:
        end = datetime.strptime(endDate, "%Y-%m-%d")
    end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=TZ)
    shortCode = code[2:]
    start = end + timedelta(TIME_DELTA[period])
    candleSticks = None
    if period == "1m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "1min", start, end)
    elif period == "3m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "1min", start, end)
        candleSticks = resample3min(candleSticks)
    elif period == "5m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "5min", start, end)
    elif period == "15m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "15min", start, end)
    elif period == "30m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "30min", start, end)
    elif period == "60m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "60min", start, end)
    elif period == "120m":
        candleSticks = queryEtfCandleSticksMin(shortCode, "60min", start, end)
        candleSticks = resampleStockOrIndex120min(candleSticks)
    elif period == "1d":
        candleSticks = queryEtfCandleSticksDay(code, start, end)
    elif period == "1w":
        candleSticks = queryEtfCandleSticksDay(code, start, end)
        candleSticks = QA_data_day_resample(candleSticks, "w")
        candleSticks['time_stamp'] = candleSticks.index.to_series().apply(
            lambda value: value[0].timestamp()
        )
    return candleSticks


@redis_cache.memoize(expiration=900)
def queryEtfCandleSticksDayAdv(code, start, end):
    data = QA_fetch_index_day_adv(code, start, end)
    if data is not None:
        return data.data
    return


def queryEtfCandleSticksDay(code, start=None, end=None):
    data = queryEtfCandleSticksDayAdv(
        code,
        QA_util_datetime_to_strdatetime(
            start if start is not None else datetime.now() - timedelta(days=30)
        ),
        QA_util_datetime_to_strdatetime(end if end is not None else datetime.now()),
    )
    if data is None or len(data) == 0:
        return None
    data.reset_index(inplace=True)
    data["datetime"] = data["date"].apply(lambda x: datetime.combine(x, time()))
    data["date_stamp"] = data["datetime"].apply(lambda x: QA_util_time_stamp(x))
    data["time_stamp"] = data["date_stamp"]
    data.set_index("datetime", drop=False, inplace=True)
    data = data[
        ["datetime", "open", "close", "high", "low", "volume", "amount", "time_stamp"]
    ]
    last_datetime = data["datetime"][-1]
    realtime_data_list = (
        DBfreshquant["index_realtime"]
        .find(
            {
                "code": fq_util_code_append_market_code(code, upper_case=False),
                "frequence": '1d',
                "datetime": {"$gt": last_datetime, "$lte": end},
                "open": {"$gt": 0},
                "high": {"$gt": 0},
                "low": {"$gt": 0},
                "close": {"$gt": 0},
            }
        )
        .sort("datetime", pymongo.ASCENDING)
    )
    realtime_data_list = pd.DataFrame(realtime_data_list)
    if len(realtime_data_list) > 0:
        realtime_data_list["time_stamp"] = realtime_data_list["datetime"].apply(
            lambda value: QA_util_time_stamp(value)
        )
        realtime_data_list["date_stamp"] = realtime_data_list["datetime"].apply(
            lambda value: QA_util_time_stamp(
                datetime(year=value.year, month=value.month, day=value.day)
            )
        )
        realtime_data_list = realtime_data_list[
            [
                "datetime",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "amount",
                "time_stamp",
            ]
        ]
        realtime_data_list["datetime"] = realtime_data_list["datetime"].apply(
            lambda value: value.replace(tzinfo=None)
        )
        realtime_data_list.set_index("datetime", drop=False, inplace=True)
        data = pd.concat([data, realtime_data_list])
        data.drop_duplicates(subset="datetime", keep="first", inplace=True)
    data = data.round(
        {"open": 3, "high": 3, "low": 3, "close": 3, "volume": 2, "amount": 2}
    )
    return data


@redis_cache.memoize(expiration=900)
def queryEftCandleSticksMinAdv(code, start, end, frequence):
    return QA_fetch_index_min_adv(code, start, end, frequence).data


def queryEtfCandleSticksMin(code, frequence, start=None, end=None):
    data = queryEftCandleSticksMinAdv(
        code,
        QA_util_datetime_to_strdatetime(start),
        QA_util_datetime_to_strdatetime(end),
        frequence=frequence,
    )
    if data is None or len(data) == 0:
        return None
    data.reset_index(inplace=True)
    data["time_stamp"] = data["datetime"].apply(lambda dt: QA_util_time_stamp(dt))
    data.set_index("datetime", inplace=True, drop=False)
    data = data[
        ["datetime", "open", "close", "high", "low", "volume", "amount", "time_stamp"]
    ]
    last_datetime = data["datetime"][-1]
    realtime_data_list = (
        DBfreshquant["index_realtime"]
        .find(
            {
                "code": fq_util_code_append_market_code(code, upper_case=False),
                "frequence": frequence,
                "datetime": {"$gt": last_datetime, "$lte": end},
                "open": {"$gt": 0},
                "high": {"$gt": 0},
                "low": {"$gt": 0},
                "close": {"$gt": 0},
            }
        )
        .sort("datetime", pymongo.ASCENDING)
    )
    realtime_data_list = pd.DataFrame(realtime_data_list)
    if len(realtime_data_list) > 0:
        realtime_data_list["time_stamp"] = realtime_data_list["datetime"].apply(
            lambda value: QA_util_time_stamp(value)
        )
        realtime_data_list["date_stamp"] = realtime_data_list["datetime"].apply(
            lambda value: QA_util_time_stamp(
                datetime(year=value.year, month=value.month, day=value.day)
            )
        )
        realtime_data_list = realtime_data_list[
            [
                "datetime",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "amount",
                "time_stamp",
            ]
        ]
        realtime_data_list["datetime"] = realtime_data_list["datetime"].apply(
            lambda value: value.replace(tzinfo=None)
        )
        realtime_data_list.set_index("datetime", drop=False, inplace=True)
        data = pd.concat([data, realtime_data_list])
        data.drop_duplicates(subset="datetime", keep="first", inplace=True)
    data = data.round(
        {"open": 3, "high": 3, "low": 3, "close": 3, "volume": 2, "amount": 2}
    )
    return data


if __name__ == "__main__":
    print(queryEtfCandleSticks("sh510050", "3m"))
