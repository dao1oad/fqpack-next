from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path


def _import_marker_module(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    sys.modules.pop("fqdagster.defs.postclose_markers", None)
    return importlib.import_module("fqdagster.defs.postclose_markers")


class FakeMarkerCollection:
    def __init__(self):
        self.documents = {}
        self.created_indexes = []

    def create_index(self, fields, **kwargs):
        self.created_indexes.append((fields, kwargs))

    def update_one(self, query, update, upsert=False):
        key = (query.get("pipeline_key"), query.get("trade_date"))
        document = dict(self.documents.get(key) or {})
        document.update(query)
        document.update(dict(update.get("$set") or {}))
        self.documents[key] = document
        return document

    def find_one(self, query):
        key = (query.get("pipeline_key"), query.get("trade_date"))
        document = self.documents.get(key)
        if document is None:
            return None
        return dict(document)

    def delete_many(self, query):
        key = (query.get("pipeline_key"), query.get("trade_date"))
        self.documents.pop(key, None)


def test_upsert_and_get_postclose_marker(monkeypatch):
    module = _import_marker_module(monkeypatch)
    collection = FakeMarkerCollection()

    marker = module.upsert_postclose_marker(
        "stock_postclose_ready",
        "2026-03-19",
        run_id="run-1",
        payload={"rows": 12},
        collection=collection,
        now_provider=lambda: datetime(2026, 3, 19, 16, 10, tzinfo=timezone.utc),
    )

    assert marker == {
        "pipeline_key": "stock_postclose_ready",
        "trade_date": "2026-03-19",
        "status": "success",
        "updated_at": "2026-03-19T16:10:00+00:00",
        "run_id": "run-1",
        "payload": {"rows": 12},
    }
    assert (
        module.get_postclose_marker(
            "stock_postclose_ready",
            "2026-03-19",
            collection=collection,
        )
        == marker
    )
    assert (
        module.has_success_postclose_marker(
            "stock_postclose_ready",
            "2026-03-19",
            collection=collection,
        )
        is True
    )


def test_upsert_postclose_marker_overwrites_same_trade_date(monkeypatch):
    module = _import_marker_module(monkeypatch)
    collection = FakeMarkerCollection()

    module.upsert_postclose_marker(
        "stock_postclose_ready",
        "2026-03-19",
        status="failed",
        payload={"rows": 0},
        collection=collection,
        now_provider=lambda: datetime(2026, 3, 19, 16, 0, tzinfo=timezone.utc),
    )
    marker = module.upsert_postclose_marker(
        "stock_postclose_ready",
        "2026-03-19",
        payload={"rows": 16},
        collection=collection,
        now_provider=lambda: datetime(2026, 3, 19, 16, 15, tzinfo=timezone.utc),
    )

    assert len(collection.documents) == 1
    assert marker["status"] == "success"
    assert marker["payload"] == {"rows": 16}
    assert marker["updated_at"] == "2026-03-19T16:15:00+00:00"


def test_delete_postclose_marker_removes_existing_document(monkeypatch):
    module = _import_marker_module(monkeypatch)
    collection = FakeMarkerCollection()

    module.upsert_postclose_marker(
        "gantt_postclose_ready",
        "2026-03-19",
        collection=collection,
    )

    module.delete_postclose_marker(
        "gantt_postclose_ready",
        "2026-03-19",
        collection=collection,
    )

    assert (
        module.get_postclose_marker(
            "gantt_postclose_ready",
            "2026-03-19",
            collection=collection,
        )
        is None
    )
    assert (
        module.has_success_postclose_marker(
            "gantt_postclose_ready",
            "2026-03-19",
            collection=collection,
        )
        is False
    )


def test_resolve_latest_completed_trade_date_uses_same_day_after_cutoff(monkeypatch):
    module = _import_marker_module(monkeypatch)

    trade_date = module.resolve_latest_completed_trade_date(
        now_provider=lambda: datetime(2026, 3, 19, 16, 10, tzinfo=timezone.utc),
        trade_dates_provider=lambda: {
            "trade_date": [
                datetime(2026, 3, 18, tzinfo=timezone.utc).date(),
                datetime(2026, 3, 19, tzinfo=timezone.utc).date(),
            ]
        },
    )

    assert trade_date == "2026-03-19"
