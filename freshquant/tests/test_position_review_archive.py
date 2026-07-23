from __future__ import annotations

import re
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


class MemoryCollection:
    def __init__(self, documents=()):
        self.documents = [dict(item) for item in documents]

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
    assert all(item["execution_fill_snapshots"] == [] for item in collection.documents)


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
    assert execution_collection.documents[0]["execution_fill_snapshots"] == []

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


def test_backfill_survives_live_xt_and_order_ledger_purge():
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
    assert repository.list_symbols() == ["002262"]
    assert len(repository.list_xt_trades("002262")) == 1
    assert [
        item["request_id"] for item in repository.list_order_requests("002262")
    ] == ["request-A"]
    assert [
        item["entry_id"] for item in repository.list_position_entries("002262")
    ] == ["entry-A"]
    assert [
        item["entry_slice_id"] for item in repository.list_entry_slices("002262")
    ] == ["slice-A"]
    assert [
        item["allocation_id"]
        for item in repository.list_exit_allocations(
            entry_ids=["entry-A"],
            trade_fact_ids=["fact-A"],
        )
    ] == ["allocation-A"]
    assert len(order[POSITION_REVIEW_EVIDENCE_ARCHIVE_COLLECTION].documents) == 8


def test_repository_includes_current_om_only_execution_without_double_counting():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {"om_execution_fills": MemoryCollection([_fill(account_id="acct-A")])}
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

    business["xt_trades"].documents = [_execution()]
    executions = repository.list_xt_trades("002262")
    assert len(executions) == 1
    assert executions[0]["execution_source"] == "xt_trades_current"


def test_repository_exposes_current_side_conflict_without_double_counting():
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
    assert canonical[0]["side"] == "sell"
    assert len(fills) == 1
    assert fills[0]["canonical_conflict"] == "side_mismatch_with_xt"

    second_backfill = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert second_backfill["executions"]["conflicting_evidence"] == 1
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 1
    assert len(fills) == 1
    assert fills[0]["canonical_conflict"] == "side_mismatch_with_xt"
    assert fills[0]["archive_account_resolution"] == "matched_execution_side_conflict"


def test_late_xt_truth_replaces_same_account_om_archive_and_survives_purge():
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

    business["xt_trades"].documents = [_execution(account_id="acct-A", side="sell")]
    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 1
    assert canonical[0]["side"] == "sell"
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
    assert detail["summary"]["buy_quantity"] == 0
    assert detail["summary"]["sell_quantity"] == 2300
    assert (
        len(
            [
                item
                for item in detail["data_quality"]["warnings"]
                if item["code"] == "execution_side_conflict"
            ]
        )
        == 1
    )

    late_xt_backfill = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert late_xt_backfill["executions"]["conflicting_evidence"] == 1
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 1
    assert canonical[0]["side"] == "sell"
    assert canonical[0]["account_partition"] == build_account_partition("acct-A")
    assert fills[0]["canonical_conflict"] == "side_mismatch_with_xt"


def test_late_xt_truth_does_not_suppress_om_archive_in_another_account():
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
    business["xt_trades"].documents = [_execution(account_id="acct-B", side="sell")]

    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert {(item["account_partition"], item["side"]) for item in canonical} == {
        (build_account_partition("acct-A"), "buy"),
        (build_account_partition("acct-B"), "sell"),
    }
    assert "canonical_conflict" not in fills[0]

    cross_account_backfill = backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert cross_account_backfill["executions"]["conflicting_evidence"] == 0
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})
    assert {
        (item["account_partition"], item["side"])
        for item in repository.list_xt_trades("002262")
    } == {
        (build_account_partition("acct-A"), "buy"),
        (build_account_partition("acct-B"), "sell"),
    }


def test_late_xt_truth_suppresses_unknown_om_archive_without_third_execution():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(),
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

    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    business["xt_trades"].documents = [_execution(account_id="acct-A", side="sell")]
    assert len(repository.list_xt_trades("002262")) == 1
    assert repository.list_xt_trades("002262")[0]["side"] == "sell"

    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    business["xt_trades"].delete_many({})
    order["om_execution_fills"].delete_many({})
    canonical = repository.list_xt_trades("002262")
    assert len(canonical) == 1
    assert canonical[0]["side"] == "sell"
    assert (
        repository.list_execution_fills("002262")[0]["canonical_conflict"]
        == "side_mismatch_with_xt"
    )


def test_current_xt_revision_replaces_older_xt_archive_after_current_is_cleared():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(
                [_execution(account_id="acct-A", side="buy")]
            ),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase()
    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=MemoryDatabase(),
    )

    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    business["xt_trades"].documents = [_execution(account_id="acct-A", side="sell")]
    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    assert [item["side"] for item in repository.list_xt_trades("002262")] == ["sell"]

    business["xt_trades"].delete_many({})
    canonical = repository.list_xt_trades("002262")
    assert len(canonical) == 1
    assert canonical[0]["side"] == "sell"
    assert len(canonical[0]["superseded_xt_revisions"]) == 1
    assert canonical[0]["superseded_xt_revisions"][0]["side"] == "buy"
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
    assert detail["executions"][0]["superseded_xt_revisions"][0]["side"] == "buy"
    assert any(
        item["code"] == "superseded_xt_revision"
        for item in detail["data_quality"]["warnings"]
    )
    assert (
        len(
            [
                item
                for item in order["om_execution_history_archive"].documents
                if "xt_trades" in item["sources"]
            ]
        )
        == 2
    )


def test_archive_preserves_multiple_xt_order_candidates_as_ambiguous_association():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(
                [
                    _execution(account_id="acct-A", order_id="broker-A"),
                    _execution(account_id="acct-A", order_id="broker-B"),
                ]
            ),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {
            "om_order_requests": MemoryCollection(
                [
                    {
                        "request_id": "request-A",
                        "symbol": "002262",
                        "action": "sell",
                        "source": "strategy",
                        "price": 22.41,
                        "quantity": 2300,
                        "created_at": "2026-04-29T10:14:04+08:00",
                    },
                    {
                        "request_id": "request-B",
                        "symbol": "002262",
                        "action": "sell",
                        "source": "strategy",
                        "price": 22.41,
                        "quantity": 2300,
                        "created_at": "2026-04-29T10:14:04+08:00",
                    },
                ]
            ),
            "om_orders": MemoryCollection(
                [
                    {
                        "internal_order_id": "order-A",
                        "request_id": "request-A",
                        "broker_order_id": "broker-A",
                        "symbol": "002262",
                        "side": "sell",
                        "submitted_at": "2026-04-29T10:14:05+08:00",
                    },
                    {
                        "internal_order_id": "order-B",
                        "request_id": "request-B",
                        "broker_order_id": "broker-B",
                        "symbol": "002262",
                        "side": "sell",
                        "submitted_at": "2026-04-29T10:14:05+08:00",
                    },
                ]
            ),
        }
    )
    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    business["xt_trades"].delete_many({})
    for name in ("om_order_requests", "om_orders"):
        order[name].delete_many({})

    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=MemoryDatabase({"pm_strategy_decisions": MemoryCollection()}),
    )
    canonical = repository.list_xt_trades("002262")
    assert len(canonical) == 1
    assert canonical[0]["broker_order_id_candidates"] == [
        "broker-A",
        "broker-B",
    ]
    assert canonical[0]["broker_order_id_candidate_count"] == 2
    assert canonical[0]["xt_snapshot_candidate_count"] == 2
    assert canonical[0]["order_id"] is None

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
    assert detail["executions"][0]["association_method"] == "ambiguous_order_candidates"
    assert detail["executions"][0]["request_id"] is None
    assert {
        item["request_id"]: item["actual"]["filled_quantity"]
        for item in detail["reviews"]
    } == {
        "request-A": 0,
        "request-B": 0,
    }
    assert any(
        item["code"] == "ambiguous_xt_order_candidates"
        for item in detail["data_quality"]["warnings"]
    )


def test_pure_archive_multi_account_ambiguous_fill_is_not_double_counted():
    business = MemoryDatabase(
        {
            "xt_trades": MemoryCollection(
                [
                    _execution(account_id="acct-A"),
                    _execution(account_id="acct-B"),
                ]
            ),
            "xt_positions": MemoryCollection(),
            "stock_signals": MemoryCollection(),
        }
    )
    order = MemoryDatabase(
        {
            "om_order_requests": MemoryCollection(
                [
                    {
                        "request_id": "request-A",
                        "symbol": "002262",
                        "action": "sell",
                        "source": "strategy",
                        "price": 22.41,
                        "quantity": 2300,
                        "created_at": "2026-04-29T10:14:04+08:00",
                    }
                ]
            ),
            "om_orders": MemoryCollection(
                [
                    {
                        "internal_order_id": "order-A",
                        "request_id": "request-A",
                        "broker_order_id": "broker-order-A",
                        "symbol": "002262",
                        "side": "sell",
                        "submitted_at": "2026-04-29T10:14:05+08:00",
                    }
                ]
            ),
            "om_execution_fills": MemoryCollection([_fill()]),
        }
    )
    position = MemoryDatabase({"pm_strategy_decisions": MemoryCollection()})

    backfill_position_review_history(
        business_database=business,
        order_database=order,
    )
    business["xt_trades"].delete_many({})
    for collection_name in (
        "om_order_requests",
        "om_orders",
        "om_execution_fills",
    ):
        order[collection_name].delete_many({})

    repository = PositionReviewRepository(
        business_database=business,
        order_database=order,
        position_database=position,
    )
    canonical = repository.list_xt_trades("002262")
    fills = repository.list_execution_fills("002262")
    assert len(canonical) == 2
    assert len(fills) == 1
    assert fills[0]["archive_account_resolution"] == "ambiguous_execution_candidate"

    runtime_repository = SimpleNamespace(
        list_guardian_events=lambda symbol: {
            "available": True,
            "error": None,
            "items": [],
        }
    )
    detail = PositionReviewService(
        repository=repository,
        runtime_repository=runtime_repository,
        name_resolver=lambda symbol: "恩华药业",
    ).get_symbol_detail("002262")

    assert len(detail["executions"]) == 2
    assert all(item["request_id"] is None for item in detail["executions"])
    assert detail["reviews"][0]["actual"]["filled_quantity"] == 0
    assert any(
        item["code"] == "ambiguous_execution_account_evidence"
        for item in detail["data_quality"]["warnings"]
    )
