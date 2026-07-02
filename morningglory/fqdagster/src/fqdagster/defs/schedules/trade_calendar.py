from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)
from fqdagster.defs.assets.trade_calendar import trade_calendar_cache_asset

from freshquant.config import cfg

TIME_ZONE = getattr(cfg, "TIME_ZONE", "Asia/Shanghai")

trade_calendar_refresh_job = define_asset_job(
    name="trade_calendar_refresh_job",
    selection=AssetSelection.assets(trade_calendar_cache_asset),
    tags={"dagster/max_concurrent_runs": "1"},
)

trade_calendar_morning_refresh_schedule = ScheduleDefinition(
    name="trade_calendar_morning_refresh_schedule",
    job=trade_calendar_refresh_job,
    cron_schedule="30 8 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

trade_calendar_postclose_refresh_schedule = ScheduleDefinition(
    name="trade_calendar_postclose_refresh_schedule",
    job=trade_calendar_refresh_job,
    cron_schedule="10 15 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
