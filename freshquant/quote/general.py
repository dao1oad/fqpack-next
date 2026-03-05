# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta

from QUANTAXIS.QAUtil.QADate import QA_util_time_stamp


def resample3min(data):
    data["group"] = data["datetime"].apply(
        lambda dt: dt + timedelta(minutes={1: 1, 2: 2, 3: 0}.get(3 - (dt.minute % 3)))
    )
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
    data.set_index("datetime", drop=False, inplace=True)
    return data


def resampleStockOrIndex120min(data):
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
    data.set_index("datetime", drop=False, inplace=True)
    return data
