# -*- coding: utf-8 -*-

import datetime
import time
from types import SimpleNamespace

import pytest

from freshquant.xt_account_sync.persistence import persist_positions


class FakeCollection:
    """Minimal in-memory collection supporting bulk_write / update_many /
    delete_many / find used by persist_positions."""

    def __init__(self, docs=None):
        self.docs = [dict(item) for item in (docs or [])]
        self.operations = []

    def __bool__(self):
        raise NotImplementedError(
            "Collection objects do not implement truth value testing"
        )

    def bulk_write(self, operations):
        self.operations.extend(operations)
        for operation in operations:
            query = dict(operation._filter)
            payload = dict(operation._doc["$set"])
            updated = False
            for index, document in enumerate(self.docs):
                if all(document.get(key) == value for key, value in query.items()):
                    self.docs[index] = dict(document, **payload)
                    updated = True
                    break
            if not updated:
                self.docs.append(payload)

    def update_many(self, query, update):
        matched = 0
        for document in self.docs:
            if all(document.get(key) == value for key, value in query.items()):
                if "$inc" in update:
                    for key, value in update["$inc"].items():
                        document[key] = int(document.get(key) or 0) + value
                if "$set" in update:
                    document.update(update["$set"])
                matched += 1
        return matched

    def update_one(self, query, update):
        for document in self.docs:
            if all(document.get(key) == value for key, value in query.items()):
                if "$inc" in update:
                    for key, value in update["$inc"].items():
                        document[key] = int(document.get(key) or 0) + value
                if "$set" in update:
                    document.update(update["$set"])
                return 1
        return 0

    def delete_many(self, query):
        remaining = []
        for document in self.docs:
            matched = True
            for key, value in query.items():
                if key == "$or":
                    matched = any(
                        all(document.get(k) == v for k, v in branch.items())
                        for branch in value
                    )
                    if not matched:
                        break
                    continue
                if document.get(key) != value:
                    matched = False
                    break
            if not matched:
                remaining.append(document)
        removed = len(self.docs) - len(remaining)
        self.docs = remaining
        return removed

    def find(self, query):
        return [
            dict(document)
            for document in self.docs
            if all(document.get(key) == value for key, value in query.items())
        ]


def _now():
    return int(time.time())


def _make_positions(*codes):
    return [
        {"account_id": "acct-a", "stock_code": code, "volume": 100} for code in codes
    ]


def test_upsert_updates_existing_and_inserts_new_with_count_reset():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600570.SH",
                "volume": 10,
                "sync_missing_count": 3,
                "sync_last_seen_at": 0,
            }
        ]
    )
    invalidation = []

    result = persist_positions(
        [{"account_id": "acct-a", "stock_code": "600570.SH", "volume": 200}],
        account_id="acct-a",
        collection=collection,
        invalidator=lambda: invalidation.append("bumped"),
        now_provider=_now,
    )

    assert result["count"] == 1
    assert invalidation == ["bumped"]
    updated = [d for d in collection.docs if d["stock_code"] == "600570.SH"][0]
    assert updated["volume"] == 200
    assert updated["sync_missing_count"] == 0
    assert updated["sync_last_seen_at"] > 0


def test_first_missing_symbol_increments_count_but_keeps_document():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600570.SH",
                "volume": 10,
                "sync_missing_count": 0,
                "sync_last_seen_at": _now(),
            },
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 0,
                "sync_last_seen_at": _now(),
            },
        ]
    )

    result = persist_positions(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        now_provider=_now,
    )

    assert result["deleted_missing"] == []
    assert collection.docs == [
        {
            "account_id": "acct-a",
            "stock_code": "600570.SH",
            "volume": 100,
            "sync_missing_count": 0,
            "sync_last_seen_at": collection.docs[0]["sync_last_seen_at"],
        },
        {
            "account_id": "acct-a",
            "stock_code": "600271.SH",
            "volume": 20,
            "sync_missing_count": 1,
            "sync_last_seen_at": collection.docs[1]["sync_last_seen_at"],
        },
    ]


def test_continuous_missing_reaches_round_threshold_then_evicts():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 19,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    result = persist_positions(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        missing_threshold=20,
        now_provider=_now,
    )

    assert result["deleted_missing"] == ["600271.SH"]
    assert [d["stock_code"] for d in collection.docs] == ["600570.SH"]


def test_missing_symbol_reappears_resets_count_and_never_evicts():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 5,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    result = persist_positions(
        _make_positions("600570.SH", "600271.SH"),
        account_id="acct-a",
        collection=collection,
        missing_threshold=20,
        now_provider=_now,
    )

    assert result["deleted_missing"] == []
    reappeared = [d for d in collection.docs if d["stock_code"] == "600271.SH"][0]
    assert reappeared["sync_missing_count"] == 0


def test_empty_snapshot_guard_keeps_existing_and_does_not_increment_count():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600570.SH",
                "volume": 10,
                "sync_missing_count": 0,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    result = persist_positions(
        [],
        account_id="acct-a",
        collection=collection,
        now_provider=_now,
    )

    assert result["empty_snapshot_guard"] is True
    assert result["deleted_missing"] == []
    kept = collection.docs[0]
    assert kept["stock_code"] == "600570.SH"
    assert kept["sync_missing_count"] == 0


def test_eviction_writes_audit_log_entry():
    from freshquant.xt_account_sync.persistence import persist_positions as _persist

    class AuditCollection(FakeCollection):
        def __init__(self, docs=None):
            super().__init__(docs)
            self.audits = []

        def insert_one(self, document):
            self.audits.append(dict(document))

    collection = AuditCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 20,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    _persist(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        missing_threshold=20,
        now_provider=_now,
        audit_collection=collection,
    )

    assert len(collection.audits) == 1
    audit = collection.audits[0]
    assert audit["operation"] == "xt_positions_missing_evict"
    assert audit["stock_codes"] == ["600271.SH"]
    assert audit["account_id"] == "acct-a"
    assert audit["snapshot_codes"] == ["600570.SH"]


def test_missing_count_below_threshold_does_not_evict():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 5,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    result = persist_positions(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        missing_threshold=20,
        now_provider=_now,
    )

    assert result["deleted_missing"] == []
    assert sorted(d["stock_code"] for d in collection.docs) == [
        "600271.SH",
        "600570.SH",
    ]


def test_wall_clock_threshold_evicts_stale_symbol_even_when_round_count_low():
    stale_seen = int(time.time()) - 600
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 20,
                "sync_missing_count": 1,
                "sync_last_seen_at": stale_seen,
            }
        ]
    )

    result = persist_positions(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        missing_wall_clock_seconds=300,
        now_provider=_now,
    )

    assert result["deleted_missing"] == ["600271.SH"]


def test_zero_volume_position_is_treated_as_cleared_and_removed_from_effective_view():
    collection = FakeCollection(
        [
            {
                "account_id": "acct-a",
                "stock_code": "600271.SH",
                "volume": 0,
                "sync_missing_count": 0,
                "sync_last_seen_at": _now(),
            }
        ]
    )

    result = persist_positions(
        [{"account_id": "acct-a", "stock_code": "600271.SH", "volume": 0}],
        account_id="acct-a",
        collection=collection,
        now_provider=_now,
    )

    assert result["cleared_zero_volume"] == ["600271.SH"]


def test_invalidator_is_called_on_every_persist():
    collection = FakeCollection()
    invalidation = []

    persist_positions(
        _make_positions("600570.SH"),
        account_id="acct-a",
        collection=collection,
        invalidator=lambda: invalidation.append("bumped"),
        now_provider=_now,
    )

    assert invalidation == ["bumped"]
