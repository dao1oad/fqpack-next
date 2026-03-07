from dagster import job

from ..ops.gantt import (
    op_run_gantt_postclose_incremental,
)


@job
def job_gantt_postclose():
    op_run_gantt_postclose_incremental()
