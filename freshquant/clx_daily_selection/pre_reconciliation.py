from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from freshquant.pre_pool_service import PrePoolService

from .ready_marker import (
    get_clx_ready_marker,
    normalize_ready_generation,
)
from .repository import classify_direction_mode


def _parse_marker_datetime(value: Any) -> datetime | None:
    """把 ready marker 的 ISO 时间戳解析为 datetime；失败返回 None。

    PrePoolService.upsert_code 会用 ``_pick_earliest/_pick_latest`` 与既有
    ``datetime`` 比较，直接传 ISO 字符串会抛 TypeError；解析失败时返回 None，
    由 service 回退到当前时间。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def build_pure_buy_target(
    repository,
    batch: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    """查询正式批次两个分区的 pure-buy 快照，返回 (codes, asset_type_by_code)。"""
    partition_ids = [
        str(state.get("partition_id"))
        for state in (batch.get("partitions") or {}).values()
        if state.get("status") == "completed" and state.get("partition_id")
    ]
    rows = repository.get_snapshots(partition_ids)
    codes: list[str] = []
    asset_type_by_code: dict[str, str] = {}
    seen: set[str] = set()
    for row in rows:
        if classify_direction_mode(row.get("directions")) != "pure_buy":
            continue
        symbol = str(row.get("symbol") or row.get("code") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        codes.append(symbol)
        asset_type_by_code[symbol] = str(row.get("asset_type") or "").strip()
    return codes, asset_type_by_code


def reconcile_pre_pool_for_ready_marker(
    marker: dict[str, Any] | None,
    *,
    repository=None,
    pre_pool_service: PrePoolService | None = None,
    ready_marker_provider: Callable[[str | None], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """按 ready generation 幂等对账 stock_pre_pools 的 CLX membership。

    流程：
    1. 读取一次 ready marker 并冻结 generation；
    2. 查询该 generation 的 pure-buy 目标集合（Stock + ETF）；
    3. 写入前再次读取 marker；generation 已变化则放弃本次，等待下一次 sensor 重跑；
    4. 按目标集合执行 PrePoolService.reconcile_clx_trade_date。

    不新增 staging 集合与审计系统；任务本身幂等，中途失败由 sensor 重跑收敛。
    """
    from .repository import ClxDailySelectionRepository

    repository = repository if repository is not None else ClxDailySelectionRepository()
    pre_pool_service = pre_pool_service or PrePoolService()
    frozen = normalize_ready_generation(marker)
    if not frozen or not frozen["batch_id"] or not frozen["partition_ids"]:
        return {
            "status": "skipped",
            "reason": "no_ready_generation",
            "trade_date": (frozen or {}).get("trade_date") or "",
        }

    batch = repository.get_batch(frozen["batch_id"])
    if not batch:
        return {
            "status": "failed",
            "reason": "batch_not_found",
            "batch_id": frozen["batch_id"],
            "trade_date": frozen["trade_date"],
        }
    codes, asset_type_by_code = build_pure_buy_target(repository, batch)

    provider = ready_marker_provider or (
        lambda trade_date: get_clx_ready_marker(trade_date=trade_date)
    )
    current_marker = provider(frozen["trade_date"])
    current = normalize_ready_generation(current_marker)
    if not current or current["batch_id"] != frozen["batch_id"]:
        return {
            "status": "aborted",
            "reason": "generation_changed",
            "expected_batch_id": frozen["batch_id"],
            "actual_batch_id": (current or {}).get("batch_id") or "",
            "trade_date": frozen["trade_date"],
        }

    result = pre_pool_service.reconcile_clx_trade_date(
        trade_date=frozen["trade_date"],
        target_codes=codes,
        asset_type_by_code=asset_type_by_code,
        batch_id=frozen["batch_id"],
        publication_id=frozen["publication_id"],
        content_hash=frozen["content_hash"],
        selection_key=f"batch:{frozen['batch_id']}",
        added_at=_parse_marker_datetime(frozen.get("ready_marker_updated_at")),
    )
    return {
        "status": "reconciled",
        "trade_date": frozen["trade_date"],
        "batch_id": frozen["batch_id"],
        "generation_id": frozen["generation_id"],
        "generation_order": frozen["generation_order"],
        "publication_id": frozen["publication_id"],
        "content_hash": frozen["content_hash"],
        "pure_buy_count": len(codes),
        "stock_count": sum(
            1 for asset_type in asset_type_by_code.values() if asset_type == "stock"
        ),
        "etf_count": sum(
            1 for asset_type in asset_type_by_code.values() if asset_type == "etf"
        ),
        **result,
    }


def reconcile_pre_pool_for_trade_date(
    trade_date: str,
    *,
    repository=None,
    pre_pool_service: PrePoolService | None = None,
) -> dict[str, Any]:
    """读取指定交易日 ready marker 并执行对账（供 Dagster sensor 使用）。"""
    marker = get_clx_ready_marker(trade_date=trade_date)
    return reconcile_pre_pool_for_ready_marker(
        marker,
        repository=repository,
        pre_pool_service=pre_pool_service,
    )
