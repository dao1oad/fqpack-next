from dagster import job

from ..ops.clean import op_clean_db


@job
def job_clean_db():
    op_clean_db()
