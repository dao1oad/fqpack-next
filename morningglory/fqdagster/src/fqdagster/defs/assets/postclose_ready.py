from __future__ import annotations

from typing import Any

from dagster import asset

from freshquant.data.quality_stock_universe import refresh_quality_stock_universe

from ..postclose_markers import resolve_latest_completed_trade_date


@asset(group_name="postclose_ready")
def refresh_quality_stock_universe_snapshot(
    stock_block: str, stock_day: str
) -> dict[str, Any]:
    result = dict(refresh_quality_stock_universe() or {})
    return {
        "trade_date": resolve_latest_completed_trade_date(),
        "count": int(result.get("count") or 0),
        "source_version": str(result.get("source_version") or "").strip(),
        "updated_at": str(result.get("updated_at") or "").strip(),
    }
