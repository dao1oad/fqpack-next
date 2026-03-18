from dagster import DefaultScheduleStatus, ScheduleDefinition

from freshquant.config import cfg

from ..jobs.daily_screening import job_daily_screening_postclose

daily_screening_postclose_schedule = ScheduleDefinition(
    description="19:00 自动执行统一每日筛选全链路",
    job=job_daily_screening_postclose,
    cron_schedule="0 19 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
