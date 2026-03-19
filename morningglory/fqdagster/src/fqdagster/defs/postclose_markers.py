from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from freshquant.config import cfg
from freshquant.data.trade_date_hist import tool_trade_date_hist_sina
from freshquant.db import DBfreshquant

COL_POSTCLOSE_MARKERS = "dagster_pipeline_markers"
POSTCLOSE_CUTOFF_HOUR = 15
POSTCLOSE_CUTOFF_MINUTE = 5


def _get_marker_collection(collection=None):
    if collection is not None:
        return collection
    return DBfreshquant[COL_POSTCLOSE_MARKERS]


def _ensure_marker_indexes(collection) -> None:
    collection.create_index(
        [("pipeline_key", 1), ("trade_date", 1)],
        unique=True,
        name="uniq_pipeline_trade_date",
    )


def _normalize_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    status: str = "success",
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    now_provider=None,
) -> dict[str, Any]:
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))
    return {
        "pipeline_key": str(pipeline_key or "").strip(),
        "trade_date": str(trade_date or "").strip(),
        "status": str(status or "").strip() or "success",
        "updated_at": now_provider().isoformat(),
        "run_id": str(run_id or "").strip(),
        "payload": dict(payload or {}),
    }


def resolve_latest_completed_trade_date(
    *,
    now_provider=None,
    trade_dates_provider=None,
) -> str:
    trade_dates_provider = trade_dates_provider or tool_trade_date_hist_sina
    trade_dates = list(trade_dates_provider()["trade_date"])
    if not trade_dates:
        raise RuntimeError("no trade dates available")

    now = now_provider() if callable(now_provider) else datetime.now(cfg.TZ)
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


def upsert_postclose_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    status: str = "success",
    run_id: str | None = None,
    payload: dict[str, Any] | None = None,
    collection=None,
    now_provider=None,
) -> dict[str, Any]:
    target_collection = _get_marker_collection(collection)
    _ensure_marker_indexes(target_collection)
    marker = _normalize_marker(
        pipeline_key,
        trade_date,
        status=status,
        run_id=run_id,
        payload=payload,
        now_provider=now_provider,
    )
    target_collection.update_one(
        {
            "pipeline_key": marker["pipeline_key"],
            "trade_date": marker["trade_date"],
        },
        {"$set": marker},
        upsert=True,
    )
    return marker


def get_postclose_marker(pipeline_key: str, trade_date: str, *, collection=None):
    target_collection = _get_marker_collection(collection)
    return target_collection.find_one(
        {
            "pipeline_key": str(pipeline_key or "").strip(),
            "trade_date": str(trade_date or "").strip(),
        }
    )


def has_success_postclose_marker(
    pipeline_key: str,
    trade_date: str,
    *,
    collection=None,
) -> bool:
    marker = get_postclose_marker(pipeline_key, trade_date, collection=collection)
    return bool(marker) and str(marker.get("status") or "").strip() == "success"


def delete_postclose_marker(pipeline_key: str, trade_date: str, *, collection=None):
    target_collection = _get_marker_collection(collection)
    target_collection.delete_many(
        {
            "pipeline_key": str(pipeline_key or "").strip(),
            "trade_date": str(trade_date or "").strip(),
        }
    )
