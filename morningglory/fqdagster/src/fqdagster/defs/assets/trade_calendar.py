from dagster import asset

from freshquant.data.trade_calendar_cache import (
    FRAME_ATTR_ERROR_MESSAGE,
    FRAME_ATTR_ERROR_TYPE,
    FRAME_ATTR_STATUS,
    STATUS_LIVE,
)
from freshquant.data.trade_date_hist import refresh_trade_date_hist_sina_cache

TRADE_CALENDAR_GROUP = "trade_calendar"


@asset(group_name=TRADE_CALENDAR_GROUP)
def trade_calendar_cache_asset() -> dict:
    frame = refresh_trade_date_hist_sina_cache()
    trade_dates = frame["trade_date"]
    refresh_status = str(frame.attrs.get(FRAME_ATTR_STATUS) or STATUS_LIVE)
    return {
        "date_count": len(trade_dates),
        "min_trade_date": trade_dates.min().strftime("%Y-%m-%d"),
        "max_trade_date": trade_dates.max().strftime("%Y-%m-%d"),
        "source": "sina",
        "refresh_status": refresh_status,
        "degraded": refresh_status != STATUS_LIVE,
        "source_error_type": str(frame.attrs.get(FRAME_ATTR_ERROR_TYPE) or ""),
        "source_error_message": str(frame.attrs.get(FRAME_ATTR_ERROR_MESSAGE) or ""),
    }
