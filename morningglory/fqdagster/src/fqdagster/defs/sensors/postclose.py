from dagster import RunRequest, SkipReason, sensor

from ..jobs.gantt import job_gantt_postclose
from ..postclose_markers import (
    has_success_postclose_marker,
    resolve_latest_completed_trade_date,
)


@sensor(job=job_gantt_postclose)
def gantt_postclose_sensor(_context):
    trade_date = resolve_latest_completed_trade_date()
    if not has_success_postclose_marker("stock_postclose_ready", trade_date):
        return SkipReason(f"stock_postclose_ready missing for {trade_date}")
    if has_success_postclose_marker("gantt_postclose_ready", trade_date):
        return SkipReason(f"gantt_postclose_ready already exists for {trade_date}")
    return RunRequest(
        run_key=f"gantt-postclose:{trade_date}",
        tags={"fq_trade_date": trade_date},
    )
