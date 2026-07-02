from datetime import datetime, timezone

import pandas as pd
import pytest
from requests.exceptions import SSLError  # type: ignore[import-untyped]

from freshquant.data.trade_calendar_cache import (
    TradeCalendarUnavailable,
    fetch_trade_dates_with_persistent_cache,
    refresh_trade_calendar_cache,
)
from freshquant.trading import dt


class FakeTradeCalendarCollection:
    def __init__(self, docs=None):
        self.docs = {}
        self.created_indexes = []
        for doc in docs or []:
            self.docs[(doc["market"], doc["source"])] = dict(doc)

    def create_index(self, fields, **kwargs):
        self.created_indexes.append((fields, kwargs))

    def find_one(self, query):
        doc = self.docs.get((query.get("market"), query.get("source")))
        if doc is None:
            return None
        return dict(doc)

    def update_one(self, query, update, upsert=False):
        key = (query.get("market"), query.get("source"))
        doc = self.docs.get(key)
        is_insert = doc is None
        if doc is None:
            if not upsert:
                return None
            doc = dict(query)
        if is_insert:
            doc.update(dict(update.get("$setOnInsert") or {}))
        doc.update(dict(update.get("$set") or {}))
        for field, increment in dict(update.get("$inc") or {}).items():
            doc[field] = int(doc.get(field) or 0) + int(increment)
        self.docs[(doc["market"], doc["source"])] = doc
        return doc


def _cache_doc(*, max_trade_date="2026-12-31"):
    return {
        "_id": "cn_a:sina",
        "market": "cn_a",
        "source": "sina",
        "schema_version": 1,
        "trade_dates": ["2026-03-18", "2026-03-19", max_trade_date],
        "min_trade_date": "2026-03-18",
        "max_trade_date": max_trade_date,
        "date_count": 3,
        "checksum": "sha256:old",
        "last_success_at": datetime(2026, 3, 19, tzinfo=timezone.utc),
        "last_error_at": None,
        "last_error_type": "",
        "last_error_message": "",
        "fallback_hits": 0,
    }


def _now():
    return datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)


def test_fetch_trade_dates_uses_valid_mongo_cache_without_remote_call():
    collection = FakeTradeCalendarCollection([_cache_doc()])

    def unexpected_fetch():
        raise AssertionError("valid trade calendar cache should be used first")

    result = fetch_trade_dates_with_persistent_cache(
        unexpected_fetch,
        collection=collection,
        now_provider=_now,
    )

    assert list(result["trade_date"].astype(str)) == [
        "2026-03-18",
        "2026-03-19",
        "2026-12-31",
    ]


def test_refresh_trade_calendar_cache_persists_normalized_source_dates():
    collection = FakeTradeCalendarCollection()

    result = refresh_trade_calendar_cache(
        lambda: pd.DataFrame(
            {
                "trade_date": [
                    "2026-03-19",
                    "2026-03-18",
                    "2026-03-19",
                ]
            }
        ),
        collection=collection,
        now_provider=_now,
    )

    doc = collection.find_one({"market": "cn_a", "source": "sina"})
    assert list(result["trade_date"].astype(str)) == ["2026-03-18", "2026-03-19"]
    assert doc["trade_dates"] == ["2026-03-18", "2026-03-19"]
    assert doc["min_trade_date"] == "2026-03-18"
    assert doc["max_trade_date"] == "2026-03-19"
    assert doc["date_count"] == 2
    assert doc["last_error_type"] == ""
    assert collection.created_indexes


def test_fetch_trade_dates_falls_back_to_cache_and_records_source_error():
    collection = FakeTradeCalendarCollection([_cache_doc()])

    result = fetch_trade_dates_with_persistent_cache(
        lambda: (_ for _ in ()).throw(SSLError("temporary ssl failure")),
        collection=collection,
        now_provider=_now,
        prefer_cache=False,
    )

    doc = collection.find_one({"market": "cn_a", "source": "sina"})
    assert list(result["trade_date"].astype(str))[-1] == "2026-12-31"
    assert doc["last_error_type"] == "SSLError"
    assert doc["last_error_message"] == "temporary ssl failure"
    assert doc["fallback_hits"] == 1


def test_fetch_trade_dates_fails_closed_when_cache_no_longer_covers_today():
    collection = FakeTradeCalendarCollection([_cache_doc(max_trade_date="2026-03-19")])

    with pytest.raises(TradeCalendarUnavailable):
        fetch_trade_dates_with_persistent_cache(
            lambda: (_ for _ in ()).throw(SSLError("temporary ssl failure")),
            collection=collection,
            now_provider=_now,
        )


def test_refresh_trade_calendar_cache_rejects_abnormally_shrunken_update():
    collection = FakeTradeCalendarCollection(
        [
            {
                **_cache_doc(),
                "trade_dates": [f"2026-03-{day:02d}" for day in range(1, 11)],
                "date_count": 10,
                "max_trade_date": "2026-03-10",
            }
        ]
    )

    with pytest.raises(ValueError, match="shrank"):
        refresh_trade_calendar_cache(
            lambda: pd.DataFrame({"trade_date": ["2026-03-10"]}),
            collection=collection,
            now_provider=_now,
        )

    doc = collection.find_one({"market": "cn_a", "source": "sina"})
    assert doc["date_count"] == 10
    assert doc["checksum"] == "sha256:old"


def test_fq_trading_fetch_trade_dates_uses_persistent_cache_entry(monkeypatch):
    calls = []

    def fake_fetch_with_cache(fetcher, **kwargs):
        calls.append(kwargs)
        return pd.DataFrame({"trade_date": [datetime(2026, 3, 19).date()]})

    monkeypatch.setattr(
        dt, "fetch_trade_dates_with_persistent_cache", fake_fetch_with_cache
    )

    result = dt.fq_trading_fetch_trade_dates(source="sina")

    assert list(result["trade_date"].astype(str)) == ["2026-03-19"]
    assert calls == [{"source": "sina"}]
