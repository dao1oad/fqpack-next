# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from typing import Any

from freshquant.runtime_observability.clickhouse_store import (
    RuntimeObservabilityClickHouseStore,
    RuntimeObservabilityStoreError,
)
from freshquant.util.code import normalize_to_base_code


class PositionReviewRuntimeRepository:
    """Optional ClickHouse evidence reader.

    Runtime events provide the historical rule parameters and trace context.
    They never replace XT trades or the order ledger as business truth.
    """

    def __init__(self, store=None):
        self.store = store or RuntimeObservabilityClickHouseStore(
            base_url=(
                os.environ.get("FQ_RUNTIME_CLICKHOUSE_URL") or "http://127.0.0.1:18123"
            ),
            database=(
                os.environ.get("FQ_RUNTIME_CLICKHOUSE_DATABASE")
                or "runtime_observability"
            ),
            username=(os.environ.get("FQ_RUNTIME_CLICKHOUSE_USER") or "fq_runtime"),
            password=(os.environ.get("FQ_RUNTIME_CLICKHOUSE_PASSWORD") or "fq_runtime"),
        )

    def list_guardian_events(
        self,
        symbol: str,
        *,
        page_size: int = 2_000,
        max_events: int = 100_000,
    ) -> dict:
        return self._list_guardian_events(
            symbol=symbol,
            page_size=page_size,
            max_events=max_events,
        )

    def list_guardian_events_by_symbol(
        self,
        *,
        page_size: int = 5_000,
        max_events: int = 500_000,
    ) -> dict:
        result = self._list_guardian_events(
            symbol=None,
            page_size=page_size,
            max_events=max_events,
        )
        items_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for item in result.get("items") or []:
            symbol = normalize_to_base_code(str(item.get("symbol") or "").strip())
            if symbol:
                items_by_symbol.setdefault(symbol, []).append(item)
        return {
            **result,
            "items_by_symbol": items_by_symbol,
        }

    def _list_guardian_events(
        self,
        *,
        symbol,
        page_size,
        max_events,
    ):
        items = []
        cursor_ts = ""
        cursor_event_id = ""
        next_cursor = None
        try:
            while len(items) < max_events:
                filters = {
                    "component": "guardian_strategy",
                    "node": [
                        "price_threshold_check",
                        "sellable_volume_check",
                    ],
                }
                if symbol:
                    filters["symbol"] = symbol
                page = self.store.list_events(
                    filters=filters,
                    limit=min(page_size, max_events - len(items)),
                    cursor_ts=cursor_ts,
                    cursor_event_id=cursor_event_id,
                )
                page_items = list(page.get("items") or [])
                items.extend(page_items)
                next_cursor = page.get("next_cursor")
                if not next_cursor or not page_items:
                    break
                cursor_ts = str(next_cursor.get("ts") or "")
                cursor_event_id = str(next_cursor.get("event_id") or "")
            return {
                "available": True,
                "items": items,
                "error": None,
                "truncated": bool(next_cursor and len(items) >= max_events),
                "max_events": max_events,
            }
        except RuntimeObservabilityStoreError as exc:
            return {
                "available": False,
                "items": [],
                "error": str(exc),
                "truncated": False,
                "max_events": max_events,
            }


__all__ = ["PositionReviewRuntimeRepository"]
