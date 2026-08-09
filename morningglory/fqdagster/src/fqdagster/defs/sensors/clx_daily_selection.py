from __future__ import annotations

import json

from dagster import RunRequest, SensorResult, SkipReason, sensor

from freshquant.clx_daily_selection.ready_marker import (
    get_clx_ready_marker,
    normalize_ready_generation,
)
from freshquant.clx_daily_selection.service import ClxDailySelectionService

from ..jobs.clx_daily_selection import (
    clx_daily_selection_finalize_job,
    clx_daily_selection_partition_job,
    clx_pre_pool_reconcile_job,
)
from ..postclose_markers import (
    get_postclose_marker,
    resolve_recent_completed_trade_dates,
)


def _make_service() -> ClxDailySelectionService:
    return ClxDailySelectionService()


def _qfq_snapshot_tags(plan: dict) -> dict[str, str]:
    pair = plan.get("qfq_snapshot_pair")
    pair_hash = str(plan.get("qfq_snapshot_pair_hash") or "").strip()
    if not isinstance(pair, dict) or not pair_hash:
        raise ValueError("CLX plan is missing the frozen QFQ snapshot pair")
    tags = {"fq_clx_qfq_snapshot_pair_hash": pair_hash}
    for asset_type in ("stock", "etf"):
        snapshot = pair.get(asset_type)
        snapshot_id = (
            str(snapshot.get("snapshot_id") or "").strip()
            if isinstance(snapshot, dict)
            else ""
        )
        if not snapshot_id:
            raise ValueError(f"CLX plan is missing {asset_type} QFQ snapshot identity")
        tags[f"fq_clx_qfq_{asset_type}_snapshot_id"] = snapshot_id
    return tags


def _partition_universe_tags(plan: dict) -> dict[str, str]:
    tags = {}
    for field, tag in (
        ("effective_universe_hash", "fq_clx_effective_universe_hash"),
        ("universe_isolation_hash", "fq_clx_universe_isolation_hash"),
    ):
        value = str(plan.get(field) or "").strip()
        if not value:
            raise ValueError(f"CLX partition plan is missing {field}")
        tags[tag] = value
    return tags


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
                **_qfq_snapshot_tags(plan),
                **_partition_universe_tags(plan),
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
                "fq_clx_generation_order": str(plan["generation_order"]),
                **_qfq_snapshot_tags(plan),
            },
        )
    return SkipReason(
        skip_message or "no recent completed trade dates for CLX finalization"
    )


@sensor(job=clx_pre_pool_reconcile_job, minimum_interval_seconds=60)
def clx_pre_pool_reconcile_sensor(context):
    """按 ready marker generation 触发 stock_pre_pools CLX membership 对账。

    - 只认 ready marker 的 generation（trade_date + generation_id + publication_id）；
    - 游标只在 job 成功写出 ``clx_pre_pool_reconcile_done`` marker 后才推进，
      避免 job 失败后（无重试）后续 tick 误判为已处理而永久跳过；
    - 失败后重新请求使用递增 attempt 的 run_key，保证 Dagster run_key 去重
      不会吞掉重试。
    """
    try:
        cursor = json.loads(context.cursor) if context.cursor else {}
    except (TypeError, ValueError):
        cursor = {}

    for trade_date in resolve_recent_completed_trade_dates(limit=5):
        marker = get_clx_ready_marker(trade_date=trade_date)
        generation = normalize_ready_generation(marker)
        if not generation or not generation["batch_id"]:
            continue
        done_marker = get_postclose_marker("clx_pre_pool_reconcile_done", trade_date)
        done_payload = dict(done_marker.get("payload") or {}) if done_marker else {}
        done_generation_id = str(
            (
                done_payload.get("generation_id")
                or (done_marker.get("generation_id") if done_marker else None)
                or ""
            )
        ).strip()
        done_publication_id = str(
            (
                done_payload.get("publication_id")
                or (done_marker.get("publication_id") if done_marker else None)
                or ""
            )
        ).strip()
        if (
            done_generation_id == generation["generation_id"]
            and done_publication_id == generation["publication_id"]
        ):
            # 该 generation 已成功对账：推进 cursor 并跳过。
            new_cursor = dict(cursor or {})
            new_cursor[trade_date] = {
                "generation_id": generation["generation_id"],
                "publication_id": generation["publication_id"],
                "batch_id": generation["batch_id"],
                "content_hash": generation["content_hash"],
                "status": "done",
            }
            cursor = new_cursor
            continue
        last = cursor.get(trade_date) or {} if isinstance(cursor, dict) else {}
        same_generation_requested = (
            last.get("generation_id") == generation["generation_id"]
            and last.get("publication_id") == generation["publication_id"]
        )
        attempt = int(last.get("attempt") or 0) + 1 if same_generation_requested else 1
        run_key = (
            f"clx-pre-reconcile:{trade_date}:{generation['generation_id']}"
            f":{generation['publication_id']}:attempt-{attempt}"
        )
        new_cursor = dict(cursor or {})
        new_cursor[trade_date] = {
            "generation_id": generation["generation_id"],
            "publication_id": generation["publication_id"],
            "batch_id": generation["batch_id"],
            "content_hash": generation["content_hash"],
            "attempt": attempt,
            "status": "requested",
        }
        return SensorResult(
            run_requests=[
                RunRequest(
                    run_key=run_key,
                    tags={
                        "fq_trade_date": trade_date,
                        "fq_clx_batch_id": generation["batch_id"],
                        "fq_clx_generation_id": generation["generation_id"],
                        "fq_clx_generation_order": generation["generation_order"],
                        "fq_clx_publication_id": generation["publication_id"],
                        "fq_clx_content_hash": generation["content_hash"],
                    },
                )
            ],
            cursor=json.dumps(new_cursor, ensure_ascii=False, sort_keys=True),
        )
    return SkipReason("no new CLX ready generation to reconcile")
