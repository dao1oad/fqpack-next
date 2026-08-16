from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from freshquant.order_management.execution_archive import (
    archive_execution_reports,
    build_account_partition,
    build_execution_key,
)
from freshquant.order_management.position_review_archive import (
    POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION,
    backfill_position_review_history,
    build_position_review_evidence_documents,
)
from freshquant.position_review.repository import PositionReviewRepository
from freshquant.position_review.service import PositionReviewService


class MemoryCursor(list):
    def sort(self, field, direction=1):
        reverse = int(direction or 1) < 0
        super().sort(
            key=lambda item: str(item.get(field) or ""),
            reverse=reverse,
        )
        return self

    def limit(self, count):
        del self[count:]
        return self


class MemoryCollection:
    def __init__(self, documents=()):
        self.documents = [dict(item) for item in documents]

    def find_one(self, query=None, *args, **kwargs):
        for item in self.documents:
            if _matches(item, query or {}):
                return dict(item)
        return None

    def find(self, query=None):
        return MemoryCursor(
            [dict(item) for item in self.documents if _matches(item, query or {})]
        )

    def distinct(self, field):
        return list(
            {item.get(field) for item in self.documents if item.get(field) is not None}
        )

    def insert_many(self, documents, ordered=False):
        batch = [dict(item) for item in documents]
        self.documents.extend(batch)
        return SimpleNamespace(inserted_ids=list(range(len(batch))))

    def delete_many(self, query):
        before = len(self.documents)
        self.documents = [item for item in self.documents if not _matches(item, query)]
        return SimpleNamespace(deleted_count=before - len(self.documents))

    def create_index(self, keys, **kwargs):
        return f"idx_{len(keys)}"

    def bulk_write(self, operations, ordered=False):
        matched = 0
        upserted = 0
        for operation in operations:
            name = operation.__class__.__name__
            if name == "UpdateOne":
                existing = [
                    item for item in self.documents if _matches(item, operation._filter)
                ]
                if existing:
                    matched += 1
                    for item in existing:
                        _apply_update(item, operation._doc)
                else:
                    upserted += 1
                    document = dict(operation._filter)
                    _apply_update(document, operation._doc)
                    self.documents.append(document)
            elif name == "InsertOne":
                upserted += 1
                self.documents.append(dict(operation._doc))
        return SimpleNamespace(
            matched_count=matched,
            modified_count=matched,
            upserted_count=upserted,
        )


def _apply_update(document, update):
    for operation, fields in dict(update or {}).items():
        if operation == "$set":
            document.update(fields)
        elif operation == "$setOnInsert":
            for key, value in (fields or {}).items():
                document.setdefault(key, value)
        elif operation == "$addToSet":
            for key, value in (fields or {}).items():
                each = value.get("$each", []) if isinstance(value, dict) else [value]
                existing = list(document.get(key) or [])
                additions = [item for item in each if item not in existing]
                if additions:
                    document[key] = existing + additions


class MemoryDatabase(dict):
    def __missing__(self, key):
        value = MemoryCollection()
        self[key] = value
        return value


def _matches(document, query):
    for field, expected in dict(query or {}).items():
        actual = document.get(field)
        if isinstance(expected, re.Pattern):
            if not expected.search(str(actual or "")):
                return False
        elif isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _execution(**overrides):
    document = {
        "account_id": "acct-A",
        "traded_id": "trade-reused",
        "order_id": "broker-order-A",
        "stock_code": "002262.SZ",
        "side": "sell",
        "traded_volume": 2300,
        "traded_price": 22.41,
        "traded_time": 1777428847,
    }
    document.update(overrides)
    return document


def _fill(**overrides):
    document = {
        "execution_fill_id": "fill-A",
        "request_id": "request-A",
        "internal_order_id": "order-A",
        "broker_trade_id": "trade-reused",
        "symbol": "002262",
        "side": "sell",
        "quantity": 2300,
        "price": 22.41,
        "trade_time": 1777428847,
    }
    document.update(overrides)
    return document


def test_execution_identity_is_six_fields_and_not_broker_order_id():
    xt_trade = _execution()
    fill = _fill(broker_order_id=None)

    assert build_execution_key(xt_trade) == build_execution_key(fill)
    assert build_execution_key(
        _execution(order_id="a-different-broker-order")
    ) == build_execution_key(xt_trade)
    assert build_execution_key(_execution(traded_volume=4500)) != build_execution_key(
        xt_trade
    )


def test_execution_archive_infers_account_and_keeps_candidate_arrays():
    collection = MemoryCollection()
    result = archive_execution_reports(
        xt_trades=[_execution()],
        execution_fills=[_fill()],
        trade_facts=[
            {
                **_fill(),
                "trade_fact_id": "fact-A",
                "execution_fill_id": None,
            }
        ],
        order_requests=[
            {
                "request_id": "request-A",
                "symbol": "002262",
                "strategy_context": {
                    "threshold": 0.01,
                    "account_id": "acct-A",
                },
            }
        ],
        orders=[
            {
                "internal_order_id": "order-A",
                "request_id": "request-A",
                "symbol": "002262",
            }
        ],
        collection=collection,
    )

    assert result["upserted"] == 1
    archived = collection.documents[0]
    assert archived["account_partition"] == build_account_partition("acct-A")
    assert "acct-A" not in archived["account_partition"]
    assert "account_id" not in archived
    assert all(
        "account_id" not in snapshot
        for field in (
            "xt_trade_snapshots",
            "execution_fill_snapshots",
            "request_snapshots",
            "order_snapshots",
            "trade_fact_snapshots",
        )
        for snapshot in archived[field]
    )
    assert "acct-A" not in repr(archived)
    assert archived["account_resolution"] in {
        "source",
        "matched_xt_execution",
    }
    assert len(archived["xt_trade_snapshots"]) == 1
    assert len(archived["execution_fill_snapshots"]) == 1
    assert [item["request_id"] for item in archived["request_snapshots"]] == [
        "request-A"
    ]
    assert [item["internal_order_id"] for item in archived["order_snapshots"]] == [
        "order-A"
    ]
    assert [item["trade_fact_id"] for item in archived["trade_fact_snapshots"]] == [
        "fact-A"
    ]


def test_two_accounts_do_not_turn_one_unknown_fill_into_third_execution():
    collection = MemoryCollection()
    result = archive_execution_reports(
        xt_trades=[
            _execution(account_id="acct-A"),
            _execution(account_id="acct-B"),
        ],
        execution_fills=[_fill()],
        collection=collection,
    )

    assert result["upserted"] == 2
    assert result["ambiguous_evidence"] == 1
    assert {item["account_partition"] for item in collection.documents} == {
        build_account_partition("acct-A"),
        build_account_partition("acct-B"),
    }
    assert {item["execution_key"] for item in collection.documents} == {
        build_execution_key(_execution())
    }
    assert all(
        (item.get("execution_fill_snapshots") or []) == []
        for item in collection.documents
    )


def test_opposite_side_om_row_is_conflict_evidence_not_canonical_execution():
    execution_collection = MemoryCollection()
    result = archive_execution_reports(
        xt_trades=[_execution(side="sell")],
        execution_fills=[_fill(side="buy")],
        collection=execution_collection,
    )

    assert result["discovered"] == 1
    assert result["conflicting_evidence"] == 1
    assert len(execution_collection.documents) == 1
    assert execution_collection.documents[0]["side"] == "sell"
    assert (
        execution_collection.documents[0].get("execution_fill_snapshots") or []
    ) == []

    second_phase = archive_execution_reports(
        execution_fills=[_fill(side="buy")],
        collection=execution_collection,
    )
    assert second_phase["discovered"] == 0
    assert second_phase["conflicting_evidence"] == 1
    assert len(execution_collection.documents) == 1

    evidence = build_position_review_evidence_documents(
        {
            "xt_trades": [_execution(side="sell")],
            "om_execution_fills": [_fill(side="buy")],
        }
    )
    conflicting_fill = next(
        item for item in evidence if item["evidence_type"] == "execution_fill"
    )
    assert conflicting_fill["canonical_conflict"] == "side_mismatch_with_xt"
    assert conflicting_fill["account_resolution"] == "matched_execution_side_conflict"


def test_evidence_archive_covers_replay_context_and_derives_allocation_symbol():
    sources = {
        "xt_trades": [_execution()],
        "om_order_requests": [{"request_id": "request-A", "symbol": "002262"}],
        "om_orders": [
            {
                "internal_order_id": "order-A",
                "request_id": "request-A",
                "symbol": "002262",
            }
        ],
        "om_execution_fills": [_fill()],
        "om_trade_facts": [
            {
                **_fill(),
                "trade_fact_id": "fact-A",
                "execution_fill_id": None,
            }
        ],
        "om_position_entries": [{"entry_id": "entry-A", "symbol": "002262"}],
        "om_entry_slices": [
            {
                "entry_slice_id": "slice-A",
                "entry_id": "entry-A",
                "symbol": "002262",
            }
        ],
        "om_exit_allocations": [
            {
                "allocation_id": "allocation-A",
                "entry_id": "entry-A",
                "entry_slice_id": "slice-A",
                "exit_trade_fact_id": "fact-A",
            }
        ],
    }

    documents = build_position_review_evidence_documents(sources)

    assert {item["evidence_type"] for item in documents} == {
        "xt_trade",
        "order_request",
        "order",
        "execution_fill",
        "trade_fact",
        "position_entry",
        "entry_slice",
        "exit_allocation",
    }
    allocation = next(
        item for item in documents if item["evidence_type"] == "exit_allocation"
    )
    assert allocation["symbol"] == "002262"
    fill = next(item for item in documents if item["evidence_type"] == "execution_fill")
    assert fill["account_partition"] == build_account_partition("acct-A")
    assert fill["account_resolution"] == "matched_execution"
    assert all("account_id" not in item for item in documents)
    assert all("account_id" not in item["payload"] for item in documents)


def test_backfill_writes_archive_but_repository_reads_current_stores_only():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection([_execution()]),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {
            "om_order_requests": MemoryCollection(
                [{"request_id": "request-A", "symbol": "002262"}]
            ),
            "om_orders": MemoryCollection(
                [
                    {
                        "internal_order_id": "order-A",
                        "request_id": "request-A",
                        "symbol": "002262",
                    }
                ]
            ),
            "om_execution_fills": MemoryCollection([_fill()]),
            "om_trade_facts": MemoryCollection(
                [
                    {
                        **_fill(),
                        "trade_fact_id": "fact-A",
                        "execution_fill_id": None,
                    }
                ]
            ),
            "om_position_entries": MemoryCollection(
                [{"entry_id": "entry-A", "symbol": "002262"}]
            ),
            "om_entry_slices": MemoryCollection(
                [
                    {
                        "entry_slice_id": "slice-A",
                        "entry_id": "entry-A",
                        "symbol": "002262",
                    }
                ]
            ),
            "om_exit_allocations": MemoryCollection(
                [
                    {
                        "allocation_id": "allocation-A",
                        "entry_id": "entry-A",
                        "entry_slice_id": "slice-A",
                        "exit_trade_fact_id": "fact-A",
                    }
                ]
            ),
        }
    )
    position = MemoryDatabase({"pm_strategy_decisions": MemoryCollection()})

    first = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    second = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert first["executions"]["upserted"] == 1
    assert second["executions"]["upserted"] == 0
    assert second["evidence"]["upserted"] == 0

    # 归档写入侧仍然工作。
    assert len(order[POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION].documents) == 8

    # purge 后持仓复盘只读当前库：不再从归档恢复订单/成交/账本。
    business["xt_trades"].delete_many({})
    for collection_name in (
        "om_order_requests",
        "om_orders",
        "om_execution_fills",
        "om_trade_facts",
        "om_position_entries",
        "om_entry_slices",
        "om_exit_allocations",
    ):
        order[collection_name].delete_many({})

    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=position,
    )
    assert repository.list_symbols() == []
    assert repository.list_xt_trades("002262") == []
    assert repository.list_order_requests("002262") == []
    assert repository.list_orders("002262") == []
    assert repository.list_position_entries("002262") == []
    assert repository.list_entry_slices("002262") == []
    assert (
        repository.list_exit_allocations(
            entry_ids=["entry-A"],
            trade_fact_ids=["fact-A"],
        )
        == []
    )

    # 重建后当前库写入重建订单，持仓复盘应直接读取当前库。
    order["om_order_requests"].documents = [
        {
            "request_id": "req_rebuilt_entry-A",
            "action": "buy",
            "symbol": "002262",
            "price": 10.27,
            "quantity": 6000,
            "source": "order_ledger_rebuild",
            "rebuilt_open": True,
        }
    ]
    order["om_orders"].documents = [
        {
            "internal_order_id": "ord_rebuilt_entry-A",
            "request_id": "req_rebuilt_entry-A",
            "broker_order_id": None,
            "symbol": "002262",
            "side": "buy",
            "state": "FILLED",
            "source": "order_ledger_rebuild",
            "rebuilt_open": True,
        }
    ]
    assert [
        item["request_id"] for item in repository.list_order_requests("002262")
    ] == ["req_rebuilt_entry-A"]
    assert [item["internal_order_id"] for item in repository.list_orders("002262")] == [
        "ord_rebuilt_entry-A"
    ]


def test_repository_reads_om_fills_only_and_ignores_xt_trades():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {
            "om_order_requests": MemoryCollection(
                [{"request_id": "request-A", "symbol": "002262"}]
            ),
            "om_orders": MemoryCollection(
                [{"internal_order_id": "order-A", "symbol": "002262"}]
            ),
            "om_execution_fills": MemoryCollection([_fill(account_id="acct-A")]),
        }
    )
    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=MemoryDatabase(),
    )

    assert repository.list_symbols() == ["002262"]
    executions = repository.list_xt_trades("002262")
    assert len(executions) == 1
    assert executions[0]["execution_source"] == "om_execution_fills_current"
    assert executions[0]["account_partition"] == build_account_partition("acct-A")

    # xt_trades 是重建前券商历史，持仓复盘读模型不读取：不会改变成交结果。
    business["xt_trades"].documents = [_execution()]
    executions = repository.list_xt_trades("002262")
    assert len(executions) == 1
    assert executions[0]["execution_source"] == "om_execution_fills_current"


def test_repository_exposes_om_fill_side_conflict_against_broker_truth():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection([_execution(side="sell")]),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {"om_execution_fills": MemoryCollection([_fill(side="buy")])}
    )
    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=MemoryDatabase(),
    )

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 1
    # canonical 成交只来自当前 OM 账本（om_execution_fills），xt_trades 不参与。
    assert canonical[0]["side"] == "buy"
    assert len(fills) == 1
    assert fills[0]["canonical_conflict"] == "side_mismatch_with_xt"

    second_backfill = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert second_backfill["executions"]["conflicting_evidence"] == 1

    # purge 后不再从归档恢复：当前库为空则成交与冲突标注均为空。
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert canonical == []
    assert fills == []


def _credit_snapshot(minute_offset):
    return {
        "queried_at": datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(minutes=minute_offset),
        "seq": minute_offset,
    }


def _credit_repository(snapshot_count):
    position = MemoryDatabase(
        {
            "pm_credit_asset_snapshots": MemoryCollection(
                [_credit_snapshot(offset) for offset in range(snapshot_count)]
            )
        }
    )
    return PositionReviewRepository(
        business_database=MemoryDatabase(),
        order_database=MemoryDatabase(),
        position_database=position,
    )


def test_list_credit_asset_snapshots_returns_latest_window_ascending():
    repository = _credit_repository(snapshot_count=300)

    snapshots = repository.list_credit_asset_snapshots(limit=100)

    # 集合超过 limit：只取最新 100 条，且返回顺序按 queried_at 升序。
    assert [item["seq"] for item in snapshots] == list(range(200, 300))
    queried = [item["queried_at"] for item in snapshots]
    assert queried == sorted(queried)


def test_list_credit_asset_snapshots_within_limit_returns_all_ascending():
    repository = _credit_repository(snapshot_count=50)

    snapshots = repository.list_credit_asset_snapshots(limit=100)

    # 集合不超过 limit：全量返回且升序，现状语义不变。
    assert [item["seq"] for item in snapshots] == list(range(50))
    queried = [item["queried_at"] for item in snapshots]
    assert queried == sorted(queried)


def test_list_credit_asset_snapshots_default_limit_matches_production_caller():
    signature = inspect.signature(PositionReviewRepository.list_credit_asset_snapshots)

    assert signature.parameters["limit"].default == 200_000


class AggregateCollection:
    """只实现 aggregate 的最小集合桩（验证服务器端聚合管道接线）。"""

    def __init__(self, documents):
        self.documents = documents
        self.last_pipeline = None
        self.last_allow_disk_use = None

    def aggregate(self, pipeline, allowDiskUse=False):
        self.last_pipeline = pipeline
        self.last_allow_disk_use = allowDiskUse
        return iter(dict(item) for item in self.documents)


def test_list_credit_asset_daily_buckets_uses_server_side_pipeline():
    collection = AggregateCollection(
        [
            {
                "bucket_time": datetime(2026, 8, 12, 1, 35, tzinfo=timezone.utc),
                "queried_at": "2026-08-12T09:35:00+00:00",
                "total_asset": 100.0,
                "market_value": 50.0,
                "total_debt": 10.0,
                "available_amount": 1.0,
            }
        ]
    )
    repository = PositionReviewRepository(
        business_database=MemoryDatabase(),
        order_database=MemoryDatabase(),
        position_database=MemoryDatabase({"pm_credit_asset_snapshots": collection}),
    )

    buckets = repository.list_credit_asset_daily_buckets(
        start_after="2026-08-01T00:00:00+00:00"
    )

    assert len(buckets) == 1
    assert buckets[0]["queried_at"] == "2026-08-12T09:35:00+00:00"
    assert buckets[0]["bucket_time"] == collection.documents[0]["bucket_time"]
    assert collection.last_allow_disk_use is True
    pipeline = collection.last_pipeline
    assert pipeline[0] == {
        "$match": {"queried_at": {"$gte": "2026-08-01T00:00:00+00:00"}}
    }
    group_stage = pipeline[2]
    assert "$dateTrunc" in str(group_stage)
    assert group_stage["$group"]["_id"]["$dateTrunc"]["unit"] == "day"
    assert group_stage["$group"]["queried_at"] == {"$last": "$queried_at"}
    # 畸形 queried_at 显式失败为 null 并过滤，不整管道报错。
    assert (
        group_stage["$group"]["_id"]["$dateTrunc"]["date"]["$dateFromString"]["onError"]
        is None
    )
    assert {"$match": {"_id": {"$ne": None}}} in pipeline
    assert pipeline[-1]["$project"]["_id"] == 0


def test_list_trade_dates_reads_calendar_cache():
    from datetime import date as _date

    today = _date.today().isoformat()
    repository = PositionReviewRepository(
        business_database=MemoryDatabase(
            {
                "trade_calendar_cache": MemoryCollection(
                    [
                        {
                            "market": "cn_a",
                            "source": "sina",
                            "trade_dates": [
                                "2026-04-07",
                                "2026-05-01",
                                today,
                            ],
                        }
                    ]
                )
            }
        ),
        order_database=MemoryDatabase(),
        position_database=MemoryDatabase(),
    )

    dates = repository.list_trade_dates()

    assert dates == {"2026-04-07", "2026-05-01", today}


def test_list_trade_dates_rejects_stale_cache():
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    stale_latest = (_date.today() - _timedelta(days=30)).isoformat()
    repository = PositionReviewRepository(
        business_database=MemoryDatabase(
            {
                "trade_calendar_cache": MemoryCollection(
                    [
                        {
                            "market": "cn_a",
                            "source": "sina",
                            "trade_dates": ["2026-04-07", stale_latest],
                        }
                    ]
                )
            }
        ),
        order_database=MemoryDatabase(),
        position_database=MemoryDatabase(),
    )

    assert repository.list_trade_dates() is None


def test_xt_trades_do_not_override_om_ledger_fills():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {
            "om_execution_fills": MemoryCollection(
                [_fill(account_id="acct-A", side="buy")]
            )
        }
    )
    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=MemoryDatabase(),
    )

    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert [item["side"] for item in repository.list_xt_trades("002262")] == ["buy"]

    # xt_trades 不再是成交来源：即使存在反向历史成交也不改变 canonical。
    business["xt_trades"].documents = [_execution(account_id="acct-A", side="sell")]
    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 1
    assert canonical[0]["side"] == "buy"
    assert fills[0]["canonical_conflict"] == "side_mismatch_with_xt"
    detail = PositionReviewService(
        repository=repository,
        runtime_repository=SimpleNamespace(
            list_guardian_events=lambda symbol: {
                "available": True,
                "error": None,
                "items": [],
            }
        ),
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")
    assert len(detail["executions"]) == 1
    assert detail["summary"]["buy_quantity"] == 2300
    assert detail["summary"]["sell_quantity"] == 0

    late_xt_backfill = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert late_xt_backfill["executions"]["conflicting_evidence"] == 1

    # purge 后只读当前库：不保留归档侧冲突证据。
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert canonical == []
    assert fills == []
