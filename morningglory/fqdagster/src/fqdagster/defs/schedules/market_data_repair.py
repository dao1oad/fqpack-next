from __future__ import annotations

from typing import cast

from dagster import DefaultScheduleStatus, ScheduleDefinition

from freshquant.config import cfg

from ..jobs.market_data_repair import stock_postclose_repair_job

TIME_ZONE = cast(str, getattr(cfg, "TIME_ZONE", "Asia/Shanghai"))

stock_postclose_repair_evening_schedule = ScheduleDefinition(
    name="stock_postclose_repair_evening_schedule",
    description="股票盘后缺口延迟修复（17:30）",
    job=stock_postclose_repair_job,
    cron_schedule="30 17 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

stock_postclose_repair_preopen_schedule = ScheduleDefinition(
    name="stock_postclose_repair_preopen_schedule",
    description="股票盘前 QFQ/盘后缺口修复（08:30）",
    job=stock_postclose_repair_job,
    cron_schedule="30 8 * * 1-5",
    execution_timezone=TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

__all__ = [
    "stock_postclose_repair_evening_schedule",
    "stock_postclose_repair_preopen_schedule",
]
