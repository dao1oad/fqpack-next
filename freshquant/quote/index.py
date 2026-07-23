from datetime import datetime, timedelta

from QUANTAXIS import QA_fetch_index_day_adv, QA_fetch_index_min_adv
from QUANTAXIS.QAData.data_resample import QA_data_day_resample

from freshquant.carnation.config import TIME_DELTA
from freshquant.config import cfg
from freshquant.data.index import (
    fq_data_index_fetch_day,
    fq_data_index_fetch_min,
    fq_data_stock_resample_90min,
)
from freshquant.data.stock import fqDataStockResample3min
from freshquant.database.cache import in_memory_cache, redis_cache
from freshquant.quote.general import resampleStockOrIndex120min
from freshquant.util.code import normalize_to_base_code


def _resolve_index_history_days(period: str, bar_count: int = 0) -> int:
    default_days = int(TIME_DELTA[period])
    try:
        requested = int(bar_count or 0)
    except (TypeError, ValueError):
        requested = 0
    if requested <= 0:
        return default_days
    if period == "1d":
        return -max(abs(default_days), int((requested + 30) * 1.2))
    if period == "1w":
        return -max(abs(default_days), int((requested * 7 + 60) * 1.2))
    minute_map = {
        "1m": 1,
        "3m": 3,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "90m": 90,
        "120m": 120,
    }
    minutes = minute_map.get(period)
    if minutes:
        bars_per_day = max(1, int(240 / minutes))
        return -max(abs(default_days), int(((requested / bars_per_day) + 60) * 1.35))
    return default_days


@in_memory_cache.memoize(expiration=3)
def queryIndexCandleSticks(code: str, period: str, endDate=None, bar_count=0):
    """Fetch real Index candles without applying any QFQ factor."""
    if endDate is None or endDate == "":
        end = datetime.now() + timedelta(1)
    else:
        end = datetime.strptime(endDate, "%Y-%m-%d")
    end = end.replace(hour=23, minute=59, second=59, microsecond=999, tzinfo=cfg.TZ)
    short_code = normalize_to_base_code(code)
    start = end + timedelta(days=_resolve_index_history_days(period, bar_count))

    if period == "1m":
        data = fq_data_index_fetch_min(short_code, "1min", start, end)
    elif period == "3m":
        data = fq_data_index_fetch_min(short_code, "1min", start, end)
        data = fqDataStockResample3min(data) if data is not None else None
    elif period in {"5m", "15m", "30m", "60m"}:
        data = fq_data_index_fetch_min(
            short_code, period.replace("m", "min"), start, end
        )
    elif period == "90m":
        data = fq_data_index_fetch_min(short_code, "30min", start, end)
        data = fq_data_stock_resample_90min(data) if data is not None else None
    elif period == "120m":
        data = fq_data_index_fetch_min(short_code, "60min", start, end)
        data = resampleStockOrIndex120min(data) if data is not None else None
    elif period == "1d":
        data = fq_data_index_fetch_day(short_code, start, end)
    elif period == "1w":
        data = fq_data_index_fetch_day(short_code, start, end)
        data = QA_data_day_resample(data, "w") if data is not None else None
    else:
        raise ValueError(f"unsupported index period: {period}")

    if data is None or len(data) == 0:
        return None
    data = data.copy()
    data.fillna(0, inplace=True)
    if bar_count and len(data) > int(bar_count):
        data = data.iloc[-int(bar_count) :].copy()
    if "datetime" not in data.columns:
        data["datetime"] = data.index
    return data


@redis_cache.memoize(expiration=900)
def fq_quote_fetch_index_day_adv(code, start, end):
    data = QA_fetch_index_day_adv(code, start, end)
    if data is not None:
        return data.data
    return


if __name__ == "__main__":
    print(fq_quote_fetch_index_day_adv('000001', '2023-01-01', '2024-08-30'))
