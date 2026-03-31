# -*- coding: utf-8 -*-

import runpy
import sys
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


class FakeSyncService:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"positions": {"count": 1}}

    def sync_once(self, *, include_credit_subjects=False, seed_symbol_snapshots=False):
        self.calls.append(
            {
                "include_credit_subjects": include_credit_subjects,
                "seed_symbol_snapshots": seed_symbol_snapshots,
            }
        )
        return dict(self.result)


class FakeSymbolPositionService:
    def __init__(self):
        self.calls = 0

    def refresh_all_from_positions(self):
        self.calls += 1
        return [{"symbol": "600570"}]


def test_sync_service_runs_expected_tasks_in_order_and_optionally_credit_subjects():
    from freshquant.xt_account_sync.service import XtAccountSyncService

    observed = []
    service = XtAccountSyncService(
        sync_assets=lambda: observed.append("assets") or {"count": 1},
        sync_credit_detail=lambda: observed.append("credit_detail")
        or {"state": "ALLOW_OPEN"},
        sync_positions=lambda: observed.append("positions") or {"count": 2},
        seed_symbol_snapshots=lambda: observed.append("seed") or {"count": 3},
        sync_orders=lambda: observed.append("orders") or {"count": 4},
        sync_trades=lambda: observed.append("trades") or {"count": 5},
        sync_credit_subjects=lambda: observed.append("credit_subjects") or {"count": 6},
    )

    result = service.sync_once(
        include_credit_subjects=True,
        seed_symbol_snapshots=True,
    )

    assert observed == [
        "assets",
        "credit_detail",
        "positions",
        "seed",
        "orders",
        "trades",
        "credit_subjects",
    ]
    assert result["assets"]["count"] == 1
    assert result["credit_subjects"]["count"] == 6


def test_worker_run_once_calls_sync_service_without_credit_subjects_by_default():
    from freshquant.xt_account_sync.worker import run_once

    service = FakeSyncService()

    result = run_once(service=service)

    assert result["positions"]["count"] == 1
    assert service.calls == [
        {
            "include_credit_subjects": False,
            "seed_symbol_snapshots": True,
        }
    ]


def test_worker_run_once_logs_when_positions_snapshot_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync import worker as worker_module

    service = FakeSyncService(
        result={
            "positions": {
                "quarantined": True,
                "reason": "empty_snapshot_with_positive_market_value",
            }
        }
    )
    warnings = []
    monkeypatch.setattr(
        worker_module,
        "logger",
        SimpleNamespace(warning=lambda message, *args: warnings.append(message % args)),
    )

    worker_module.run_once(service=service)

    assert warnings == [
        "xt_account_sync positions snapshot quarantined: empty_snapshot_with_positive_market_value"
    ]


def test_worker_main_once_returns_zero():
    from freshquant.xt_account_sync.worker import main

    service = FakeSyncService()

    result = main(argv=["--once"], service=service)

    assert result == 0
    assert service.calls == [
        {
            "include_credit_subjects": False,
            "seed_symbol_snapshots": True,
        }
    ]


def test_worker_main_uses_fifteen_second_default_interval(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync import worker as worker_module

    observed: dict[str, object] = {}
    monkeypatch.setattr(
        worker_module,
        "run_forever",
        lambda **kwargs: observed.update(kwargs),
    )

    result = worker_module.main(argv=[])

    assert result == 0
    assert observed["interval_seconds"] == 15.0


def test_worker_module_runs_main_when_executed_as_module(
    monkeypatch: pytest.MonkeyPatch,
):
    calls = []

    class FakeDefaultService:
        def sync_once(
            self,
            *,
            include_credit_subjects=False,
            seed_symbol_snapshots=False,
        ):
            calls.append(
                {
                    "include_credit_subjects": include_credit_subjects,
                    "seed_symbol_snapshots": seed_symbol_snapshots,
                }
            )
            return {"positions": {"count": 1}}

    fake_service_module = types.ModuleType("freshquant.xt_account_sync.service")
    setattr(
        fake_service_module,
        "XtAccountSyncService",
        type(
            "FakeXtAccountSyncService",
            (),
            {"build_default": staticmethod(lambda: FakeDefaultService())},
        ),
    )

    monkeypatch.setitem(
        sys.modules,
        "freshquant.xt_account_sync.service",
        fake_service_module,
    )
    monkeypatch.delitem(
        sys.modules,
        "freshquant.xt_account_sync.worker",
        raising=False,
    )
    monkeypatch.setattr(sys, "argv", ["worker", "--once"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("freshquant.xt_account_sync.worker", run_name="__main__")

    assert excinfo.value.code == 0
    assert calls == [
        {
            "include_credit_subjects": False,
            "seed_symbol_snapshots": True,
        }
    ]


def test_worker_run_forever_schedules_credit_subjects_and_only_seeds_once():
    from freshquant.xt_account_sync.worker import run_forever

    service = FakeSyncService()
    symbol_position_service = FakeSymbolPositionService()
    moments = iter(
        [
            datetime(2026, 3, 19, 9, 19, tzinfo=timezone.utc),
            datetime(2026, 3, 19, 9, 20, tzinfo=timezone.utc),
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
            interval_seconds=3,
            sleep_fn=fake_sleep,
            now_provider=fake_now,
            scheduled_hour=9,
            scheduled_minute=20,
            symbol_position_service=symbol_position_service,
        )

    assert symbol_position_service.calls == 1
    assert service.calls == [
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": False,
        },
    ]
    assert sleep_calls == [3]


def test_build_default_sync_service_filters_replayed_orders_and_trades_by_cursor(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "STOCK"

        def query_stock_asset(self):
            return {"account_id": self.account_id, "cash": 1.0}

        def query_credit_detail(self):
            return []

        def query_stock_positions(self):
            return []

        def query_stock_orders(self):
            return [
                {"account_id": self.account_id, "order_id": "O-1", "order_time": 100},
                {"account_id": self.account_id, "order_id": "O-2", "order_time": 100},
            ]

        def query_stock_trades(self):
            return [
                {
                    "account_id": self.account_id,
                    "traded_id": "T-1",
                    "traded_time": 101,
                    "stock_code": "000001.SZ",
                },
                {
                    "account_id": self.account_id,
                    "traded_id": "T-2",
                    "traded_time": 101,
                    "stock_code": "000002.SZ",
                },
            ]

        def query_credit_subjects(self):
            return []

    class FakePositionRepository:
        def get_config(self):
            return {}

        def insert_snapshot(self, snapshot):
            return snapshot

        def upsert_current_state(self, current_state):
            return current_state

    class FakeCreditSubjectRepository:
        def upsert_subject(self, document):
            return document

        def delete_missing_subjects(self, account_id, instrument_ids):
            return 0

    class FakeStateCollection:
        def __init__(self):
            self.docs = {}

        def find_one(self, query):
            return self.docs.get((query.get("account_id"), query.get("stream")))

        def replace_one(self, query, document, upsert=False):
            self.docs[(query.get("account_id"), query.get("stream"))] = dict(document)
            return None

    observed: dict[str, list[list[dict[str, object]]]] = {
        "orders_batches": [],
        "trades_batches": [],
    }

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service._load_puppet_module",
        lambda: types.SimpleNamespace(
            saveAssets=lambda assets: None,
            saveOrders=lambda orders: observed["orders_batches"].append(
                [dict(item) for item in orders]
            ),
            saveTrades=lambda trades: observed["trades_batches"].append(
                [dict(item) for item in trades]
            ),
        ),
    )

    state_collection = FakeStateCollection()
    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        position_repository=FakePositionRepository(),
        reconcile_service=types.SimpleNamespace(
            reconcile_account=lambda *args, **kwargs: {"confirmed_candidates": []}
        ),
        credit_subject_repository=FakeCreditSubjectRepository(),
        sync_state_collection=state_collection,
    )

    first_orders = service.sync_orders()
    second_orders = service.sync_orders()
    first_trades = service.sync_trades()
    second_trades = service.sync_trades()

    assert first_orders["count"] == 2
    assert second_orders["count"] == 0
    assert first_trades["count"] == 2
    assert second_trades["count"] == 0
    assert observed["orders_batches"] == [
        [
            {"account_id": "acct-sync", "order_id": "O-1", "order_time": 100},
            {"account_id": "acct-sync", "order_id": "O-2", "order_time": 100},
        ]
    ]
    assert observed["trades_batches"] == [
        [
            {
                "account_id": "acct-sync",
                "traded_id": "T-1",
                "traded_time": 101,
                "stock_code": "000001.SZ",
            },
            {
                "account_id": "acct-sync",
                "traded_id": "T-2",
                "traded_time": 101,
                "stock_code": "000002.SZ",
            },
        ]
    ]


def test_build_default_sync_positions_quarantines_empty_snapshot_with_positive_market_value(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "CREDIT"

        def query_stock_positions(self):
            return []

    class FakePositionRepository:
        def get_latest_snapshot(self):
            return {
                "account_id": "acct-sync",
                "market_value": 128000.0,
            }

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.02,
                }
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {"count": 0, "account_id": "acct-sync"}

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        position_repository=FakePositionRepository(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["quarantined"] is True
    assert result["reason"] == "empty_snapshot_with_positive_market_value"
    assert result["previous_summary"]["symbol_count"] == 1
    assert result["current_summary"]["symbol_count"] == 0
    assert result["latest_credit_market_value"] == 128000.0
    assert persist_calls == []
    assert reconcile_calls == []


def test_build_default_sync_positions_quarantines_severely_shrunk_snapshot_when_credit_market_value_stays_high(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "CREDIT"

        def query_stock_positions(self):
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 100,
                    "avg_price": 10.0,
                }
            ]

    class FakePositionRepository:
        def get_latest_snapshot(self):
            return {
                "account_id": "acct-sync",
                "market_value": 98000.0,
            }

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 900,
                    "avg_price": 170.0,
                },
                {
                    "account_id": "acct-sync",
                    "stock_code": "600570.SH",
                    "volume": 800,
                    "avg_price": 25.0,
                },
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.0,
                },
                {
                    "account_id": "acct-sync",
                    "stock_code": "603919.SH",
                    "volume": 2800,
                    "avg_price": 18.0,
                },
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {"count": 1, "account_id": "acct-sync"}

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        position_repository=FakePositionRepository(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["quarantined"] is True
    assert result["reason"] == "shrunk_snapshot_with_positive_market_value"
    assert result["previous_summary"]["symbol_count"] == 4
    assert result["current_summary"]["symbol_count"] == 1
    assert result["current_summary"]["estimated_market_value"] == 1000.0
    assert result["latest_credit_market_value"] == 98000.0
    assert persist_calls == []
    assert reconcile_calls == []


def test_build_default_sync_positions_quarantines_small_account_severe_shrink_when_credit_market_value_stays_high(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "CREDIT"

        def query_stock_positions(self):
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 100,
                    "avg_price": 170.0,
                }
            ]

    class FakePositionRepository:
        def get_latest_snapshot(self):
            return {
                "account_id": "acct-sync",
                "market_value": 153000.0,
            }

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 900,
                    "avg_price": 170.0,
                }
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {"count": 1, "account_id": "acct-sync"}

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        position_repository=FakePositionRepository(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["quarantined"] is True
    assert (
        result["reason"] == "small_account_shrunk_snapshot_with_positive_market_value"
    )
    assert result["previous_summary"]["symbol_count"] == 1
    assert result["current_summary"]["symbol_count"] == 1
    assert result["current_summary"]["total_volume"] == 100
    assert result["latest_credit_market_value"] == 153000.0
    assert persist_calls == []
    assert reconcile_calls == []


def test_build_default_sync_positions_allows_empty_snapshot_when_credit_market_value_is_flat(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "CREDIT"

        def query_stock_positions(self):
            return []

    class FakePositionRepository:
        def get_latest_snapshot(self):
            return {
                "account_id": "acct-sync",
                "market_value": 0.0,
            }

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.02,
                }
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(positions, **kwargs):
        persist_calls.append((positions, kwargs))
        return {"count": 0, "account_id": "acct-sync"}

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return {"confirmed_candidates": []}

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        position_repository=FakePositionRepository(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["count"] == 0
    assert result["account_id"] == "acct-sync"
    assert result["reconcile"] == {"confirmed_candidates": []}
    assert "quarantined" not in result
    assert len(persist_calls) == 1
    assert persist_calls[0][0] == []
    assert len(reconcile_calls) == 1


def test_persist_positions_clears_only_current_account_and_invalidates_holdings():
    from freshquant.xt_account_sync.persistence import persist_assets, persist_positions

    class FakeAssetCollection:
        def __init__(self):
            self.operations = []

        def __bool__(self):
            raise NotImplementedError(
                "Collection objects do not implement truth value testing"
            )

        def bulk_write(self, operations):
            self.operations.extend(operations)

    asset_collection = FakeAssetCollection()

    asset_result = persist_assets(
        [{"account_id": "acct-a", "cash": 100.0}],
        collection=asset_collection,
    )

    assert asset_result["count"] == 1
    assert len(asset_collection.operations) == 1

    class FakeCollection:
        def __init__(self):
            self.docs = [
                {"account_id": "acct-a", "stock_code": "600000.SH", "volume": 10},
                {"account_id": "acct-a", "stock_code": "600570.SH", "volume": 20},
                {"account_id": "acct-b", "stock_code": "000001.SZ", "volume": 30},
            ]

        def __bool__(self):
            raise NotImplementedError(
                "Collection objects do not implement truth value testing"
            )

        def bulk_write(self, operations):
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

        def delete_many(self, query):
            account_id = query.get("account_id")
            stock_filter = query.get("stock_code")
            if isinstance(stock_filter, dict) and "$nin" in stock_filter:
                excluded = set(stock_filter["$nin"])
                self.docs = [
                    document
                    for document in self.docs
                    if document.get("account_id") != account_id
                    or document.get("stock_code") in excluded
                ]
            else:
                self.docs = [
                    document
                    for document in self.docs
                    if document.get("account_id") != account_id
                ]
            return None

    invalidation_calls = []
    collection = FakeCollection()

    result = persist_positions(
        [
            {"account_id": "acct-a", "stock_code": "600570.SH", "volume": 200},
            {"account_id": "acct-a", "stock_code": "688111.SH", "volume": 300},
        ],
        account_id="acct-a",
        collection=collection,
        invalidator=lambda: invalidation_calls.append("bumped"),
    )

    assert result["count"] == 2
    assert invalidation_calls == ["bumped"]
    assert collection.docs == [
        {"account_id": "acct-a", "stock_code": "600570.SH", "volume": 200},
        {"account_id": "acct-b", "stock_code": "000001.SZ", "volume": 30},
        {"account_id": "acct-a", "stock_code": "688111.SH", "volume": 300},
    ]


def test_persist_positions_deletes_current_account_when_snapshot_is_empty():
    from freshquant.xt_account_sync.persistence import persist_positions

    class FakeCollection:
        def __init__(self):
            self.docs = [
                {"account_id": "acct-a", "stock_code": "600570.SH", "volume": 20},
                {"account_id": "acct-b", "stock_code": "000001.SZ", "volume": 30},
            ]

        def __bool__(self):
            raise NotImplementedError(
                "Collection objects do not implement truth value testing"
            )

        def bulk_write(self, operations):
            raise AssertionError("bulk_write should not be called for empty snapshots")

        def delete_many(self, query):
            account_id = query.get("account_id")
            self.docs = [
                document
                for document in self.docs
                if document.get("account_id") != account_id
            ]
            return None

    invalidation_calls = []
    collection = FakeCollection()

    result = persist_positions(
        [],
        account_id="acct-a",
        collection=collection,
        invalidator=lambda: invalidation_calls.append("bumped"),
    )

    assert result["count"] == 0
    assert invalidation_calls == ["bumped"]
    assert collection.docs == [
        {"account_id": "acct-b", "stock_code": "000001.SZ", "volume": 30},
    ]


def test_refresh_credit_detail_uses_force_profit_reduce_below_holding_threshold():
    from freshquant.position_management.models import FORCE_PROFIT_REDUCE
    from freshquant.xt_account_sync.persistence import refresh_credit_detail

    class FakeRepository:
        def __init__(self):
            self.snapshots = []
            self.current_state = None

        def get_config(self):
            return {
                "thresholds": {
                    "allow_open_min_bail": 800000.0,
                    "holding_only_min_bail": 100000.0,
                }
            }

        def insert_snapshot(self, snapshot):
            self.snapshots.append(dict(snapshot))

        def upsert_current_state(self, current_state):
            self.current_state = dict(current_state)

    repository = FakeRepository()

    result = refresh_credit_detail(
        {"m_dEnableBailBalance": 50000},
        account_id="068000076370",
        account_type="CREDIT",
        repository=repository,
        now_provider=lambda: datetime(2026, 3, 19, tzinfo=timezone.utc),
    )

    assert result["state"] == FORCE_PROFIT_REDUCE
    assert repository.current_state["state"] == FORCE_PROFIT_REDUCE


def test_sync_credit_subjects_does_not_delete_existing_rows_when_snapshot_missing():
    from freshquant.xt_account_sync.persistence import sync_credit_subjects

    class FakeRepository:
        def __init__(self):
            self.upserts = []
            self.delete_calls = []

        def upsert_subject(self, document):
            self.upserts.append(dict(document))

        def delete_missing_subjects(self, account_id, instrument_ids):
            self.delete_calls.append((account_id, list(instrument_ids)))
            return 3

    repository = FakeRepository()

    result = sync_credit_subjects(
        None,
        account_id="068000076370",
        account_type="CREDIT",
        repository=repository,
        now_provider=lambda: datetime(2026, 3, 19, tzinfo=timezone.utc),
    )

    assert result["count"] == 0
    assert result["deleted_count"] == 0
    assert repository.upserts == []
    assert repository.delete_calls == []
