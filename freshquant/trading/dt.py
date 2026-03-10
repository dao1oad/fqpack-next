# -*- coding: utf-8 -*-

import os
from contextlib import contextmanager
from datetime import date, datetime
from typing import Callable, Iterator, Optional, TypeVar

import akshare as ak
import pydash
import pandas as pd
from freshquant.carnation.config import DT_FORMAT_DAY
from freshquant.database.cache import redis_cache

T = TypeVar("T")
_PROXY_ENV_KEYS = ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY")


@contextmanager
def _without_proxy_env(keys: tuple[str, ...] = _PROXY_ENV_KEYS) -> Iterator[None]:
    original: dict[str, tuple[str, str] | None] = {}
    for key in keys:
        normalized = key.upper()
        if normalized not in original:
            original[normalized] = (key, os.environ.get(key))
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for normalized, original_entry in original.items():
            original_key = normalized
            value = None if original_entry is None else original_entry[1]
            if value is None:
                os.environ.pop(original_key, None)
            else:
                os.environ[original_key] = value


def _call_without_proxy_env(func: Callable[[], T]) -> T:
    with _without_proxy_env():
        return func()


@redis_cache.memoize(expiration=86400)
def fq_trading_fetch_trade_dates(source="sina") -> pd.DataFrame:
    if source == "sina":
        return _call_without_proxy_env(ak.tool_trade_date_hist_sina)
    return _call_without_proxy_env(ak.tool_trade_date_hist_sina)


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
