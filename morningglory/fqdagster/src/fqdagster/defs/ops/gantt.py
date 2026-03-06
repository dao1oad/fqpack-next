from dagster import op

from freshquant.data.gantt_readmodel import (
    persist_gantt_daily_for_date,
    persist_plate_reason_daily_for_date,
    persist_shouban30_for_date,
)
from freshquant.data.gantt_source_jygs import sync_jygs_action_for_date
from freshquant.data.gantt_source_xgb import sync_xgb_history_for_date


def _resolve_trade_date(trade_date: str | None = None) -> str:
    if trade_date:
        return str(trade_date).strip()
    from freshquant.trading.dt import query_prev_trade_date

    previous_trade_date = query_prev_trade_date()
    if previous_trade_date is None:
        raise RuntimeError("no previous trade date available")
    return previous_trade_date.strftime("%Y-%m-%d")


@op
def op_sync_xgb_history_daily(context) -> str:
    trade_date = _resolve_trade_date()
    rows = sync_xgb_history_for_date(trade_date)
    context.log.info("synced xgb history rows=%s trade_date=%s", rows, trade_date)
    return trade_date


@op
def op_sync_jygs_action_daily(context) -> str:
    trade_date = _resolve_trade_date()
    result = sync_jygs_action_for_date(trade_date)
    context.log.info("synced jygs action=%s", result)
    return result["trade_date"]


@op
def op_build_plate_reason_daily(
    context, xgb_trade_date: str, jygs_trade_date: str
) -> str:
    if xgb_trade_date != jygs_trade_date:
        raise RuntimeError(
            f"trade_date mismatch xgb={xgb_trade_date} jygs={jygs_trade_date}"
        )
    count = persist_plate_reason_daily_for_date(xgb_trade_date)
    context.log.info(
        "built plate_reason_daily rows=%s trade_date=%s", count, xgb_trade_date
    )
    return xgb_trade_date


@op
def op_build_gantt_daily(context, trade_date: str) -> str:
    result = persist_gantt_daily_for_date(trade_date)
    context.log.info("built gantt daily=%s", result)
    return trade_date


@op
def op_build_shouban30_daily(context, trade_date: str) -> dict:
    result = persist_shouban30_for_date(trade_date)
    context.log.info("built shouban30=%s", result)
    return result
