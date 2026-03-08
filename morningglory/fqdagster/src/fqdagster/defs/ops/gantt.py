from datetime import datetime
from typing import Any

from dagster import op

from freshquant.data.gantt_readmodel import (
    persist_gantt_daily_for_date,
    persist_plate_reason_daily_for_date,
    persist_shouban30_for_date,
    persist_stock_hot_reason_daily_for_date,
)
from freshquant.data.gantt_source_jygs import sync_jygs_action_for_date
from freshquant.data.gantt_source_xgb import sync_xgb_history_for_date
from freshquant.data.trade_date_hist import (
    get_trade_dates_between,
    tool_trade_date_hist_sina,
)
from freshquant.db import DBGantt

COL_GANTT_PLATE_DAILY = "gantt_plate_daily"
COL_SHOUBAN30_PLATES = "shouban30_plates"
POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5
SHOUBAN30_STOCK_WINDOWS = (30, 45, 60, 90)


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _query_latest_trade_date() -> str:
    trade_dates = list(tool_trade_date_hist_sina()["trade_date"])
    if not trade_dates:
        raise RuntimeError("no trade dates available")

    now = datetime.now()
    today = now.date()
    cutoff = now.replace(
        hour=POSTCLOSE_CUTOFF_HOUR,
        minute=POSTCLOSE_CUTOFF_MINUTE,
        second=0,
        microsecond=0,
    )

    if today in trade_dates and now >= cutoff:
        return today.strftime("%Y-%m-%d")

    for trade_date in reversed(trade_dates):
        if trade_date < today:
            return trade_date.strftime("%Y-%m-%d")

    raise RuntimeError("no completed trade date available")


def _query_latest_completed_gantt_trade_date() -> str | None:
    dates = [
        _to_str(trade_date)
        for trade_date in DBGantt[COL_GANTT_PLATE_DAILY].distinct("trade_date")
        if _to_str(trade_date)
    ]
    if not dates:
        return None
    return max(dates)


def _has_legacy_shouban30_snapshot(trade_date: str) -> bool:
    date_str = _to_str(trade_date)
    if not date_str:
        return False

    collection = DBGantt[COL_SHOUBAN30_PLATES]
    if collection.count_documents({"as_of_date": date_str}) <= 0:
        return False

    windows = {
        int(value)
        for value in collection.distinct("stock_window_days", {"as_of_date": date_str})
        if isinstance(value, int) and value in SHOUBAN30_STOCK_WINDOWS
    }
    return not windows


def _query_trade_dates_between(start_date: str, end_date: str) -> list[str]:
    if not start_date or not end_date or start_date > end_date:
        return []
    return [
        trade_date.strftime("%Y-%m-%d")
        for trade_date in get_trade_dates_between(start_date, end_date)
    ]


def _resolve_trade_date(trade_date: str | None = None) -> str:
    if trade_date:
        return str(trade_date).strip()
    return _query_latest_trade_date()


def _build_shouban30_snapshots_for_date(context, trade_date: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for stock_window_days in SHOUBAN30_STOCK_WINDOWS:
        result = persist_shouban30_for_date(
            trade_date,
            stock_window_days=stock_window_days,
        )
        results.append(result)
        context.log.info(
            "built shouban30 trade_date=%s stock_window_days=%s result=%s",
            trade_date,
            stock_window_days,
            result,
        )
    return {
        "trade_date": trade_date,
        "windows": list(SHOUBAN30_STOCK_WINDOWS),
        "results": results,
    }


def resolve_gantt_backfill_trade_dates() -> list[str]:
    latest_trade_date = _query_latest_trade_date()
    latest_completed_trade_date = _query_latest_completed_gantt_trade_date()

    if latest_completed_trade_date is None:
        return [latest_trade_date]

    if latest_completed_trade_date >= latest_trade_date:
        if _has_legacy_shouban30_snapshot(latest_trade_date):
            return [latest_trade_date]
        return []

    trade_dates = _query_trade_dates_between(
        latest_completed_trade_date,
        latest_trade_date,
    )
    return [
        trade_date
        for trade_date in trade_dates
        if trade_date > latest_completed_trade_date
    ]


def run_gantt_pipeline_for_date(context, trade_date: str) -> dict[str, Any]:
    rows = sync_xgb_history_for_date(trade_date)
    context.log.info("synced xgb history rows=%s trade_date=%s", rows, trade_date)

    jygs_result = sync_jygs_action_for_date(trade_date)
    context.log.info("synced jygs action=%s", jygs_result)
    jygs_trade_date = _to_str((jygs_result or {}).get("trade_date")) or trade_date
    if jygs_trade_date != trade_date:
        raise RuntimeError(
            f"trade_date mismatch xgb={trade_date} jygs={jygs_trade_date}"
        )

    plate_reason_count = persist_plate_reason_daily_for_date(trade_date)
    context.log.info(
        "built plate_reason_daily rows=%s trade_date=%s",
        plate_reason_count,
        trade_date,
    )

    gantt_result = persist_gantt_daily_for_date(trade_date)
    context.log.info("built gantt daily=%s", gantt_result)

    stock_hot_reason_count = persist_stock_hot_reason_daily_for_date(trade_date)
    context.log.info(
        "built stock_hot_reason_daily rows=%s trade_date=%s",
        stock_hot_reason_count,
        trade_date,
    )
    shouban30_result = _build_shouban30_snapshots_for_date(context, trade_date)

    return {
        "trade_date": trade_date,
        "xgb_rows": rows,
        "jygs": jygs_result,
        "plate_reason_rows": plate_reason_count,
        "gantt": gantt_result,
        "stock_hot_reason_rows": stock_hot_reason_count,
        "shouban30": shouban30_result,
    }


def run_gantt_backfill(context) -> list[str]:
    latest_trade_date = _query_latest_trade_date()
    latest_completed_trade_date = _query_latest_completed_gantt_trade_date()
    trade_dates = resolve_gantt_backfill_trade_dates()

    context.log.info(
        "gantt postclose incremental latest_trade_date=%s latest_completed_trade_date=%s pending_days=%s",
        latest_trade_date,
        latest_completed_trade_date,
        len(trade_dates),
    )
    if not trade_dates:
        return []

    processed_trade_dates: list[str] = []
    for trade_date in trade_dates:
        context.log.info("gantt postclose incremental start trade_date=%s", trade_date)
        run_gantt_pipeline_for_date(context, trade_date)
        processed_trade_dates.append(trade_date)

    context.log.info(
        "gantt postclose incremental done days=%s start=%s end=%s",
        len(processed_trade_dates),
        processed_trade_dates[0],
        processed_trade_dates[-1],
    )
    return processed_trade_dates


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
def op_build_stock_hot_reason_daily(context, trade_date: str) -> str:
    count = persist_stock_hot_reason_daily_for_date(trade_date)
    context.log.info(
        "built stock_hot_reason_daily rows=%s trade_date=%s", count, trade_date
    )
    return trade_date


@op
def op_build_shouban30_daily(context, trade_date: str) -> dict:
    return _build_shouban30_snapshots_for_date(context, trade_date)


@op
def op_run_gantt_postclose_incremental(context) -> list[str]:
    return run_gantt_backfill(context)
