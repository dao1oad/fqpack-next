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


@op
def clx_daily_selection_partition_op(context) -> dict:
    tags = _run_tags(context)
    asset_type = str(tags.get("fq_clx_asset_type") or "").strip()
    attempt_id = str(tags.get("fq_clx_attempt_id") or "").strip()
    if asset_type not in {"stock", "etf"} or not attempt_id:
        raise Failure("CLX partition job requires asset_type and attempt_id tags")
    service = _make_service()
    result = service.execute_partition(
        attempt_id,
        lambda requested_asset: get_postclose_marker(
            f"{requested_asset}_postclose_ready",
            str(tags.get("fq_trade_date") or "").strip(),
        ),
        claim_owner=str(getattr(context, "run_id", None) or "").strip() or None,
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
        expected_partition_ids=partition_ids,
    )
    if not result.get("is_final"):
        raise Failure(f"CLX finalizer ended as {result.get('status') or 'unknown'}")
    return result


@job(tags={"dagster/max_concurrent_runs": "1", "dagster/max_retries": "0"})
def clx_daily_selection_finalize_job():
    clx_daily_selection_finalize_op()
