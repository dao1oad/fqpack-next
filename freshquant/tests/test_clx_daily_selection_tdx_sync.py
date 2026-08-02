from __future__ import annotations

from copy import deepcopy

import pytest

from freshquant.clx_daily_selection.service import ClxDailySelectionService


def published_batch():
    return {
        "batch_id": "clx-2026-07-31-production_v1-final",
        "trade_date": "2026-07-31",
        "status": "completed",
        "release_status": "final",
        "is_final": True,
        "publication": {"status": "published"},
        "partitions": {
            "stock": {"status": "completed", "partition_id": "partition-stock"},
            "etf": {"status": "completed", "partition_id": "partition-etf"},
        },
    }


class SnapshotRepository:
    def __init__(self, *, batch=None, rows=None):
        self.batch = deepcopy(batch or published_batch())
        self.rows = deepcopy(rows or [])
        self.snapshot_calls = []

    def get_batch(self, batch_id):
        if batch_id != self.batch["batch_id"]:
            return None
        return deepcopy(self.batch)

    def get_snapshots(self, partition_ids):
        self.snapshot_calls.append(deepcopy(partition_ids))
        return deepcopy(self.rows)


def make_service(repository):
    return ClxDailySelectionService(
        repository=repository,
        market_data_provider=object(),
        engine=object(),
    )


def test_sync_selected_results_to_tdx_revalidates_snapshot_and_full_replaces_basket(
    monkeypatch,
):
    rows = [
        {
            "asset_type": "etf",
            "symbol": "160512",
            "distinct_model_count": 4,
        },
        {
            "asset_type": "stock",
            "symbol": "000001",
            "distinct_model_count": 3,
        },
        {
            "asset_type": "stock",
            "symbol": "830799",
            "distinct_model_count": 2,
        },
    ]
    batch = published_batch()
    batch["partitions"]["preview"] = {
        "status": "completed",
        "partition_id": "partition-preview",
    }
    repository = SnapshotRepository(batch=batch, rows=rows)
    writes = []

    def write_group(selected_rows):
        writes.append(deepcopy(selected_rows))
        return {
            "group_name": "clx_18",
            "file_name": "CLX_18.blk",
            "written_count": len(selected_rows),
        }

    monkeypatch.setattr(
        "freshquant.clx_daily_selection.service.write_clx_tdx_group", write_group
    )
    service = make_service(repository)
    batch_id = repository.batch["batch_id"]

    first = service.sync_selected_results_to_tdx(
        batch_id,
        {
            "items": [
                {"asset_type": "stock", "symbol": "830799"},
                {"asset_type": "etf", "symbol": "160512"},
                {"asset_type": "stock", "symbol": "000001"},
                {"asset_type": "stock", "symbol": "000001"},
            ]
        },
    )
    second = service.sync_selected_results_to_tdx(
        batch_id,
        {
            "items": [
                {"asset_type": "stock", "symbol": "830799"},
                {"asset_type": "stock", "symbol": "000001"},
            ]
        },
    )

    assert first == {
        "group_name": "clx_18",
        "file_name": "CLX_18.blk",
        "requested_count": 3,
        "written_count": 3,
        "scope_id": batch_id,
        "trade_date": "2026-07-31",
    }
    assert second["requested_count"] == 2
    assert second["written_count"] == 2
    assert writes == [rows, [rows[1], rows[2]]]
    assert repository.snapshot_calls == [
        ["partition-stock", "partition-etf"],
        ["partition-stock", "partition-etf"],
    ]


@pytest.mark.parametrize(
    "batch",
    [
        {**published_batch(), "status": "failed"},
        {**published_batch(), "is_final": False, "release_status": "partial"},
        {**published_batch(), "publication": {"status": "not_required"}},
        {
            **published_batch(),
            "partitions": {
                **published_batch()["partitions"],
                "etf": {"status": "running"},
            },
        },
    ],
)
def test_sync_selected_results_to_tdx_rejects_incomplete_or_unpublished_batch(batch):
    repository = SnapshotRepository(
        batch=batch, rows=[{"asset_type": "stock", "symbol": "000001"}]
    )

    with pytest.raises(ValueError, match="旧分组已保留"):
        make_service(repository).sync_selected_results_to_tdx(
            batch["batch_id"],
            {"items": [{"asset_type": "stock", "symbol": "000001"}]},
        )

    assert repository.snapshot_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"items": [{"asset_type": "stock", "symbol": "000001"}], "q": "x"},
        {"items": [{"asset_type": "stock", "symbol": "000001", "name": "x"}]},
    ],
)
def test_sync_selected_results_to_tdx_rejects_invalid_items(payload):
    repository = SnapshotRepository(rows=[{"asset_type": "stock", "symbol": "000001"}])

    with pytest.raises(ValueError, match="旧分组已保留"):
        make_service(repository).sync_selected_results_to_tdx(
            repository.batch["batch_id"], payload
        )

    assert repository.snapshot_calls == []


def test_sync_selected_results_to_tdx_rejects_external_symbol_and_asset_conflict():
    repository = SnapshotRepository(
        rows=[{"asset_type": "etf", "symbol": "159577", "distinct_model_count": 1}]
    )
    service = make_service(repository)
    batch_id = repository.batch["batch_id"]

    with pytest.raises(ValueError, match="不属于该正式批次"):
        service.sync_selected_results_to_tdx(
            batch_id,
            {"items": [{"asset_type": "stock", "symbol": "000001"}]},
        )
    with pytest.raises(ValueError, match="asset_type 与正式批次不一致"):
        service.sync_selected_results_to_tdx(
            batch_id,
            {"items": [{"asset_type": "stock", "symbol": "159577"}]},
        )


def test_sync_selected_results_to_tdx_rejects_evaluated_non_hit_before_writer(
    monkeypatch,
):
    repository = SnapshotRepository(
        rows=[
            {
                "asset_type": "stock",
                "symbol": "000001",
                "distinct_model_count": 0,
            }
        ]
    )
    called = False

    def write_group(_rows):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        "freshquant.clx_daily_selection.service.write_clx_tdx_group", write_group
    )

    with pytest.raises(ValueError, match="不是该正式批次的每日选股命中结果"):
        make_service(repository).sync_selected_results_to_tdx(
            repository.batch["batch_id"],
            {"items": [{"asset_type": "stock", "symbol": "000001"}]},
        )

    assert called is False


def test_sync_selected_results_to_tdx_writer_failure_propagates_old_group_message(
    monkeypatch,
):
    repository = SnapshotRepository(
        rows=[{"asset_type": "stock", "symbol": "000001", "distinct_model_count": 1}]
    )

    def fail_write(_rows):
        raise RuntimeError("导入通达信失败，旧分组已保留：replace denied")

    monkeypatch.setattr(
        "freshquant.clx_daily_selection.service.write_clx_tdx_group", fail_write
    )

    with pytest.raises(RuntimeError, match="旧分组已保留"):
        make_service(repository).sync_selected_results_to_tdx(
            repository.batch["batch_id"],
            {"items": [{"asset_type": "stock", "symbol": "000001"}]},
        )
