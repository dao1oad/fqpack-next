# -*- coding: utf-8 -*-

from datetime import datetime, time

import pandas as pd
import pymongo
from QUANTAXIS import (
    QA_fetch_index_day_adv,
    QA_fetch_index_list_adv,
    QA_fetch_index_min_adv,
)
from QUANTAXIS.QAUtil.QADate import QA_util_datetime_to_strdatetime, QA_util_time_stamp

from freshquant.database.cache import redis_cache
from freshquant.db import DBfreshquant
from freshquant.util.code import fq_util_code_append_market_code


@redis_cache.memoize(expiration=900)
def fq_data_QA_fetch_index_min_adv(code, start, end, frequence):
    return QA_fetch_index_min_adv(code, start, end, frequence).to_qfq().data


@redis_cache.memoize(expiration=900)
def fqDataQAFetchIndexDayAdv(code, start, end):
    return QA_fetch_index_day_adv(code, start, end).data


@redis_cache.memoize(expiration=864000)
def fqDataQAFetchIndexListAdv():
    return QA_fetch_index_list_adv()


def fq_data_index_fetch_min(code, frequence, start=None, end=None):
    data = fq_data_QA_fetch_index_min_adv(
        code,
        QA_util_datetime_to_strdatetime(start),
        QA_util_datetime_to_strdatetime(end),
        frequence=frequence,
    )
    data.reset_index(inplace=True)
    data["time_stamp"] = data["datetime"].apply(lambda dt: QA_util_time_stamp(dt))
    data.set_index("datetime", inplace=True, drop=False)
    if data is None or len(data) == 0:
        return None
    last_datetime = data["datetime"][-1]
    realtime_data_list = (
        DBfreshquant["stock_realtime"]
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
    data = data[
        ["datetime", "open", "close", "high", "low", "volume", "amount", "time_stamp"]
    ]
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
        data = data.append(realtime_data_list)
        data.drop_duplicates(subset="datetime", keep="first", inplace=True)
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    return data


def fqDataIndexFetchDay(code, start=None, end=None):
    data = fqDataQAFetchIndexDayAdv(
        code,
        QA_util_datetime_to_strdatetime(start),
        QA_util_datetime_to_strdatetime(end),
    )
    data.reset_index(inplace=True)
    data["datetime"] = data["date"].apply(lambda x: datetime.combine(x, time()))
    data["date_stamp"] = data["datetime"].apply(lambda x: QA_util_time_stamp(x))
    data["time_stamp"] = data["date_stamp"]
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=False, inplace=True)
    return data


def fq_data_stock_resample_60min(data):
    def func(dt):
        if dt.time() > time(hour=9, minute=30) and dt.time() <= time(
            hour=10, minute=30
        ):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=10, minute=30
            )
        elif dt.time() > time(hour=10, minute=30) and dt.time() <= time(
            hour=11, minute=30
        ):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=11, minute=30
            )
        elif dt.time() > time(hour=13, minute=0) and dt.time() <= time(
            hour=14, minute=0
        ):
            return datetime(year=dt.year, month=dt.month, day=dt.day, hour=14, minute=0)
        elif dt.time() > time(hour=14, minute=0) and dt.time() <= time(
            hour=15, minute=0
        ):
            return datetime(year=dt.year, month=dt.month, day=dt.day, hour=15, minute=0)

    data["group"] = data["datetime"].apply(func)
    data = data.groupby(by="group").agg(
        {
            "datetime": "last",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }
    )
    data["time_stamp"] = data["datetime"].apply(lambda dt: QA_util_time_stamp(dt))
    data["date_stamp"] = data["datetime"].apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=True, inplace=True)
    return data


def fq_data_stock_resample_90min(data):
    def func(dt):
        if dt.time() > time(hour=9, minute=30) and dt.time() <= time(hour=11, minute=0):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=10, minute=30
            )
        elif dt.time() > time(hour=11, minute=0) and dt.time() <= time(
            hour=14, minute=0
        ):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=11, minute=30
            )
        elif dt.time() > time(hour=14, minute=0) and dt.time() <= time(
            hour=15, minute=0
        ):
            return datetime(year=dt.year, month=dt.month, day=dt.day, hour=14, minute=0)

    data["group"] = data["datetime"].apply(func)
    data = data.groupby(by="group").agg(
        {
            "datetime": "last",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }
    )
    data["time_stamp"] = data["datetime"].apply(lambda dt: QA_util_time_stamp(dt))
    data["date_stamp"] = data["datetime"].apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=True, inplace=True)
    return data


def fq_data_stock_resample_120min(data):
    def func(dt):
        if dt.time() > time(hour=9, minute=30) and dt.time() <= time(
            hour=11, minute=30
        ):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=10, minute=30
            )
        elif dt.time() > time(hour=13, minute=0) and dt.time() <= time(
            hour=15, minute=0
        ):
            return datetime(
                year=dt.year, month=dt.month, day=dt.day, hour=11, minute=30
            )

    data["group"] = data["datetime"].apply(func)
    data = data.groupby(by="group").agg(
        {
            "datetime": "last",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "amount": "sum",
        }
    )
    data["time_stamp"] = data["datetime"].apply(lambda dt: QA_util_time_stamp(dt))
    data["date_stamp"] = data["datetime"].apply(
        lambda dt: QA_util_time_stamp(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        )
    )
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=True, inplace=True)
    return data
