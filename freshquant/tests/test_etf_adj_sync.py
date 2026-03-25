from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd

from freshquant.data import etf_adj_sync


class FakeCursor:
    def __init__(self, documents):
        self._documents = [dict(item) for item in documents]

    def sort(self, key, direction):
        reverse = int(direction) < 0
        return FakeCursor(
            sorted(self._documents, key=lambda item: item.get(key), reverse=reverse)
        )

    def __iter__(self):
        return iter(self._documents)


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [dict(item) for item in (documents or [])]
        self.created_indexes = []

    def create_index(self, fields, unique=False):
        self.created_indexes.append((fields, unique))

    def find(self, query=None, projection=None):
        query = query or {}
        filtered = []
        for document in self.documents:
            matched = True
            for key, expected in query.items():
                if (
                    isinstance(expected, dict)
                    and "$gte" in expected
                    and "$lte" in expected
                ):
                    value = document.get(key)
                    if (
                        value is None
                        or value < expected["$gte"]
                        or value > expected["$lte"]
                    ):
                        matched = False
                        break
                elif document.get(key) != expected:
                    matched = False
                    break
            if not matched:
                continue

            if projection:
                item = {}
                for key, enabled in projection.items():
                    if enabled and key in document:
                        item[key] = document[key]
                filtered.append(item)
            else:
                filtered.append(dict(document))
        return FakeCursor(filtered)

    def delete_many(self, query):
        keep = []
        for document in self.documents:
            matched = True
            for key, expected in query.items():
                if document.get(key) != expected:
                    matched = False
                    break
            if not matched:
                keep.append(document)
        self.documents = keep

    def insert_many(self, documents, ordered=False):
        self.documents.extend(dict(item) for item in documents)


class FakeDb:
    def __init__(self, *, etf_list=None, etf_xdxr=None, etf_adj=None, index_day=None):
        self.etf_list = FakeCollection(etf_list)
        self.etf_xdxr = FakeCollection(etf_xdxr)
        self.etf_adj = FakeCollection(etf_adj)
        self.index_day = FakeCollection(index_day)

    def __getitem__(self, name):
        return getattr(self, name)

    def drop_collection(self, name):
        setattr(self, name, FakeCollection())


class FakeTdxApi:
    payload_by_code: dict[str, list[dict[str, Any]]] = {}
    instance_count = 0

    def __init__(self):
        type(self).instance_count += 1
        self.instance_no = type(self).instance_count
        self.call_count_by_code: dict[str, int] = {}

    def connect(self, ip, port, time_out=0.7):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_xdxr_info(self, market, code):
        self.call_count_by_code[code] = self.call_count_by_code.get(code, 0) + 1
        payload = self.payload_by_code.get(code, [])
        if callable(payload):
            return payload(
                code=code,
                market=market,
                instance_no=self.instance_no,
                call_no=self.call_count_by_code[code],
            )
        return payload

    def to_df(self, raw):
        if not raw:
            return pd.DataFrame()
        return pd.DataFrame(raw)


def test_sync_etf_xdxr_all_preserves_existing_docs_when_source_returns_empty(
    monkeypatch,
):
    db = FakeDb(
        etf_list=[{"code": "512000", "sse": "sh"}],
        etf_xdxr=[
            {
                "code": "512000",
                "date": "2025-08-04",
                "category": 11,
                "suogu": 2.0,
            }
        ],
    )

    monkeypatch.setattr(etf_adj_sync, "_ensure_indexes", lambda db: None)
    monkeypatch.setattr(
        etf_adj_sync,
        "_pick_hq_host",
        lambda timeout=0.7, **kwargs: etf_adj_sync.TdxHqHost(
            "fake", "127.0.0.1", 7709
        ),
    )
    FakeTdxApi.payload_by_code = {"512000": []}
    monkeypatch.setattr(etf_adj_sync, "_import_pytdx", lambda: (FakeTdxApi, []))

    stats = etf_adj_sync.sync_etf_xdxr_all(db=db)

    assert stats == {
        "total": 1,
        "ok": 0,
        "empty": 0,
        "preserved": 1,
        "failed": 0,
        "retried_empty": 1,
        "recovered_after_retry": 0,
        "retry_failed": 0,
    }
    assert db.etf_xdxr.documents == [
        {
            "code": "512000",
            "date": "2025-08-04",
            "category": 11,
            "suogu": 2.0,
        }
    ]


def test_sync_etf_xdxr_all_replaces_docs_when_source_returns_events(monkeypatch):
    db = FakeDb(
        etf_list=[{"code": "512800", "sse": "sh"}],
        etf_xdxr=[
            {
                "code": "512800",
                "date": "2024-01-01",
                "category": 1,
                "fenhong": 0.1,
            }
        ],
    )

    monkeypatch.setattr(etf_adj_sync, "_ensure_indexes", lambda db: None)
    monkeypatch.setattr(
        etf_adj_sync,
        "_pick_hq_host",
        lambda timeout=0.7, **kwargs: etf_adj_sync.TdxHqHost(
            "fake", "127.0.0.1", 7709
        ),
    )
    FakeTdxApi.payload_by_code = {
        "512800": [
            {
                "year": 2025,
                "month": 7,
                "day": 7,
                "category": 11,
                "name": "扩缩股",
                "suogu": 2.0,
            }
        ]
    }
    monkeypatch.setattr(etf_adj_sync, "_import_pytdx", lambda: (FakeTdxApi, []))

    stats = etf_adj_sync.sync_etf_xdxr_all(db=db)

    assert stats == {
        "total": 1,
        "ok": 1,
        "empty": 0,
        "preserved": 0,
        "failed": 0,
        "retried_empty": 0,
        "recovered_after_retry": 0,
        "retry_failed": 0,
    }
    assert db.etf_xdxr.documents == [
        {
            "code": "512800",
            "date": "2025-07-07",
            "category": 11,
            "name": "扩缩股",
            "suogu": 2.0,
            "category_meaning": "扩缩股",
        }
    ]


def test_sync_etf_xdxr_all_retries_empty_result_before_preserving_docs(monkeypatch):
    db = FakeDb(
        etf_list=[{"code": "512800", "sse": "sh"}],
        etf_xdxr=[
            {
                "code": "512800",
                "date": "2023-12-25",
                "category": 1,
                "fenhong": 0.48,
            }
        ],
    )

    monkeypatch.setattr(etf_adj_sync, "_ensure_indexes", lambda db: None)
    monkeypatch.setattr(
        etf_adj_sync,
        "_pick_hq_host",
        lambda timeout=0.7, **kwargs: etf_adj_sync.TdxHqHost(
            "fake", "127.0.0.1", 7709
        ),
    )
    FakeTdxApi.instance_count = 0
    FakeTdxApi.payload_by_code = {
        "512800": lambda **kwargs: []
        if kwargs["instance_no"] == 1
        else [
            {
                "year": 2025,
                "month": 7,
                "day": 7,
                "category": 11,
                "name": "扩缩股",
                "suogu": 2.0,
            }
        ]
    }
    monkeypatch.setattr(etf_adj_sync, "_import_pytdx", lambda: (FakeTdxApi, []))

    stats = etf_adj_sync.sync_etf_xdxr_all(db=db)

    assert stats == {
        "total": 1,
        "ok": 1,
        "empty": 0,
        "preserved": 0,
        "failed": 0,
        "retried_empty": 1,
        "recovered_after_retry": 1,
        "retry_failed": 0,
    }
    assert db.etf_xdxr.documents == [
        {
            "code": "512800",
            "date": "2025-07-07",
            "category": 11,
            "name": "扩缩股",
            "suogu": 2.0,
            "category_meaning": "扩缩股",
        }
    ]


def test_sync_etf_xdxr_all_reconnects_between_batches(monkeypatch):
    db = FakeDb(
        etf_list=[
            {"code": "512800", "sse": "sh"},
            {"code": "512810", "sse": "sh"},
        ],
    )

    monkeypatch.setattr(etf_adj_sync, "_ensure_indexes", lambda db: None)
    monkeypatch.setattr(
        etf_adj_sync,
        "_pick_hq_host",
        lambda timeout=0.7, **kwargs: etf_adj_sync.TdxHqHost(
            "fake", "127.0.0.1", 7709
        ),
    )
    FakeTdxApi.instance_count = 0
    FakeTdxApi.payload_by_code = {
        "512800": [
            {
                "year": 2025,
                "month": 7,
                "day": 7,
                "category": 11,
                "name": "扩缩股",
                "suogu": 2.0,
            }
        ],
        "512810": [
            {
                "year": 2025,
                "month": 8,
                "day": 1,
                "category": 11,
                "name": "扩缩股",
                "suogu": 1.5,
            }
        ],
    }
    monkeypatch.setattr(etf_adj_sync, "_import_pytdx", lambda: (FakeTdxApi, []))

    stats = etf_adj_sync.sync_etf_xdxr_all(db=db, reconnect_every=1)

    assert stats == {
        "total": 2,
        "ok": 2,
        "empty": 0,
        "preserved": 0,
        "failed": 0,
        "retried_empty": 0,
        "recovered_after_retry": 0,
        "retry_failed": 0,
    }
    assert FakeTdxApi.instance_count == 2
