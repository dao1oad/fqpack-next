from __future__ import annotations

from typing import Any

from freshquant.db import DBfreshquant

CLX_READY_PIPELINE_KEY = "clx_daily_selection_ready"


def get_clx_ready_marker(
    trade_date: str | None = None, *, collection=None
) -> dict[str, Any] | None:
    """读取 CLX 正式结果 ready marker（pre 自动落池的唯一 generation 锚点）。

    只认 ``dagster_pipeline_markers`` 中 ``pipeline_key=clx_daily_selection_ready``
    的成功 marker；不扫描任意 ``is_final=true`` 批次，也不按最后创建批次推断。
    未指定 trade_date 时返回最近交易日的最新 marker。
    """
    target = (
        collection
        if collection is not None
        else DBfreshquant["dagster_pipeline_markers"]
    )
    query: dict[str, Any] = {
        "pipeline_key": CLX_READY_PIPELINE_KEY,
        "status": "success",
    }
    if trade_date:
        query["trade_date"] = str(trade_date or "").strip()
    marker = target.find_one(query, sort=[("trade_date", -1), ("updated_at", -1)])
    if not marker:
        return None
    return dict(marker)


def normalize_ready_generation(marker: dict[str, Any] | None) -> dict[str, Any] | None:
    """把 ready marker 归一为对账用的 generation 身份。"""
    if not marker:
        return None
    payload = dict(marker.get("payload") or {})
    return {
        "trade_date": str(marker.get("trade_date") or "").strip(),
        "batch_id": str(payload.get("batch_id") or "").strip(),
        "content_hash": str(payload.get("content_hash") or "").strip(),
        "generation_id": str(
            marker.get("generation_id") or payload.get("generation_id") or ""
        ).strip(),
        "generation_order": str(
            marker.get("generation_order") or payload.get("generation_order") or ""
        ).strip(),
        "publication_id": str(
            marker.get("publication_id") or payload.get("publication_id") or ""
        ).strip(),
        "ready_marker_updated_at": str(marker.get("updated_at") or "").strip(),
        "partition_ids": [
            str(item or "").strip()
            for item in (payload.get("partition_ids") or [])
            if str(item or "").strip()
        ],
    }
