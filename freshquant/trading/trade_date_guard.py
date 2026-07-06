from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any

import pandas as pd

from freshquant.runtime_constants import TZ
from freshquant.trading.dt import fq_trading_fetch_trade_dates


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.isoformat()
    else:
        dt = pd.Timestamp(value).to_pydatetime()

    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ)
    return dt.date().isoformat()


def _weekday_open(value: Any) -> bool:
    try:
        if isinstance(value, datetime):
            dt = value.astimezone(TZ) if value.tzinfo is not None else value
            return dt.weekday() < 5
        if isinstance(value, date):
            return value.weekday() < 5
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(TZ)
        return ts.weekday() < 5
    except Exception:
        return False


@lru_cache(maxsize=1)
def _trade_date_set() -> frozenset[str]:
    frame = fq_trading_fetch_trade_dates()
    if frame is None or "trade_date" not in frame.columns:
        raise RuntimeError("trade calendar dataframe missing trade_date column")
    values = pd.to_datetime(frame["trade_date"], errors="coerce")
    if values.isna().any():
        raise RuntimeError("trade calendar contains unparseable trade_date values")
    return frozenset(value.date().isoformat() for value in values)


def is_cn_a_trade_date(value: Any) -> bool:
    if not _weekday_open(value):
        return False
    try:
        return _date_key(value) in _trade_date_set()
    except Exception:
        return False


def clear_trade_date_guard_cache() -> None:
    cache_clear = getattr(_trade_date_set, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
