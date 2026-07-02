from dagster import asset

from freshquant.data.trade_date_hist import refresh_trade_date_hist_sina_cache

TRADE_CALENDAR_GROUP = "trade_calendar"


@asset(group_name=TRADE_CALENDAR_GROUP)
def trade_calendar_cache_asset() -> dict:
    trade_dates = refresh_trade_date_hist_sina_cache()["trade_date"]
    return {
        "date_count": len(trade_dates),
        "min_trade_date": trade_dates.min().strftime("%Y-%m-%d"),
        "max_trade_date": trade_dates.max().strftime("%Y-%m-%d"),
        "source": "sina",
    }
