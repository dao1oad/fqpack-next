from datetime import datetime
from typing import Any, Generator

from dagster import DynamicOut, DynamicOutput, Output, graph, op
from dagster._core.events import DagsterEvent, EngineEventData

from freshquant.data.gantt_readmodel import (
    persist_gantt_daily_for_date,
    persist_plate_reason_daily_for_date,
    persist_shouban30_for_date,
    persist_stock_hot_reason_daily_for_date,
)
from freshquant.data.gantt_source_jygs import sync_jygs_action_for_date
from freshquant.data.gantt_source_xgb import sync_xgb_history_for_date
from freshquant.data.quality_stock_universe import refresh_quality_stock_universe
from freshquant.data.trade_date_hist import (
    get_trade_dates_between,
    tool_trade_date_hist_sina,
)
from freshquant.db import DBGantt

COL_GANTT_PLATE_DAILY = "gantt_plate_daily"
COL_SHOUBAN30_PLATES = "shouban30_plates"
COL_SHOUBAN30_STOCKS = "shouban30_stocks"
POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5
SHOUBAN30_STOCK_WINDOWS = (30, 45, 60, 90)
SHOUBAN30_EXTRA_FILTER_FIELDS = (
    "is_credit_subject",
    "credit_subject_snapshot_ready",
    "near_long_term_ma_passed",
    "is_quality_subject",
    "quality_subject_snapshot_ready",
)


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
    docs = list(collection.find({"as_of_date": date_str}))
    if not docs:
        return False

    windows = set()
    for doc in docs:
        stock_window_days = doc.get("stock_window_days")
        if (
            not isinstance(stock_window_days, int)
            or stock_window_days not in SHOUBAN30_STOCK_WINDOWS
        ):
            return True
        if not _to_str(doc.get("chanlun_filter_version")):
            return True
        windows.add(stock_window_days)

    if windows != set(SHOUBAN30_STOCK_WINDOWS):
        return True

    stock_docs = list(DBGantt[COL_SHOUBAN30_STOCKS].find({"as_of_date": date_str}))
    if not stock_docs:
        return True

    for doc in stock_docs:
        if not _to_str(doc.get("chanlun_filter_version")):
            return True
        if any(field not in doc for field in SHOUBAN30_EXTRA_FILTER_FIELDS):
            return True

    return False


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


def _require_result_trade_date(result: dict[str, Any] | None, source_name: str) -> str:
    trade_date = _to_str((result or {}).get("trade_date"))
    if not trade_date:
        raise RuntimeError(f"missing trade_date in {source_name} result")
    return trade_date


def _build_trade_date_mapping_key(trade_date: str) -> str:
    return _to_str(trade_date).replace("-", "_")


def _format_log_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ",".join(_to_str(item) for item in value if _to_str(item))
    return _to_str(value)


def _log_postclose_event(
    context,
    *,
    event: str,
    stage: str,
    trade_date: str | None = None,
    **fields: Any,
) -> DagsterEvent:
    parts = [f"gantt postclose event={_to_str(event)}", f"stage={_to_str(stage)}"]
    if _to_str(trade_date):
        rendered_trade_date = _to_str(trade_date)
        parts.append(f"trade_date={rendered_trade_date}")
    for key, value in fields.items():
        formatted = _format_log_value(value)
        if not formatted:
            continue
        parts.append(f"{key}={formatted}")
    message = " ".join(parts)
    return DagsterEvent.engine_event(
        context.get_step_execution_context(),
        message,
        EngineEventData(),
    )


def _build_shouban30_snapshots_for_date(context, trade_date: str) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    chanlun_result_cache: dict[str, dict[str, Any]] = {}
    for stock_window_days in SHOUBAN30_STOCK_WINDOWS:
        result = persist_shouban30_for_date(
            trade_date,
            stock_window_days=stock_window_days,
            chanlun_result_cache=chanlun_result_cache,
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
    quality_stock_result = refresh_quality_stock_universe()
    context.log.info(
        "refreshed quality_stock_universe trade_date=%s result=%s",
        trade_date,
        quality_stock_result,
    )
    shouban30_result = _build_shouban30_snapshots_for_date(context, trade_date)

    return {
        "trade_date": trade_date,
        "xgb_rows": rows,
        "jygs": jygs_result,
        "plate_reason_rows": plate_reason_count,
        "gantt": gantt_result,
        "stock_hot_reason_rows": stock_hot_reason_count,
        "quality_stock_universe": quality_stock_result,
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


@op(out=DynamicOut(str))
def op_resolve_pending_gantt_trade_dates(context):
    yield _log_postclose_event(
        context,
        event="start",
        stage="resolve_pending_trade_dates",
    )
    trade_dates = resolve_gantt_backfill_trade_dates()
    context.log.info("resolved gantt pending trade_dates=%s", trade_dates)
    yield _log_postclose_event(
        context,
        event="done",
        stage="resolve_pending_trade_dates",
        pending_count=len(trade_dates),
        trade_dates=trade_dates,
    )
    for trade_date in trade_dates:
        yield DynamicOutput(
            trade_date, mapping_key=_build_trade_date_mapping_key(trade_date)
        )


@op
def op_sync_xgb_history_daily(context) -> Generator[object, None, None]:
    trade_date = _resolve_trade_date()
    yield _log_postclose_event(
        context,
        event="start",
        stage="sync_xgb_history",
        trade_date=trade_date,
    )
    rows = sync_xgb_history_for_date(trade_date)
    context.log.info("synced xgb history rows=%s trade_date=%s", rows, trade_date)
    yield _log_postclose_event(
        context,
        event="done",
        stage="sync_xgb_history",
        trade_date=trade_date,
        rows=rows,
    )
    yield Output(trade_date)


@op
def op_sync_jygs_action_daily(context) -> Generator[object, None, None]:
    trade_date = _resolve_trade_date()
    yield _log_postclose_event(
        context,
        event="start",
        stage="sync_jygs_action",
        trade_date=trade_date,
    )
    result = sync_jygs_action_for_date(trade_date)
    context.log.info("synced jygs action=%s", result)
    resolved_trade_date = _require_result_trade_date(result, "jygs action")
    yield _log_postclose_event(
        context,
        event="done",
        stage="sync_jygs_action",
        trade_date=resolved_trade_date,
        result=result,
    )
    yield Output(resolved_trade_date)


@op
def op_sync_xgb_history_for_trade_date(
    context, trade_date: str
) -> Generator[object, None, None]:
    resolved_trade_date = _to_str(trade_date)
    yield _log_postclose_event(
        context,
        event="start",
        stage="sync_xgb_history",
        trade_date=resolved_trade_date,
    )
    rows = sync_xgb_history_for_date(resolved_trade_date)
    context.log.info("synced xgb history rows=%s trade_date=%s", rows, trade_date)
    yield _log_postclose_event(
        context,
        event="done",
        stage="sync_xgb_history",
        trade_date=resolved_trade_date,
        rows=rows,
    )
    yield Output(resolved_trade_date)


@op
def op_sync_jygs_action_for_trade_date(
    context, trade_date: str
) -> Generator[object, None, None]:
    resolved_trade_date = _to_str(trade_date)
    yield _log_postclose_event(
        context,
        event="start",
        stage="sync_jygs_action",
        trade_date=resolved_trade_date,
    )
    result = sync_jygs_action_for_date(resolved_trade_date)
    context.log.info("synced jygs action=%s", result)
    result_trade_date = _require_result_trade_date(result, "jygs action")
    yield _log_postclose_event(
        context,
        event="done",
        stage="sync_jygs_action",
        trade_date=result_trade_date,
        result=result,
    )
    yield Output(result_trade_date)


@op
def op_build_plate_reason_daily(
    context, xgb_trade_date: str, jygs_trade_date: str
) -> Generator[object, None, None]:
    yield _log_postclose_event(
        context,
        event="start",
        stage="build_plate_reason_daily",
        trade_date=xgb_trade_date,
        jygs_trade_date=jygs_trade_date,
    )
    if xgb_trade_date != jygs_trade_date:
        raise RuntimeError(
            f"trade_date mismatch xgb={xgb_trade_date} jygs={jygs_trade_date}"
        )
    count = persist_plate_reason_daily_for_date(xgb_trade_date)
    context.log.info(
        "built plate_reason_daily rows=%s trade_date=%s", count, xgb_trade_date
    )
    yield _log_postclose_event(
        context,
        event="done",
        stage="build_plate_reason_daily",
        trade_date=xgb_trade_date,
        rows=count,
    )
    yield Output(xgb_trade_date)


@op
def op_build_gantt_daily(context, trade_date: str) -> Generator[object, None, None]:
    yield _log_postclose_event(
        context,
        event="start",
        stage="build_gantt_daily",
        trade_date=trade_date,
    )
    result = persist_gantt_daily_for_date(trade_date)
    context.log.info("built gantt daily=%s", result)
    yield _log_postclose_event(
        context,
        event="done",
        stage="build_gantt_daily",
        trade_date=trade_date,
        result=result,
    )
    yield Output(trade_date)


@op
def op_build_stock_hot_reason_daily(
    context, trade_date: str
) -> Generator[object, None, None]:
    yield _log_postclose_event(
        context,
        event="start",
        stage="build_stock_hot_reason_daily",
        trade_date=trade_date,
    )
    count = persist_stock_hot_reason_daily_for_date(trade_date)
    context.log.info(
        "built stock_hot_reason_daily rows=%s trade_date=%s", count, trade_date
    )
    yield _log_postclose_event(
        context,
        event="done",
        stage="build_stock_hot_reason_daily",
        trade_date=trade_date,
        rows=count,
    )
    yield Output(trade_date)


@op
def op_refresh_quality_stock_universe_daily(
    context, trade_date: str
) -> Generator[object, None, None]:
    yield _log_postclose_event(
        context,
        event="start",
        stage="refresh_quality_stock_universe",
        trade_date=trade_date,
    )
    result = refresh_quality_stock_universe()
    context.log.info(
        "refreshed quality_stock_universe trade_date=%s result=%s",
        trade_date,
        result,
    )
    yield _log_postclose_event(
        context,
        event="done",
        stage="refresh_quality_stock_universe",
        trade_date=trade_date,
        count=(result or {}).get("count"),
        source_version=(result or {}).get("source_version"),
    )
    yield Output(trade_date)


@op
def op_build_shouban30_daily(context, trade_date: str) -> Generator[object, None, None]:
    yield _log_postclose_event(
        context,
        event="start",
        stage="build_shouban30",
        trade_date=trade_date,
    )
    results: list[dict[str, Any]] = []
    chanlun_result_cache: dict[str, dict[str, Any]] = {}
    for stock_window_days in SHOUBAN30_STOCK_WINDOWS:
        yield _log_postclose_event(
            context,
            event="progress",
            stage="build_shouban30",
            trade_date=trade_date,
            stock_window_days=stock_window_days,
            status="start",
        )
        result = persist_shouban30_for_date(
            trade_date,
            stock_window_days=stock_window_days,
            chanlun_result_cache=chanlun_result_cache,
        )
        results.append(result)
        context.log.info(
            "built shouban30 trade_date=%s stock_window_days=%s result=%s",
            trade_date,
            stock_window_days,
            result,
        )
        yield _log_postclose_event(
            context,
            event="progress",
            stage="build_shouban30",
            trade_date=trade_date,
            stock_window_days=stock_window_days,
            status="done",
            plates=(result or {}).get("plates"),
            stocks=(result or {}).get("stocks"),
        )
    payload = {
        "trade_date": trade_date,
        "windows": list(SHOUBAN30_STOCK_WINDOWS),
        "results": results,
    }
    yield _log_postclose_event(
        context,
        event="done",
        stage="build_shouban30",
        trade_date=trade_date,
        windows=payload.get("windows"),
    )
    yield Output(payload)


@op
def op_run_gantt_postclose_incremental(context) -> list[str]:
    return run_gantt_backfill(context)


@graph
def graph_gantt_postclose_for_trade_date(trade_date):
    xgb_trade_date = op_sync_xgb_history_for_trade_date(trade_date)
    jygs_trade_date = op_sync_jygs_action_for_trade_date(trade_date)
    agreed_trade_date = op_build_plate_reason_daily(xgb_trade_date, jygs_trade_date)
    gantt_trade_date = op_build_gantt_daily(agreed_trade_date)
    hot_reason_trade_date = op_build_stock_hot_reason_daily(gantt_trade_date)
    quality_stock_trade_date = op_refresh_quality_stock_universe_daily(
        hot_reason_trade_date
    )
    op_build_shouban30_daily(quality_stock_trade_date)


@graph
def graph_gantt_postclose():
    op_resolve_pending_gantt_trade_dates().map(graph_gantt_postclose_for_trade_date)
