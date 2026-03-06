from dagster import job

from ..ops.gantt import (
    op_build_gantt_daily,
    op_build_plate_reason_daily,
    op_build_shouban30_daily,
    op_sync_jygs_action_daily,
    op_sync_xgb_history_daily,
)


@job
def job_gantt_postclose():
    xgb_trade_date = op_sync_xgb_history_daily()
    jygs_trade_date = op_sync_jygs_action_daily()
    trade_date = op_build_plate_reason_daily(xgb_trade_date, jygs_trade_date)
    trade_date = op_build_gantt_daily(trade_date)
    op_build_shouban30_daily(trade_date)
