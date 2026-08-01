from __future__ import annotations

import importlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


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
        existing = self.documents.get(key)
        if existing is not None and not self._matches(existing, query):
            return SimpleNamespace(matched_count=0, upserted_id=None)
        if existing is None and not upsert:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        document = dict(existing or {})
        document.update(
            {
                "pipeline_key": query.get("pipeline_key"),
                "trade_date": query.get("trade_date"),
            }
        )
        document.update(dict(update.get("$set") or {}))
        self.documents[key] = document
        return SimpleNamespace(
            matched_count=1 if existing is not None else 0,
            upserted_id=None if existing is not None else key,
        )

    @staticmethod
    def _matches(document, query):
        for field, expected in query.items():
            if field in {"pipeline_key", "trade_date"}:
                if document.get(field) != expected:
                    return False
            elif isinstance(expected, dict) and "$exists" in expected:
                if (field in document) is not bool(expected["$exists"]):
                    return False
            elif document.get(field) != expected:
                return False
        return True

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


def test_generation_publication_rejects_late_old_writer_and_retries_idempotently(
    monkeypatch,
):
    module = _import_marker_module(monkeypatch)
    collection = FakeMarkerCollection()

    newer = module.upsert_postclose_marker(
        "clx_daily_selection_ready",
        "2026-03-19",
        payload={"batch_id": "batch-new"},
        generation_id="batch-new",
        generation_order="2026-03-19T08:20:00Z|batch-new",
        publication_id="publication-new",
        collection=collection,
        now_provider=lambda: datetime(2026, 3, 19, 16, 20, tzinfo=timezone.utc),
    )
    retry = module.upsert_postclose_marker(
        "clx_daily_selection_ready",
        "2026-03-19",
        payload={"batch_id": "batch-new", "retry": True},
        generation_id="batch-new",
        generation_order="2026-03-19T08:20:00Z|batch-new",
        publication_id="publication-new",
        collection=collection,
        now_provider=lambda: datetime(2026, 3, 19, 16, 21, tzinfo=timezone.utc),
    )
    with pytest.raises(
        module.StalePostclosePublicationError, match="stale-publication"
    ) as caught:
        module.upsert_postclose_marker(
            "clx_daily_selection_ready",
            "2026-03-19",
            payload={"batch_id": "batch-old"},
            generation_id="batch-old",
            generation_order="2026-03-19T08:00:00Z|batch-old",
            publication_id="publication-old",
            collection=collection,
            now_provider=lambda: datetime(2026, 3, 19, 16, 22, tzinfo=timezone.utc),
        )

    assert retry == newer
    assert caught.value.code == "stale_publication"
    assert caught.value.current_publication_id == "publication-new"
    assert collection.documents[("clx_daily_selection_ready", "2026-03-19")] == newer


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
    shanghai = timezone(timedelta(hours=8))

    trade_date = module.resolve_latest_completed_trade_date(
        now_provider=lambda: datetime(2026, 3, 19, 16, 10, tzinfo=shanghai),
        trade_dates_provider=lambda: {
            "trade_date": [
                datetime(2026, 3, 18, tzinfo=timezone.utc).date(),
                datetime(2026, 3, 19, tzinfo=timezone.utc).date(),
            ]
        },
    )

    assert trade_date == "2026-03-19"


def test_resolve_recent_completed_trade_dates_uses_shanghai_cutoff_and_limit(
    monkeypatch,
):
    module = _import_marker_module(monkeypatch)
    shanghai = timezone(timedelta(hours=8))
    trade_dates = [date(2026, 3, day) for day in (17, 20, 13, 19, 16, 18)]

    before_cutoff = module.resolve_recent_completed_trade_dates(
        limit=5,
        now_provider=lambda: datetime(2026, 3, 20, 15, 4, tzinfo=shanghai),
        trade_dates_provider=lambda: {"trade_date": trade_dates},
    )
    at_cutoff = module.resolve_recent_completed_trade_dates(
        limit=5,
        now_provider=lambda: datetime(2026, 3, 20, 15, 5, tzinfo=shanghai),
        trade_dates_provider=lambda: {"trade_date": trade_dates},
    )

    assert before_cutoff == [
        "2026-03-19",
        "2026-03-18",
        "2026-03-17",
        "2026-03-16",
        "2026-03-13",
    ]
    assert at_cutoff == [
        "2026-03-20",
        "2026-03-19",
        "2026-03-18",
        "2026-03-17",
        "2026-03-16",
    ]


def test_resolve_recent_completed_trade_dates_uses_friday_on_weekend(monkeypatch):
    module = _import_marker_module(monkeypatch)
    shanghai = timezone(timedelta(hours=8))

    trade_dates = module.resolve_recent_completed_trade_dates(
        limit=3,
        now_provider=lambda: datetime(2026, 3, 22, 12, 0, tzinfo=shanghai),
        trade_dates_provider=lambda: {
            "trade_date": [
                date(2026, 3, 18),
                date(2026, 3, 19),
                date(2026, 3, 20),
                date(2026, 3, 23),
            ]
        },
    )

    assert trade_dates == ["2026-03-20", "2026-03-19", "2026-03-18"]
