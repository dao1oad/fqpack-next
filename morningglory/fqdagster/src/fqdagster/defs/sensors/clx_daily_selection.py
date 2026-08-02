from __future__ import annotations

from dagster import RunRequest, SkipReason, sensor

from freshquant.clx_daily_selection.service import ClxDailySelectionService

from ..jobs.clx_daily_selection import (
    clx_daily_selection_finalize_job,
    clx_daily_selection_partition_job,
)
from ..postclose_markers import (
    get_postclose_marker,
    resolve_recent_completed_trade_dates,
)


def _make_service() -> ClxDailySelectionService:
    return ClxDailySelectionService()


def _partition_sensor_result(asset_type: str):
    pipeline_key = f"{asset_type}_postclose_ready"
    service = _make_service()
    skip_message = None
    for trade_date in resolve_recent_completed_trade_dates(limit=5):
        marker = get_postclose_marker(pipeline_key, trade_date)
        if not marker or str(marker.get("status") or "") != "success":
            skip_message = skip_message or f"{pipeline_key} missing for {trade_date}"
            continue
        plan = service.plan_partition(asset_type, marker)
        if plan["action"] == "reuse":
            skip_message = skip_message or (
                f"{asset_type} partition already completed for {trade_date}"
            )
            continue
        if plan["action"] == "active":
            return SkipReason(
                f"{asset_type} partition attempt already active for {trade_date}"
            )
        return RunRequest(
            run_key=plan["run_key"],
            tags={
                "fq_trade_date": trade_date,
                "fq_clx_asset_type": asset_type,
                "fq_clx_attempt_id": plan["attempt_id"],
                "fq_clx_attempt_no": str(plan["attempt_no"]),
                "fq_clx_selection_key": plan["selection_key"],
                "fq_clx_marker_snapshot_hash": plan["marker_snapshot_hash"],
            },
        )
    return SkipReason(
        skip_message or f"no recent completed trade dates for {asset_type} partition"
    )


@sensor(job=clx_daily_selection_partition_job, minimum_interval_seconds=30)
def clx_daily_selection_stock_sensor(_context):
    return _partition_sensor_result("stock")


@sensor(job=clx_daily_selection_partition_job, minimum_interval_seconds=30)
def clx_daily_selection_etf_sensor(_context):
    return _partition_sensor_result("etf")


@sensor(job=clx_daily_selection_finalize_job, minimum_interval_seconds=30)
def clx_daily_selection_finalizer_sensor(_context):
    service = _make_service()
    skip_message = None
    for trade_date in resolve_recent_completed_trade_dates(limit=5):
        plan = service.plan_finalization(
            trade_date,
            lambda asset_type, trade_date=trade_date: get_postclose_marker(
                f"{asset_type}_postclose_ready", trade_date
            ),
        )
        if plan["action"] == "reuse":
            skip_message = skip_message or (
                f"CLX final batch already published for {trade_date}"
            )
            continue
        if plan["action"] == "active":
            return SkipReason(
                f"CLX final batch publication already active for {trade_date}"
            )
        if plan["action"] == "wait":
            states = plan["partitions"]
            skip_message = skip_message or (
                "CLX finalizer waiting for partitions: "
                + ", ".join(
                    f"{asset_type}={states[asset_type]['status']}"
                    for asset_type in ("stock", "etf")
                )
            )
            continue
        return RunRequest(
            run_key=plan["run_key"],
            tags={
                "fq_trade_date": trade_date,
                "fq_clx_batch_id": plan["batch_id"],
                "fq_clx_partition_ids": ",".join(plan["partition_ids"]),
                "fq_clx_finalization_attempt_id": plan["finalization_attempt_id"],
                "fq_clx_finalization_attempt_no": str(plan["finalization_attempt_no"]),
            },
        )
    return SkipReason(
        skip_message or "no recent completed trade dates for CLX finalization"
    )
