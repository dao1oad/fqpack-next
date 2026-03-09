# -*- coding: utf-8 -*-

from datetime import datetime, time, timedelta

import pandas as pd
import pymongo
from loguru import logger
from QUANTAXIS import QA_fetch_index_day_adv, QA_fetch_index_min_adv
from QUANTAXIS.QAData.data_resample import QA_data_day_resample
from QUANTAXIS.QAUtil.QADate import QA_util_datetime_to_strdatetime, QA_util_time_stamp

from freshquant.carnation.config import TIME_DELTA, TZ
from freshquant.data.adj_intraday import (
    apply_qfq_with_intraday_override,
    fetch_intraday_override,
    fetch_qfq_adj_df,
)
from freshquant.database.cache import in_memory_cache, redis_cache
from freshquant.db import DBfreshquant
from freshquant.quote.general import resample3min, resampleStockOrIndex120min
from freshquant.util.code import fq_util_code_append_market_code, normalize_to_base_code


def _fetch_etf_adj(
    code: str, start: datetime | None, end: datetime | None
) -> pd.DataFrame | None:
    if start is None or end is None:
        return None
    docs = fetch_qfq_adj_df(
        coll_name="etf_adj",
        code=normalize_to_base_code(code),
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )
    if len(docs) == 0:
        return None
    return docs


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
    start_dt = start if start is not None else datetime.now() - timedelta(days=30)
    end_dt = end if end is not None else datetime.now()
    data = queryEtfCandleSticksDayAdv(
        code,
        QA_util_datetime_to_strdatetime(start_dt),
        QA_util_datetime_to_strdatetime(end_dt),
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
                "datetime": {"$gt": last_datetime, "$lte": end_dt},
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

    adj = _fetch_etf_adj(code, start_dt, end_dt)
    if adj is None or len(adj) == 0:
        start_s = start_dt.strftime("%Y-%m-%d") if start_dt else "N/A"
        end_s = end_dt.strftime("%Y-%m-%d") if end_dt else "N/A"
        logger.warning(
            f"etf_adj missing for {normalize_to_base_code(code)} [{start_s},{end_s}]"
        )
    else:
        override = fetch_intraday_override(
            coll_name="etf_adj_intraday",
            code=code,
            trade_date=end_dt.strftime("%Y-%m-%d"),
        )
        data = apply_qfq_with_intraday_override(
            data,
            adj,
            override=override,
            datetime_col="datetime",
        )

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

    adj = _fetch_etf_adj(code, start, end)
    if adj is None or len(adj) == 0:
        start_s = start.strftime("%Y-%m-%d") if start else "N/A"
        end_s = end.strftime("%Y-%m-%d") if end else "N/A"
        logger.warning(
            f"etf_adj missing for {normalize_to_base_code(code)} [{start_s},{end_s}]"
        )
    else:
        override = fetch_intraday_override(
            coll_name="etf_adj_intraday",
            code=code,
            trade_date=end.strftime("%Y-%m-%d") if end else None,
        )
        data = apply_qfq_with_intraday_override(
            data,
            adj,
            override=override,
            datetime_col="datetime",
        )

    data = data.round(
        {"open": 3, "high": 3, "low": 3, "close": 3, "volume": 2, "amount": 2}
    )
    return data


if __name__ == "__main__":
    print(queryEtfCandleSticks("sh510050", "3m"))
