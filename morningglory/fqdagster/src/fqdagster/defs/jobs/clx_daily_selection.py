from __future__ import annotations

from dagster import Failure, job, op

from freshquant.clx_daily_selection.service import ClxDailySelectionService

from ..postclose_markers import get_postclose_marker, upsert_postclose_marker


def _run_tags(context) -> dict[str, str]:
    run = getattr(context, "run", None)
    tags = getattr(run, "tags", None)
    return dict(tags or {})


def _make_service(*, ready_marker_publisher=None) -> ClxDailySelectionService:
    return ClxDailySelectionService(ready_marker_publisher=ready_marker_publisher)


def _required_tag(tags: dict[str, str], key: str) -> str:
    value = str(tags.get(key) or "").strip()
    if not value:
        raise Failure(f"CLX run requires {key} tag")
    return value


def _required_positive_int_tag(tags: dict[str, str], key: str) -> int:
    value = _required_tag(tags, key)
    if not value.isdigit() or int(value) < 1:
        raise Failure(f"CLX run requires {key} to be a positive integer")
    return int(value)


def _qfq_snapshot_ids(tags: dict[str, str]) -> dict[str, str]:
    return {
        asset_type: _required_tag(tags, f"fq_clx_qfq_{asset_type}_snapshot_id")
        for asset_type in ("stock", "etf")
    }


@op
def clx_daily_selection_partition_op(context) -> dict:
    tags = _run_tags(context)
    asset_type = str(tags.get("fq_clx_asset_type") or "").strip()
    attempt_id = str(tags.get("fq_clx_attempt_id") or "").strip()
    if asset_type not in {"stock", "etf"} or not attempt_id:
        raise Failure("CLX partition job requires asset_type and attempt_id tags")
    trade_date = _required_tag(tags, "fq_trade_date")
    expected_attempt_no = _required_positive_int_tag(tags, "fq_clx_attempt_no")
    expected_selection_key = _required_tag(tags, "fq_clx_selection_key")
    expected_marker_hash = _required_tag(tags, "fq_clx_marker_snapshot_hash")
    expected_qfq_pair_hash = _required_tag(tags, "fq_clx_qfq_snapshot_pair_hash")
    expected_qfq_snapshot_ids = _qfq_snapshot_ids(tags)
    expected_effective_universe_hash = _required_tag(
        tags, "fq_clx_effective_universe_hash"
    )
    expected_universe_isolation_hash = _required_tag(
        tags, "fq_clx_universe_isolation_hash"
    )
    service = _make_service()
    result = service.execute_partition(
        attempt_id,
        lambda requested_asset: get_postclose_marker(
            f"{requested_asset}_postclose_ready",
            trade_date,
        ),
        claim_owner=str(getattr(context, "run_id", None) or "").strip() or None,
        expected_asset_type=asset_type,
        expected_trade_date=trade_date,
        expected_attempt_no=expected_attempt_no,
        expected_selection_key=expected_selection_key,
        expected_marker_snapshot_hash=expected_marker_hash,
        expected_qfq_snapshot_pair_hash=expected_qfq_pair_hash,
        expected_qfq_snapshot_ids=expected_qfq_snapshot_ids,
        expected_effective_universe_hash=expected_effective_universe_hash,
        expected_universe_isolation_hash=expected_universe_isolation_hash,
    )
    if result.get("status") != "completed":
        raise Failure(
            f"CLX {asset_type} partition ended as {result.get('status') or 'unknown'}"
        )
    return result


@job(
    tags={
        "dagster/max_concurrent_runs": "2",
        "dagster/max_retries": "0",
    }
)
def clx_daily_selection_partition_job():
    clx_daily_selection_partition_op()


@op
def clx_daily_selection_finalize_op(context) -> dict:
    tags = _run_tags(context)
    trade_date = str(tags.get("fq_trade_date") or "").strip()
    batch_id = str(tags.get("fq_clx_batch_id") or "").strip()
    finalization_attempt_id = str(
        tags.get("fq_clx_finalization_attempt_id") or ""
    ).strip()
    partition_ids = [
        item.strip()
        for item in str(tags.get("fq_clx_partition_ids") or "").split(",")
        if item.strip()
    ]
    if not trade_date or not batch_id or not finalization_attempt_id:
        raise Failure(
            "CLX finalizer requires trade_date, batch_id, and finalization attempt tags"
        )
    if len(partition_ids) != 2:
        raise Failure("CLX finalizer requires exactly two immutable partition ids")
    expected_attempt_no = _required_positive_int_tag(
        tags, "fq_clx_finalization_attempt_no"
    )
    expected_qfq_pair_hash = _required_tag(tags, "fq_clx_qfq_snapshot_pair_hash")
    expected_qfq_snapshot_ids = _qfq_snapshot_ids(tags)
    expected_generation_order = _required_tag(tags, "fq_clx_generation_order")

    def publish_ready_marker(published_trade_date: str, payload: dict):
        return upsert_postclose_marker(
            "clx_daily_selection_ready",
            published_trade_date,
            run_id=getattr(context, "run_id", None),
            payload=payload,
            generation_id=payload.get("generation_id"),
            generation_order=payload.get("generation_order"),
            publication_id=payload.get("publication_id"),
        )

    result = _make_service(
        ready_marker_publisher=publish_ready_marker
    ).execute_finalization(
        finalization_attempt_id,
        lambda asset_type: get_postclose_marker(
            f"{asset_type}_postclose_ready", trade_date
        ),
        claim_owner=str(getattr(context, "run_id", None) or "").strip() or None,
        expected_trade_date=trade_date,
        expected_batch_id=batch_id,
        expected_attempt_no=expected_attempt_no,
        expected_partition_ids=partition_ids,
        expected_qfq_snapshot_pair_hash=expected_qfq_pair_hash,
        expected_qfq_snapshot_ids=expected_qfq_snapshot_ids,
        expected_generation_order=expected_generation_order,
    )
    if not result.get("is_final"):
        raise Failure(f"CLX finalizer ended as {result.get('status') or 'unknown'}")
    return result


@job(tags={"dagster/max_concurrent_runs": "1", "dagster/max_retries": "0"})
def clx_daily_selection_finalize_job():
    clx_daily_selection_finalize_op()


@op
def clx_pre_pool_reconcile_op(context) -> dict:
    """按当前 ready marker generation 对账 stock_pre_pools 的 CLX membership。"""
    tags = _run_tags(context)
    trade_date = str(tags.get("fq_trade_date") or "").strip()
    expected_batch_id = str(tags.get("fq_clx_batch_id") or "").strip()
    if not trade_date:
        raise Failure("CLX pre reconcile requires fq_trade_date tag")

    from freshquant.clx_daily_selection.pre_reconciliation import (
        reconcile_pre_pool_for_trade_date,
    )

    result = reconcile_pre_pool_for_trade_date(trade_date)
    status = str(result.get("status") or "").strip()
    if status == "skipped":
        raise Failure(f"CLX pre reconcile skipped: {result.get('reason')}")
    if status != "reconciled":
        raise Failure(
            f"CLX pre reconcile failed: {status} "
            f"({result.get('reason') or 'unknown'})"
        )
    actual_batch_id = str(result.get("batch_id") or "").strip()
    if expected_batch_id and actual_batch_id != expected_batch_id:
        raise Failure(
            "CLX pre reconcile generation drift: "
            f"expected={expected_batch_id} actual={actual_batch_id}"
        )
    return result


@job(tags={"dagster/max_concurrent_runs": "1", "dagster/max_retries": "0"})
def clx_pre_pool_reconcile_job():
    clx_pre_pool_reconcile_op()
