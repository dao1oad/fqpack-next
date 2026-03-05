from dagster import DefaultScheduleStatus, ScheduleDefinition

from ..jobs.clean import job_clean_db

clean_db_schedule = ScheduleDefinition(
    description="清理数据定时任务",
    job=job_clean_db,
    cron_schedule="0 21 * * *",
    execution_timezone="Asia/Shanghai",
    default_status=DefaultScheduleStatus.RUNNING,
)
