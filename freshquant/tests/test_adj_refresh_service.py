from datetime import date, datetime, timezone

import pytest

from freshquant.market_data.xtdata.adj_refresh_service import AdjRefreshService
from freshquant.market_data.xtdata.adj_refresh_worker import (
    main,
    run_forever,
    run_once,
)


class InMemoryAdjRefreshRepository:
    def __init__(self, base_adj_docs=None):
        self.base_adj_docs = dict(base_adj_docs or {})
        self.saved_docs = {"stock": [], "etf": []}

    def get_base_anchor(self, kind, code, base_anchor_date):
        return self.base_adj_docs.get((kind, code, base_anchor_date))

    def upsert_intraday_override(self, kind, document):
        self.saved_docs[kind].append(dict(document))
        return dict(document)


class FakeXtDataAdjClient:
    def __init__(self, close_pairs=None):
        self.close_pairs = dict(close_pairs or {})

    def get_daily_close_pair(self, code, trade_date):
        return self.close_pairs.get((code, trade_date))


class FakeSyncService:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or {"count": 1}

    def sync_once(self):
        self.calls += 1
        return dict(self.result)


def test_sync_adj_refresh_once_writes_stock_and_etf_intraday_overrides():
    repository = InMemoryAdjRefreshRepository(
        {
            ("stock", "sz000001", "2026-03-08"): {"date": "2026-03-08", "adj": 2.0},
            ("etf", "sh510050", "2026-03-08"): {"date": "2026-03-08", "adj": 1.5},
        }
    )
    market_client = FakeXtDataAdjClient(
        {
            ("sz000001", "2026-03-08"): {"front_close": 18.0, "raw_close": 10.0},
            ("sh510050", "2026-03-08"): {"front_close": 1.2, "raw_close": 1.0},
        }
    )
    service = AdjRefreshService(
        repository=repository,
        market_client=market_client,
        code_loader=lambda: ["sz000001", "sh510050"],
        trade_date_provider=lambda: date(2026, 3, 9),
        prev_trade_date_provider=lambda: date(2026, 3, 8),
        now_provider=lambda: datetime(2026, 3, 9, 1, 20, tzinfo=timezone.utc),
    )

    result = service.sync_once()

    assert result["count"] == 2
    assert result["stock_count"] == 1
    assert result["etf_count"] == 1
    assert repository.saved_docs["stock"][0]["code"] == "000001"
    assert repository.saved_docs["stock"][0]["trade_date"] == "2026-03-09"
    assert repository.saved_docs["stock"][0]["base_anchor_date"] == "2026-03-08"
    assert repository.saved_docs["stock"][0]["anchor_scale"] == pytest.approx(0.9)
    assert repository.saved_docs["etf"][0]["code"] == "510050"
    assert repository.saved_docs["etf"][0]["anchor_scale"] == pytest.approx(0.8)


def test_sync_adj_refresh_once_uses_repository_anchor_date_for_xtdata_pair():
    repository = InMemoryAdjRefreshRepository(
        {
            ("stock", "sz000001", "2026-03-08"): {"date": "2026-03-07", "adj": 2.0},
        }
    )
    market_client = FakeXtDataAdjClient(
        {
            ("sz000001", "2026-03-07"): {"front_close": 18.0, "raw_close": 10.0},
        }
    )
    service = AdjRefreshService(
        repository=repository,
        market_client=market_client,
        code_loader=lambda: ["sz000001"],
        trade_date_provider=lambda: date(2026, 3, 9),
        prev_trade_date_provider=lambda: date(2026, 3, 8),
        now_provider=lambda: datetime(2026, 3, 9, 1, 20, tzinfo=timezone.utc),
    )

    result = service.sync_once()

    assert result["count"] == 1
    assert repository.saved_docs["stock"][0]["base_anchor_date"] == "2026-03-07"
    assert repository.saved_docs["stock"][0]["anchor_scale"] == pytest.approx(0.9)


def test_worker_run_once_calls_sync_service():
    service = FakeSyncService()

    result = run_once(service=service)

    assert result["count"] == 1
    assert service.calls == 1


def test_worker_main_once_returns_zero():
    service = FakeSyncService()

    result = main(argv=["--once"], service=service)

    assert result == 0
    assert service.calls == 1


def test_worker_main_defaults_schedule_to_0920(monkeypatch):
    service = FakeSyncService()
    captured = {}

    def fake_run_forever(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        "freshquant.market_data.xtdata.adj_refresh_worker.run_forever",
        fake_run_forever,
    )

    result = main(argv=[], service=service)

    assert result == 0
    assert captured["scheduled_hour"] == 9
    assert captured["scheduled_minute"] == 20


def test_worker_run_forever_syncs_on_startup_then_at_schedule():
    service = FakeSyncService()
    moments = iter(
        [
            datetime(2026, 3, 9, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 3, 9, 9, 20, tzinfo=timezone.utc),
        ]
    )
    sleep_calls = []

    def fake_now():
        return next(moments)

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_forever(
            service=service,
            interval_seconds=30,
            sleep_fn=fake_sleep,
            now_provider=fake_now,
            scheduled_hour=9,
            scheduled_minute=20,
        )

    assert service.calls == 2
    assert sleep_calls == [30]
