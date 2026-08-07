# -*- coding: utf-8 -*-

import runpy
import sys
import time
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


class SequencedSyncService:
    def __init__(self, outcomes):
        self.calls = []
        self.outcomes = list(outcomes)

    def sync_once(self, *, include_credit_subjects=False, seed_symbol_snapshots=False):
        self.calls.append(
            {
                "include_credit_subjects": include_credit_subjects,
                "seed_symbol_snapshots": seed_symbol_snapshots,
            }
        )
        if not self.outcomes:
            raise AssertionError("no more outcomes configured")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return dict(outcome)


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


def test_worker_run_once_logs_when_positions_snapshot_is_empty_guarded(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync import worker as worker_module

    service = FakeSyncService(
        result={
            "positions": {
                "empty_snapshot_guard": True,
                "deleted_missing": [],
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
        "xt_account_sync empty snapshot guarded; kept existing positions"
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


def test_worker_run_forever_schedules_credit_subjects_and_refreshes_symbol_snapshots_each_loop():
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
            "seed_symbol_snapshots": True,
        },
    ]
    assert sleep_calls == [3]


def test_worker_run_forever_retries_retryable_xt_errors_until_startup_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync import worker as worker_module

    service = SequencedSyncService(
        [
            RuntimeError("xtquant connect failed: -1"),
            {"positions": {"count": 1}},
            {"positions": {"count": 2}},
        ]
    )
    warnings = []
    monkeypatch.setattr(
        worker_module,
        "logger",
        SimpleNamespace(
            warning=lambda message, *args: warnings.append(message % args),
        ),
    )
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
        if len(sleep_calls) >= 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        worker_module.run_forever(
            service=service,
            interval_seconds=3,
            sleep_fn=fake_sleep,
            now_provider=fake_now,
            scheduled_hour=9,
            scheduled_minute=20,
            retry_delay_seconds=5,
            retry_delay_max_seconds=60,
        )

    assert service.calls == [
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
    ]
    assert sleep_calls == [5, 3]
    assert warnings == [
        "xt_account_sync XT unavailable; retrying in 5.0 seconds: xtquant connect failed: -1"
    ]


def test_worker_treats_empty_credit_detail_as_retryable_xt_failure():
    from freshquant.xt_account_sync.worker import _is_retryable_xt_sync_error

    assert _is_retryable_xt_sync_error(
        ValueError("query_credit_detail returned no records")
    )


def test_worker_run_forever_rebuilds_default_service_after_retryable_xt_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync import worker as worker_module

    failed_service = SequencedSyncService([RuntimeError("xtquant connect failed: -1")])
    recovered_service = SequencedSyncService(
        [
            {"positions": {"count": 1}},
            {"positions": {"count": 2}},
        ]
    )
    built_services = []
    service_queue = iter([failed_service, recovered_service])

    def _build_service():
        built_services.append("build")
        return next(service_queue)

    monkeypatch.setattr(
        worker_module,
        "XtAccountSyncService",
        type(
            "FakeXtAccountSyncService",
            (),
            {"build_default": staticmethod(_build_service)},
        ),
    )
    warnings = []
    monkeypatch.setattr(
        worker_module,
        "logger",
        SimpleNamespace(
            warning=lambda message, *args: warnings.append(message % args),
        ),
    )
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
        if len(sleep_calls) >= 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        worker_module.run_forever(
            interval_seconds=3,
            sleep_fn=fake_sleep,
            now_provider=fake_now,
            scheduled_hour=9,
            scheduled_minute=20,
            retry_delay_seconds=5,
            retry_delay_max_seconds=60,
        )

    assert built_services == ["build", "build"]
    assert failed_service.calls == [
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        }
    ]
    assert recovered_service.calls == [
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
        {
            "include_credit_subjects": True,
            "seed_symbol_snapshots": True,
        },
    ]
    assert sleep_calls == [5, 3]
    assert warnings == [
        "xt_account_sync XT unavailable; retrying in 5.0 seconds: xtquant connect failed: -1"
    ]


def test_worker_run_forever_keeps_non_retryable_errors_fatal():
    from freshquant.xt_account_sync.worker import run_forever

    service = SequencedSyncService([ValueError("xtquant.path is required")])
    sleep_calls = []

    with pytest.raises(ValueError, match="xtquant.path is required"):
        run_forever(
            service=service,
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
        )

    assert sleep_calls == []


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


def test_build_default_sync_positions_skips_reconcile_on_empty_snapshot_guard(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "STOCK"

        def query_stock_positions(self):
            return []

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.02,
                    "sync_missing_count": 0,
                }
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {
            "count": 0,
            "account_id": "acct-sync",
            "empty_snapshot_guard": True,
            "deleted_missing": [],
            "cleared_zero_volume": [],
        }

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["empty_snapshot_guard"] is True
    assert result["reconcile_skipped"] is True
    assert result["reconcile"] is None
    assert len(persist_calls) == 1
    assert reconcile_calls == []


def test_build_default_sync_positions_passes_effective_view_with_hysteresis_retained_symbol(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "STOCK"

        def query_stock_positions(self):
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 900,
                    "avg_price": 170.0,
                }
            ]

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "300760.SZ",
                    "volume": 900,
                    "avg_price": 170.0,
                    "sync_missing_count": 0,
                },
                {
                    "account_id": "acct-sync",
                    "stock_code": "600271.SH",
                    "volume": 78100,
                    "avg_price": 8.7,
                    "sync_missing_count": 5,
                },
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {
            "count": 1,
            "account_id": "acct-sync",
            "empty_snapshot_guard": False,
            "deleted_missing": [],
            "cleared_zero_volume": [],
        }

    def _capture_reconcile(account_id, **kwargs):
        reconcile_calls.append((account_id, kwargs))
        return {"confirmed_candidates": []}

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["reconcile_skipped"] is False
    assert len(reconcile_calls) == 1
    reconcile_account_id, reconcile_kwargs = reconcile_calls[0]
    assert reconcile_account_id == "acct-sync"
    effective = reconcile_kwargs["positions"]
    effective_codes = {doc["stock_code"] for doc in effective}
    # 滞回期内的缺失标的（sync_missing_count=5 < 20）必须保留在有效视图中
    assert "600271.SH" in effective_codes
    assert "300760.SZ" in effective_codes


def test_build_default_sync_positions_excludes_cleared_zero_volume_from_effective_view(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "STOCK"

        def query_stock_positions(self):
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "600271.SH",
                    "volume": 0,
                }
            ]

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "600271.SH",
                    "volume": 0,
                    "sync_missing_count": 0,
                },
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.0,
                    "sync_missing_count": 0,
                },
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(*args, **kwargs):
        persist_calls.append((args, kwargs))
        return {
            "count": 1,
            "account_id": "acct-sync",
            "empty_snapshot_guard": False,
            "deleted_missing": [],
            "cleared_zero_volume": ["600271.SH"],
        }

    def _capture_reconcile(account_id, **kwargs):
        reconcile_calls.append((account_id, kwargs))
        return {"confirmed_candidates": []}

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["reconcile_skipped"] is False
    assert len(reconcile_calls) == 1
    effective = reconcile_calls[0][1]["positions"]
    effective_codes = {doc["stock_code"] for doc in effective}
    assert "600271.SH" not in effective_codes
    assert "512600.SH" in effective_codes


def test_build_default_sync_positions_uses_effective_view_from_persisted_collection(
    monkeypatch: pytest.MonkeyPatch,
):
    from freshquant.xt_account_sync.service import XtAccountSyncService

    class FakeQueryClient:
        account_id = "acct-sync"
        account_type = "STOCK"

        def query_stock_positions(self):
            return []

    class FakePositionsCollection:
        def find(self, query):
            assert query == {"account_id": "acct-sync"}
            return [
                {
                    "account_id": "acct-sync",
                    "stock_code": "512600.SH",
                    "volume": 4700,
                    "avg_price": 1.02,
                    "sync_missing_count": 0,
                    "sync_last_seen_at": 100,
                }
            ]

    persist_calls = []
    reconcile_calls = []

    def _capture_persist(positions, **kwargs):
        persist_calls.append((positions, kwargs))
        return {
            "count": 0,
            "account_id": "acct-sync",
            "empty_snapshot_guard": False,
            "deleted_missing": [],
            "cleared_zero_volume": [],
        }

    def _capture_reconcile(*args, **kwargs):
        reconcile_calls.append((args, kwargs))
        return {"confirmed_candidates": []}

    monkeypatch.setattr(
        "freshquant.xt_account_sync.service.persist_positions",
        _capture_persist,
    )

    service = XtAccountSyncService.build_default(
        client=FakeQueryClient(),
        reconcile_service=SimpleNamespace(reconcile_account=_capture_reconcile),
        positions_collection=FakePositionsCollection(),
    )

    result = service.sync_positions()

    assert result["count"] == 0
    assert result["account_id"] == "acct-sync"
    assert result["reconcile"] == {"confirmed_candidates": []}
    assert result["reconcile_skipped"] is False
    assert len(persist_calls) == 1
    assert len(reconcile_calls) == 1
    effective = reconcile_calls[0][1]["positions"]
    assert [doc["stock_code"] for doc in effective] == ["512600.SH"]


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
                {
                    "account_id": "acct-a",
                    "stock_code": "600000.SH",
                    "volume": 10,
                    "sync_missing_count": 0,
                    "sync_last_seen_at": int(time.time()),
                },
                {
                    "account_id": "acct-a",
                    "stock_code": "600570.SH",
                    "volume": 20,
                    "sync_missing_count": 0,
                    "sync_last_seen_at": int(time.time()),
                },
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
            stock_code = query.get("stock_code")
            self.docs = [
                document
                for document in self.docs
                if not (
                    document.get("account_id") == account_id
                    and (stock_code is None or document.get("stock_code") == stock_code)
                )
            ]
            return 0

        def update_one(self, query, update):
            for document in self.docs:
                if all(document.get(key) == value for key, value in query.items()):
                    if "$inc" in update:
                        for key, value in update["$inc"].items():
                            document[key] = int(document.get(key) or 0) + value
                    return 1
            return 0

        def find(self, query):
            return [
                dict(document)
                for document in self.docs
                if all(document.get(key) == value for key, value in query.items())
            ]

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
    # 600000.SH 不在本次快照，滞回首轮缺失计数=1，保留不删除
    kept_600000 = [d for d in collection.docs if d.get("stock_code") == "600000.SH"][0]
    assert kept_600000["sync_missing_count"] == 1
    assert {d["stock_code"] for d in collection.docs} == {
        "600570.SH",
        "600000.SH",
        "000001.SZ",
        "688111.SH",
    }
    updated_600570 = [d for d in collection.docs if d.get("stock_code") == "600570.SH"][
        0
    ]
    assert updated_600570["volume"] == 200
    assert updated_600570["sync_missing_count"] == 0


def test_persist_positions_deletes_current_account_when_snapshot_is_empty():
    from freshquant.xt_account_sync.persistence import persist_positions

    class FakeCollection:
        def __init__(self):
            self.docs = [
                {
                    "account_id": "acct-a",
                    "stock_code": "600570.SH",
                    "volume": 20,
                    "sync_missing_count": 0,
                    "sync_last_seen_at": 1,
                },
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
            return 0

        def update_one(self, query, update):
            return 0

        def find(self, query):
            return [
                dict(document)
                for document in self.docs
                if all(document.get(key) == value for key, value in query.items())
            ]

    invalidation_calls = []
    collection = FakeCollection()

    result = persist_positions(
        [],
        account_id="acct-a",
        collection=collection,
        invalidator=lambda: invalidation_calls.append("bumped"),
    )

    # 空快照守卫：保留 acct-a 存量，不删除
    assert result["count"] == 0
    assert result["empty_snapshot_guard"] is True
    assert invalidation_calls == ["bumped"]
    assert collection.docs == [
        {
            "account_id": "acct-a",
            "stock_code": "600570.SH",
            "volume": 20,
            "sync_missing_count": 0,
            "sync_last_seen_at": 1,
        },
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
