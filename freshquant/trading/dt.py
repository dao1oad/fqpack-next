# -*- coding: utf-8 -*-

from datetime import date, datetime
from typing import Callable, Optional, TypeVar

import akshare as ak
import pandas as pd
import pydash
from requests.exceptions import RequestException  # type: ignore[import-untyped]

from freshquant.carnation.config import DT_FORMAT_DAY
from freshquant.database.cache import redis_cache
from freshquant.runtime.network import without_proxy_env

T = TypeVar("T")
_TRADE_DATE_FETCH_RETRIES = 3


def _call_without_proxy_env(func: Callable[[], T]) -> T:
    with without_proxy_env():
        return func()


def _fetch_trade_dates_from_source(
    fetcher: Callable[[], pd.DataFrame],
    retries: int = _TRADE_DATE_FETCH_RETRIES,
) -> pd.DataFrame:
    last_error: RequestException | None = None
    for _ in range(max(retries, 1)):
        try:
            return _call_without_proxy_env(fetcher)
        except RequestException as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("trade date fetch failed without exception")


@redis_cache.memoize(expiration=86400)
def fq_trading_fetch_trade_dates(source="sina") -> pd.DataFrame:
    if source == "sina":
        return _fetch_trade_dates_from_source(ak.tool_trade_date_hist_sina)
    return _fetch_trade_dates_from_source(ak.tool_trade_date_hist_sina)


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
