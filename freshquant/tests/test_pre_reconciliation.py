from __future__ import annotations

from datetime import datetime

from freshquant.clx_daily_selection.pre_reconciliation import (
    build_pure_buy_target,
    reconcile_pre_pool_for_ready_marker,
)


class FakeRepository:
    def __init__(self, snapshots=None, batch=None):
        self._snapshots = list(snapshots or [])
        self._batch = batch

    def get_snapshots(self, partition_ids):
        return list(self._snapshots)

    def get_batch(self, batch_id):
        if self._batch and self._batch.get("batch_id") == batch_id:
            return dict(self._batch)
        return None


class FakePrePoolService:
    def __init__(self):
        self.calls = []

    def reconcile_clx_trade_date(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "trade_date": kwargs["trade_date"],
            "category": f"trade_date:{kwargs['trade_date']}",
            "target_count": len(kwargs["target_codes"]),
            "added": 3,
            "updated": 0,
            "unchanged": 0,
            "removed": 1,
        }


def _ready_marker(trade_date="2026-08-07", batch_id="clx-2026-08-07-production_v1-abc"):
    return {
        "pipeline_key": "clx_daily_selection_ready",
        "trade_date": trade_date,
        "status": "success",
        "updated_at": "2026-08-07T20:00:00+08:00",
        "generation_id": batch_id,
        "generation_order": "1",
        "publication_id": "pub-1",
        "payload": {
            "batch_id": batch_id,
            "content_hash": "hash-1",
            "partition_ids": ["p-stock", "p-etf"],
            "generation_id": batch_id,
            "generation_order": "1",
            "publication_id": "pub-1",
        },
    }


def test_build_pure_buy_target_only_includes_exact_buy():
    repository = FakeRepository(
        snapshots=[
            {"symbol": "600000", "asset_type": "stock", "directions": ["buy"]},
            {"symbol": "600001", "asset_type": "stock", "directions": ["sell"]},
            {"symbol": "600002", "asset_type": "stock", "directions": ["buy", "sell"]},
            {"symbol": "600003", "asset_type": "stock", "directions": []},
            {"symbol": "510300", "asset_type": "etf", "directions": ["buy"]},
        ],
        batch={
            "batch_id": "b1",
            "partitions": {
                "stock": {"status": "completed", "partition_id": "p-stock"},
                "etf": {"status": "completed", "partition_id": "p-etf"},
            },
        },
    )

    codes, asset_type_by_code = build_pure_buy_target(repository, repository._batch)

    assert sorted(codes) == ["510300", "600000"]
    assert asset_type_by_code == {"510300": "etf", "600000": "stock"}


def test_reconcile_pre_pool_for_ready_marker_reconciles_frozen_generation():
    repository = FakeRepository(
        snapshots=[
            {"symbol": "600000", "asset_type": "stock", "directions": ["buy"]},
            {"symbol": "510300", "asset_type": "etf", "directions": ["buy"]},
        ],
        batch={
            "batch_id": "clx-2026-08-07-production_v1-abc",
            "partitions": {
                "stock": {"status": "completed", "partition_id": "p-stock"},
                "etf": {"status": "completed", "partition_id": "p-etf"},
            },
        },
    )
    pre_service = FakePrePoolService()

    result = reconcile_pre_pool_for_ready_marker(
        _ready_marker(),
        repository=repository,
        pre_pool_service=pre_service,
        ready_marker_provider=lambda trade_date: _ready_marker(),
    )

    assert result["status"] == "reconciled"
    assert result["batch_id"] == "clx-2026-08-07-production_v1-abc"
    assert result["pure_buy_count"] == 2
    assert result["stock_count"] == 1
    assert result["etf_count"] == 1
    assert result["added"] == 3
    call = pre_service.calls[0]
    assert call["trade_date"] == "2026-08-07"
    assert sorted(call["target_codes"]) == ["510300", "600000"]
    assert call["batch_id"] == "clx-2026-08-07-production_v1-abc"
    assert call["publication_id"] == "pub-1"
    assert call["content_hash"] == "hash-1"
    assert call["asset_type_by_code"] == {"510300": "etf", "600000": "stock"}


def test_reconcile_pre_pool_aborts_when_generation_changed_before_write():
    repository = FakeRepository(
        snapshots=[],
        batch={
            "batch_id": "clx-2026-08-07-production_v1-abc",
            "partitions": {
                "stock": {"status": "completed", "partition_id": "p-stock"},
                "etf": {"status": "completed", "partition_id": "p-etf"},
            },
        },
    )
    pre_service = FakePrePoolService()

    def _changed_marker(trade_date):
        marker = _ready_marker()
        marker["batch_id"] = "clx-2026-08-07-production_v1-newer"
        marker["generation_id"] = "clx-2026-08-07-production_v1-newer"
        marker["publication_id"] = "pub-2"
        marker["payload"]["batch_id"] = "clx-2026-08-07-production_v1-newer"
        marker["payload"]["content_hash"] = "hash-2"
        marker["payload"]["publication_id"] = "pub-2"
        return marker

    result = reconcile_pre_pool_for_ready_marker(
        _ready_marker(),
        repository=repository,
        pre_pool_service=pre_service,
        ready_marker_provider=_changed_marker,
    )

    assert result["status"] == "aborted"
    assert result["reason"] == "generation_changed"
    assert pre_service.calls == []


def test_reconcile_pre_pool_skips_without_ready_generation():
    repository = FakeRepository()
    pre_service = FakePrePoolService()

    result = reconcile_pre_pool_for_ready_marker(
        None,
        repository=repository,
        pre_pool_service=pre_service,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "no_ready_generation"
    assert pre_service.calls == []


def test_reconcile_pre_pool_marks_batch_not_found_as_failed():
    repository = FakeRepository()
    pre_service = FakePrePoolService()

    result = reconcile_pre_pool_for_ready_marker(
        _ready_marker(),
        repository=repository,
        pre_pool_service=pre_service,
        ready_marker_provider=lambda trade_date: _ready_marker(),
    )

    assert result["status"] == "failed"
    assert result["reason"] == "batch_not_found"
    assert pre_service.calls == []
