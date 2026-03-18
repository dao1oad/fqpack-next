from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    ScheduleDefinition,
    define_asset_job,
)

from freshquant.config import cfg

from ..assets.daily_screening import daily_screening_context

daily_screening_postclose_job = define_asset_job(
    name="daily_screening_postclose_job",
    description="盘后物化每日筛选资产依赖图",
    selection=AssetSelection.assets(daily_screening_context).downstream(),
    tags={"dagster/max_concurrent_runs": "1"},
)

daily_screening_postclose_schedule = ScheduleDefinition(
    description="19:00 自动执行统一每日筛选全链路",
    job=daily_screening_postclose_job,
    cron_schedule="0 19 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
