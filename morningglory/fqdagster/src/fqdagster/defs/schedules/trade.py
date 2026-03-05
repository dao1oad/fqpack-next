from dagster import DefaultScheduleStatus, ScheduleDefinition

from freshquant.config import cfg

from ..jobs.trade import job_backfill_order, job_reverse_repo

exec_reverse_repo_schedule = ScheduleDefinition(
    description="国债逆回购",
    job=job_reverse_repo,
    cron_schedule="55 14 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)

exec_backfill_order_schedule = ScheduleDefinition(
    description="补单",
    job=job_backfill_order,
    cron_schedule="20 9 * * 1-5",
    execution_timezone="Asia/Shanghai",
    default_status=DefaultScheduleStatus.RUNNING,
)
