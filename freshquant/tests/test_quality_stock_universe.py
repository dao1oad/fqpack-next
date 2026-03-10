# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.data.quality_stock_universe import (
    QUALITY_STOCK_BLOCK_NAMES,
    QUALITY_STOCK_SOURCE_VERSION,
    load_quality_stock_lookup,
    refresh_quality_stock_universe,
)


class FakeBlockCollection:
    def __init__(self, documents):
        self.documents = [dict(item) for item in (documents or [])]

    def find(self, query=None, projection=None):
        query = query or {}
        block_names = set(((query.get("blockname") or {}).get("$in")) or [])
        rows = [
            dict(item)
            for item in self.documents
            if not block_names or item.get("blockname") in block_names
        ]
        return rows


class FakeTargetCollection:
    def __init__(self):
        self.documents = []
        self.deleted_queries = []
        self.created_indexes = []

    def delete_many(self, query):
        self.deleted_queries.append(dict(query))
        self.documents = []

    def insert_many(self, documents, ordered=False):
        self.documents.extend(dict(item) for item in (documents or []))

    def create_index(self, fields, **kwargs):
        self.created_indexes.append((fields, kwargs))

    def find(self, query=None, projection=None):
        return [dict(item) for item in self.documents]


class BoolExplodingTargetCollection(FakeTargetCollection):
    def __bool__(self):
        raise NotImplementedError(
            "Collection objects do not implement truth value testing"
        )


def test_quality_stock_block_names_contains_expected_seed_values():
    assert "沪深300" in QUALITY_STOCK_BLOCK_NAMES
    assert "券商金股" in QUALITY_STOCK_BLOCK_NAMES
    assert "行业龙头" in QUALITY_STOCK_BLOCK_NAMES
    assert len(QUALITY_STOCK_BLOCK_NAMES) == 21


def test_refresh_quality_stock_universe_dedupes_codes_and_preserves_block_order():
    block_collection = FakeBlockCollection(
        [
            {"blockname": "高股息股", "code": "600000"},
            {"blockname": "沪深300", "code": "600000"},
            {"blockname": "沪深300", "code": "000001"},
            {"blockname": "行业龙头", "code": "000001"},
            {"blockname": "无关板块", "code": "000002"},
        ]
    )
    target_collection = FakeTargetCollection()

    result = refresh_quality_stock_universe(
        block_collection=block_collection,
        target_collection=target_collection,
        now_provider=lambda: datetime(2026, 3, 9, tzinfo=timezone.utc),
    )

    assert result == {
        "count": 2,
        "source_version": QUALITY_STOCK_SOURCE_VERSION,
        "updated_at": "2026-03-09T00:00:00+00:00",
    }
    assert target_collection.deleted_queries == [{}]
    assert target_collection.documents == [
        {
            "code6": "000001",
            "block_names": ["沪深300", "行业龙头"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
        {
            "code6": "600000",
            "block_names": ["沪深300", "高股息股"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
    ]


def test_refresh_quality_stock_universe_writes_empty_snapshot_when_no_matches():
    target_collection = FakeTargetCollection()

    result = refresh_quality_stock_universe(
        block_collection=FakeBlockCollection(
            [{"blockname": "无关板块", "code": "000002"}]
        ),
        target_collection=target_collection,
        now_provider=lambda: datetime(2026, 3, 9, tzinfo=timezone.utc),
    )

    assert result["count"] == 0
    assert target_collection.documents == []
    assert target_collection.deleted_queries == [{}]


def test_load_quality_stock_lookup_returns_code_map():
    target_collection = FakeTargetCollection()
    target_collection.documents = [
        {
            "code6": "000001",
            "block_names": ["沪深300"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
        {
            "code6": "600000",
            "block_names": ["高股息股"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
    ]

    assert load_quality_stock_lookup(target_collection=target_collection) == {
        "000001": {
            "code6": "000001",
            "block_names": ["沪深300"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
        "600000": {
            "code6": "600000",
            "block_names": ["高股息股"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        },
    }


def test_load_quality_stock_lookup_accepts_explicit_collection_without_bool_check():
    target_collection = BoolExplodingTargetCollection()
    target_collection.documents = [
        {
            "code6": "000001",
            "block_names": ["沪深300"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        }
    ]

    assert load_quality_stock_lookup(target_collection=target_collection) == {
        "000001": {
            "code6": "000001",
            "block_names": ["沪深300"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        }
    }


def test_refresh_quality_stock_universe_normalizes_infoharbor_aliases():
    block_collection = FakeBlockCollection(
        [{"blockname": "中证央企", "code": "000001"}]
    )
    target_collection = FakeTargetCollection()

    result = refresh_quality_stock_universe(
        block_collection=block_collection,
        target_collection=target_collection,
        now_provider=lambda: datetime(2026, 3, 9, tzinfo=timezone.utc),
    )

    assert result["count"] == 1
    assert target_collection.documents == [
        {
            "code6": "000001",
            "block_names": ["“中证央企”"],
            "source_version": QUALITY_STOCK_SOURCE_VERSION,
            "updated_at": "2026-03-09T00:00:00+00:00",
        }
    ]
