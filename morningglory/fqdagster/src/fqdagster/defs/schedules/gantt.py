from dagster import DefaultScheduleStatus, ScheduleDefinition

from freshquant.config import cfg

from ..jobs.gantt import job_gantt_postclose

gantt_postclose_schedule = ScheduleDefinition(
    description="盘后构建 Gantt 与 Shouban30 读模型",
    job=job_gantt_postclose,
    cron_schedule="40 16 * * 1-5",
    execution_timezone=cfg.TIME_ZONE,
    default_status=DefaultScheduleStatus.STOPPED,
)
