from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd
import pymongo
from QUANTAXIS import QA_fetch_stock_day_adv, QA_fetch_stock_min_adv
from QUANTAXIS.QAUtil.QADate import QA_util_datetime_to_strdatetime, QA_util_time_stamp
from talib import ATR

from freshquant.data.adj_intraday import (
    apply_qfq_with_intraday_override,
    fetch_intraday_override,
    fetch_qfq_adj_df,
)
from freshquant.database.cache import redis_cache
from freshquant.db import DBfreshquant
from freshquant.util.code import fq_util_code_append_market_code, normalize_to_base_code


@redis_cache.memoize(expiration=900)
def fq_data_QA_fetch_stock_min_adv(code, start, end, frequence):
    data = QA_fetch_stock_min_adv(code, start, end, frequence)
    if data is not None:
        return data.data
    return


@redis_cache.memoize(expiration=900)
def fq_data_QA_fetch_stock_day_adv(code, start, end):
    data = QA_fetch_stock_day_adv(code, start, end)
    if data is not None:
        return data.data
    return


def _apply_stock_qfq(
    data: pd.DataFrame,
    *,
    code: str,
    start: datetime | None,
    end: datetime | None,
) -> pd.DataFrame:
    if data is None or len(data) == 0 or start is None or end is None:
        return data
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")
    base_code = normalize_to_base_code(code)
    adj = fetch_qfq_adj_df(
        coll_name="stock_adj",
        code=base_code,
        start_date=start_date,
        end_date=end_date,
    )
    override = fetch_intraday_override(
        coll_name="stock_adj_intraday",
        code=base_code,
        trade_date=end_date,
    )
    return apply_qfq_with_intraday_override(
        data,
        adj,
        override=override,
        datetime_col="datetime",
    )


def fq_data_stock_fetch_min(code, frequence, start=None, end=None):
    start_dt = start
    end_dt = end
    data = fq_data_QA_fetch_stock_min_adv(
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
        data = pd.concat([data, realtime_data_list])
        data.drop_duplicates(subset="datetime", keep="first", inplace=True)
    data = _apply_stock_qfq(data, code=code, start=start_dt, end=end_dt)
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    return data


def fq_data_stock_fetch_day(code, start=None, end=None):
    # 处理start参数：如果已经是字符串类型就不需要转换
    start_param = start if start is not None else datetime.now() - timedelta(days=60)
    if isinstance(start_param, str):
        start_str = start_param
        start_dt = datetime.fromisoformat(start_param[:19])
    else:
        start_str = QA_util_datetime_to_strdatetime(start_param)
        start_dt = start_param

    # 处理end参数：如果已经是字符串类型就不需要转换
    end_param = end if end is not None else datetime.now()
    if isinstance(end_param, str):
        end_str = end_param
        end_dt = datetime.fromisoformat(end_param[:19])
    else:
        end_str = QA_util_datetime_to_strdatetime(end_param)
        end_dt = end_param

    data = fq_data_QA_fetch_stock_day_adv(code, start_str, end_str)
    if data is None or len(data) == 0:
        return None
    data.reset_index(inplace=True)
    data["datetime"] = data["date"].apply(lambda x: datetime.combine(x, time()))
    data["date_stamp"] = data["datetime"].apply(lambda x: QA_util_time_stamp(x))
    data["time_stamp"] = data["date_stamp"]
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=False, inplace=True)
    data = data[
        ["datetime", "open", "close", "high", "low", "volume", "amount", "time_stamp"]
    ]
    last_datetime = data["datetime"][-1]
    realtime_data_list = (
        DBfreshquant["stock_realtime"]
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
    data = _apply_stock_qfq(data, code=code, start=start_dt, end=end_dt)
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    return data


def fqDataStockResample3min(data):
    def groupFunc(dt):
        delta = 3 - (dt.minute % 3)
        return dt + timedelta(minutes=delta)

    data["group"] = data["datetime"].apply(groupFunc)
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


@redis_cache.memoize(expiration=60 * 60 * 24)
def fq_data_stock_fetch_atr(
    code: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    n: int = 14,
):
    data = fq_data_stock_fetch_day(code, start, end)
    return ATR(data.high.values, data.low.values, data.close.values, n)


if __name__ == "__main__":
    print(fq_data_stock_fetch_atr("600999"))
