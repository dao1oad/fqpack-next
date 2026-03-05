# coding=utf-8

from dagster import job

from ..ops.trade import op_backfill_order, op_reverse_repo


@job
def job_reverse_repo():
    op_reverse_repo()


@job
def job_backfill_order():
    op_backfill_order()
