# -*- coding;utf-8 -*-

from datetime import datetime, time

from freshquant.config import cfg


def fq_data_future_resample_60min(data):
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
            "position": "sum",
            "amount": "sum",
        }
    )
    data["time_stamp"] = data["datetime"].apply(lambda dt: dt.timestamp())
    data["date_stamp"] = data["datetime"].apply(
        lambda dt: cfg.TZ.localize(
            datetime(year=dt.year, month=dt.month, day=dt.day)
        ).timestamp()
    )
    data = data.round(
        {"open": 2, "high": 2, "low": 2, "close": 2, "volume": 2, "amount": 2}
    )
    data.set_index("datetime", drop=True, inplace=True)
    return data
