from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from freshquant.carnation.enum_instrument import InstrumentType


def _make_dashboard():
    return {
        "bootstrap": {
            "file_path": "D:/fqpack/config/freshquant_bootstrap.yaml",
            "values": {
                "mongodb": {
                    "host": "127.0.0.1",
                    "port": 27027,
                    "db": "freshquant",
                    "gantt_db": "freshquant_gantt",
                },
                "redis": {
                    "host": "127.0.0.1",
                    "port": 6380,
                    "db": 1,
                    "password": "",
                },
                "order_management": {
                    "mongo_database": "freshquant_order_management",
                    "projection_database": "freshquant",
                },
                "position_management": {
                    "mongo_database": "freshquant_position_management",
                },
                "memory": {
                    "mongodb": {
                        "host": "127.0.0.1",
                        "port": 27027,
                        "db": "fq_memory",
                    },
                    "cold_root": "D:/fqpack/runtime/memory",
                    "artifact_root": "D:/fqpack/runtime/memory/artifacts",
                },
                "tdx": {
                    "home": "D:/tdx_biduan",
                    "hq": {"endpoint": "http://127.0.0.1:15001"},
                },
                "api": {"base_url": "http://127.0.0.1:15000"},
                "xtdata": {"port": 58610},
                "runtime": {"log_dir": "D:/fqpack/log/runtime"},
            },
        },
        "settings": {
            "values": {
                "notification": {
                    "webhook": {
                        "dingtalk": {
                            "private": "https://private.example",
                            "public": "https://public.example",
                        }
                    }
                },
                "monitor": {
                    "xtdata": {
                        "mode": "guardian_1m",
                        "max_symbols": 50,
                        "queue_backlog_threshold": 120,
                        "prewarm": {"max_bars": 300},
                    },
                },
                "xtquant": {
                    "path": "D:/xtquant/userdata_mini",
                    "account": "068000076370",
                    "account_type": "CREDIT",
                    "broker_submit_mode": "observe_only",
                },
                "guardian": {
                    "stock": {
                        "lot_amount": 1800,
                        "threshold": {"mode": "percent", "percent": 1.2},
                        "grid_interval": {"mode": "percent", "percent": 3},
                    }
                },
                "position_management": {
                    "allow_open_min_bail": 910000.0,
                    "holding_only_min_bail": 210000.0,
                },
            }
        },
    }


class FakeCollection:
    def __init__(self, initial=None):
        self.documents = list(initial or [])
        self.delete_queries = []

    def find_one(self, _query=None):
        return self.documents[0] if self.documents else None

    def delete_many(self, query):
        normalized_query = dict(query or {})
        self.delete_queries.append(normalized_query)
        if not normalized_query:
            deleted_count = len(self.documents)
            self.documents = []
            return {"deleted_count": deleted_count}
        remaining_documents = []
        deleted_count = 0
        for document in self.documents:
            if all(
                document.get(key) == value for key, value in normalized_query.items()
            ):
                deleted_count += 1
                continue
            remaining_documents.append(document)
        self.documents = remaining_documents
        return {"deleted_count": deleted_count}

    def insert_many(self, documents, ordered=False):
        self.documents.extend(list(documents or []))
        return {"inserted_count": len(list(documents or [])), "ordered": ordered}


class FakeDatabase:
    def __init__(self, initial=None):
        self.collections = {
            key: FakeCollection(value) for key, value in dict(initial or {}).items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


class FakeBulkCollection:
    def __init__(self):
        self.delete_queries = []
        self.bulk_batches = []

    def delete_many(self, query):
        self.delete_queries.append(dict(query or {}))
        return {"deleted_count": 0}

    def bulk_write(self, batch):
        self.bulk_batches.append(list(batch))
        return {"matched_count": 0}


def test_run_initialize_wizard_updates_bootstrap_and_settings_then_bootstraps_runtime():
    from freshquant.initialize import run_initialize_wizard

    calls = []

    class FakeService:
        def get_dashboard(self):
            return _make_dashboard()

        def update_bootstrap(self, payload):
            calls.append(("bootstrap", payload))
            return {"values": payload}

        def update_settings(self, payload):
            calls.append(("settings", payload))
            return {"values": payload}

    prompts = {
        "bootstrap.mongodb.host": "10.0.0.8",
        "settings.xtquant.account": "123456",
        "settings.position_management.allow_open_min_bail": 950000.0,
    }
    lines = []

    result = run_initialize_wizard(
        service=FakeService(),
        prompt_provider=lambda field_key, _label, default, _kind: prompts.get(
            field_key, default
        ),
        output_fn=lines.append,
        runtime_bootstrap_runner=lambda: {
            "xt": {"assets": 1, "positions": 2, "orders": 3, "trades": 4},
            "credit_subjects": {"count": 5},
            "instrument_strategy": {"count": 6},
        },
    )

    assert result["bootstrap"]["mongodb"]["host"] == "10.0.0.8"
    assert result["settings"]["xtquant"]["account"] == "123456"
    assert result["settings"]["position_management"]["allow_open_min_bail"] == 950000.0
    assert calls[0][0] == "bootstrap"
    assert calls[1][0] == "settings"
    assert any("运行态 bootstrap 完成" in line for line in lines)


def test_main_skip_runtime_bootstrap_does_not_execute_runtime_sync():
    from freshquant.initialize import main

    class FakeService:
        def get_dashboard(self):
            return _make_dashboard()

        def update_bootstrap(self, payload):
            return {"values": payload}

        def update_settings(self, payload):
            return {"values": payload}

    lines = []

    result = main(
        ["--skip-runtime-bootstrap"],
        service=FakeService(),
        prompt_provider=lambda _field_key, _label, default, _kind: default,
        output_fn=lines.append,
        runtime_bootstrap_runner=lambda: (_ for _ in ()).throw(
            AssertionError("runtime bootstrap should be skipped")
        ),
    )

    assert result == 0
    assert any("运行态 bootstrap 已跳过" in line for line in lines)


def test_run_runtime_bootstrap_syncs_xt_credit_subjects_and_instrument_strategy_defaults():
    from freshquant.initialize import run_runtime_bootstrap

    instrument_strategy_calls = []
    monitor_loader_calls = []

    summary = run_runtime_bootstrap(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(
                xtdata_mode="guardian_and_clx_15_30",
                xtdata_max_symbols=20,
            ),
            get_strategy_id=lambda code: (
                "guardian_strategy_id" if code == "Guardian" else ""
            ),
        ),
        xt_runtime_sync_runner=lambda: {
            "assets": 1,
            "positions": 2,
            "orders": 3,
            "trades": 4,
        },
        credit_subject_sync_runner=lambda: {"count": 5},
        monitor_code_loader=lambda max_symbols: monitor_loader_calls.append(max_symbols)
        or ["sz000001", "sh510050"],
        instrument_code_loader=lambda code: (
            "510050.SH" if code == "510050" else "000001.SZ"
        ),
        instrument_strategy_writer=lambda instrument_code, instrument_type, strategy_name: instrument_strategy_calls.append(
            (instrument_code, instrument_type, strategy_name)
        ),
        instrument_type_loader=lambda code: (
            InstrumentType.ETF_CN if code == "510050" else InstrumentType.STOCK_CN
        ),
    )

    assert summary["xt"]["assets"] == 1
    assert summary["credit_subjects"]["count"] == 5
    assert summary["instrument_strategy"]["count"] == 2
    assert monitor_loader_calls == [20]
    assert instrument_strategy_calls == [
        ("000001.SZ", "stock", "guardian_strategy_id"),
        ("510050.SH", "etf", "guardian_strategy_id"),
    ]


def test_default_xt_runtime_sync_runner_connects_before_sync_when_connection_missing(
    monkeypatch,
):
    from freshquant.initialize import _default_xt_runtime_sync_runner

    connect_calls = []
    query_calls = []
    persisted_truth = {}
    rebuild_calls = []
    connection_state = {
        "xt_trader": None,
        "acc": None,
        "connected": False,
    }

    class FakeTradingManager:
        def get_connection(self):
            return (
                connection_state["xt_trader"],
                connection_state["acc"],
                connection_state["connected"],
            )

        def update_connection(self, xt_trader, acc, connected):
            connection_state["xt_trader"] = xt_trader
            connection_state["acc"] = acc
            connection_state["connected"] = connected

    fake_manager = FakeTradingManager()

    broker_module = types.ModuleType("morningglory.fqxtrade.fqxtrade.xtquant.broker")

    class FakeXtTrader:
        def query_stock_asset(self, account):
            query_calls.append(("asset", account.account_id))
            return SimpleNamespace(
                account_type=2,
                account_id=account.account_id,
                cash=1.0,
                frozen_cash=0.0,
                market_value=2.0,
                total_asset=3.0,
            )

        def query_stock_positions(self, account):
            query_calls.append(("positions", account.account_id))
            return [
                SimpleNamespace(
                    account_id=account.account_id,
                    stock_code="000001.SZ",
                    volume=100,
                    can_use_volume=100,
                    open_price=12.5,
                    market_value=1300.0,
                    frozen_volume=0,
                    on_road_volume=0,
                    yesterday_volume=100,
                    avg_price=12.5,
                    last_price=13.0,
                    instrument_name="Ping An Bank",
                )
            ]

    def fake_connect(session_id=100):
        connect_calls.append(session_id)
        return FakeXtTrader(), SimpleNamespace(account_id="068000076370"), True

    broker_module.connect = fake_connect
    broker_module.trading_manager = fake_manager
    monkeypatch.setitem(
        sys.modules,
        "morningglory.fqxtrade.fqxtrade.xtquant.broker",
        broker_module,
    )

    monkeypatch.setattr(
        "freshquant.initialize._persist_xt_runtime_truth",
        lambda **kwargs: persisted_truth.update(kwargs) or kwargs,
    )
    monkeypatch.setattr(
        "freshquant.initialize._bootstrap_order_ledger_from_synced_truth",
        lambda **kwargs: rebuild_calls.append(kwargs)
        or {"skipped": False, "position_entries": 1, "auto_open_entries": 1},
    )

    summary = _default_xt_runtime_sync_runner()

    assert connect_calls == [100]
    assert query_calls == [
        ("asset", "068000076370"),
        ("positions", "068000076370"),
    ]
    assert persisted_truth["account_id"] == "068000076370"
    assert persisted_truth["positions"][0]["avg_price"] == 12.5
    assert persisted_truth["orders"] == []
    assert persisted_truth["trades"] == []
    assert rebuild_calls == [
        {
            "xt_positions": persisted_truth["positions"],
        }
    ]
    assert summary == {
        "assets": 1,
        "positions": 1,
        "orders": 0,
        "trades": 0,
        "rebuild": {
            "skipped": False,
            "position_entries": 1,
            "auto_open_entries": 1,
        },
    }


def test_bootstrap_order_ledger_from_synced_truth_purges_state_and_rebuilds_compat():
    from freshquant.initialize import _bootstrap_order_ledger_from_synced_truth

    database = FakeDatabase(
        {
            "om_position_entries": [{"entry_id": "stale-entry"}],
            "om_buy_lots": [{"buy_lot_id": "stale-buy-lot"}],
        }
    )
    projection_database = FakeDatabase(
        {
            "stock_fills_compat": [{"symbol": "000001", "quantity": 100}],
        }
    )
    compat_calls = []

    class FakeRebuildService:
        def build_from_truth(self, *, xt_orders, xt_trades, xt_positions):
            assert xt_orders == []
            assert xt_trades == []
            assert xt_positions == [{"stock_code": "000001.SZ", "avg_price": 12.5}]
            return {
                "broker_orders": 0,
                "execution_fills": 0,
                "position_entries": 1,
                "entry_slices": 1,
                "exit_allocations": 0,
                "reconciliation_gaps": 0,
                "reconciliation_resolutions": 1,
                "auto_open_entries": 1,
                "auto_close_allocations": 0,
                "ingest_rejections": 0,
                "broker_order_documents": [],
                "execution_fill_documents": [],
                "position_entry_documents": [{"entry_id": "entry-1"}],
                "entry_slice_documents": [{"slice_id": "slice-1"}],
                "exit_allocation_documents": [],
                "reconciliation_gap_documents": [],
                "reconciliation_resolution_documents": [
                    {"resolution_id": "resolution-1"}
                ],
                "ingest_rejection_documents": [],
            }

    summary = _bootstrap_order_ledger_from_synced_truth(
        xt_positions=[{"stock_code": "000001.SZ", "avg_price": 12.5}],
        database=database,
        projection_database=projection_database,
        rebuild_service=FakeRebuildService(),
        compat_view_rebuilder=lambda **kwargs: compat_calls.append(kwargs)
        or {
            "synced_symbols": ["000001"],
            "rows_by_symbol": {"000001": 1},
            "rebuilt_collections": ["stock_fills_compat"],
        },
    )

    assert summary == {
        "skipped": False,
        "broker_orders": 0,
        "execution_fills": 0,
        "position_entries": 1,
        "entry_slices": 1,
        "exit_allocations": 0,
        "reconciliation_gaps": 0,
        "reconciliation_resolutions": 1,
        "auto_open_entries": 1,
        "auto_close_allocations": 0,
        "ingest_rejections": 0,
        "purged_collections": [
            "om_order_requests",
            "om_order_events",
            "om_orders",
            "om_broker_orders",
            "om_trade_facts",
            "om_execution_fills",
            "om_buy_lots",
            "om_position_entries",
            "om_lot_slices",
            "om_entry_slices",
            "om_sell_allocations",
            "om_exit_allocations",
            "om_external_candidates",
            "om_reconciliation_gaps",
            "om_reconciliation_resolutions",
            "om_stoploss_bindings",
            "om_entry_stoploss_bindings",
            "om_ingest_rejections",
        ],
        "compat": {
            "synced_symbols": ["000001"],
            "rows_by_symbol": {"000001": 1},
            "rebuilt_collections": ["stock_fills_compat"],
        },
    }
    assert database["om_buy_lots"].documents == []
    assert database["om_position_entries"].documents == [{"entry_id": "entry-1"}]
    assert database["om_reconciliation_resolutions"].documents == [
        {"resolution_id": "resolution-1"}
    ]
    assert compat_calls == [
        {
            "order_database": database,
            "projection_database": projection_database,
        }
    ]


def test_bootstrap_order_ledger_from_synced_truth_purges_existing_ledger_instead_of_skipping():
    from freshquant.initialize import _bootstrap_order_ledger_from_synced_truth

    database = FakeDatabase({"om_position_entries": [{"entry_id": "existing-entry"}]})

    class FakeRebuildService:
        def build_from_truth(self, *, xt_orders, xt_trades, xt_positions):
            assert xt_orders == []
            assert xt_trades == []
            assert xt_positions == []
            return {
                "broker_orders": 0,
                "execution_fills": 0,
                "position_entries": 0,
                "entry_slices": 0,
                "exit_allocations": 0,
                "reconciliation_gaps": 0,
                "reconciliation_resolutions": 0,
                "auto_open_entries": 0,
                "auto_close_allocations": 0,
                "ingest_rejections": 0,
                "broker_order_documents": [],
                "execution_fill_documents": [],
                "position_entry_documents": [],
                "entry_slice_documents": [],
                "exit_allocation_documents": [],
                "reconciliation_gap_documents": [],
                "reconciliation_resolution_documents": [],
                "ingest_rejection_documents": [],
            }

    summary = _bootstrap_order_ledger_from_synced_truth(
        xt_positions=[],
        database=database,
        rebuild_service=FakeRebuildService(),
        compat_view_rebuilder=lambda **kwargs: {
            "synced_symbols": [],
            "rows_by_symbol": {},
            "rebuilt_collections": ["stock_fills_compat"],
        },
    )

    assert summary["skipped"] is False
    assert summary["position_entries"] == 0
    assert database["om_position_entries"].documents == []


def test_rebuild_initialize_compat_views_clears_stock_fills_compat_and_rebuilds_from_order_database(
    monkeypatch,
):
    from freshquant.initialize import _rebuild_initialize_compat_views

    order_database = FakeDatabase({"om_position_entries": [{"entry_id": "entry-1"}]})
    projection_database = FakeDatabase(
        {"stock_fills_compat": [{"symbol": "000001", "quantity": 100}]}
    )
    sync_calls = []

    monkeypatch.setattr(
        "freshquant.order_management.projection.stock_fills_compat.sync_symbols",
        lambda **kwargs: sync_calls.append(kwargs)
        or {
            "synced_symbols": ["000001"],
            "rows_by_symbol": {"000001": 1},
        },
    )

    summary = _rebuild_initialize_compat_views(
        order_database=order_database,
        projection_database=projection_database,
    )

    assert projection_database["stock_fills_compat"].documents == []
    assert projection_database["stock_fills_compat"].delete_queries == [{}]
    assert sync_calls[0]["database"] is projection_database
    assert sync_calls[0]["repository"].database is order_database
    assert summary == {
        "synced_symbols": ["000001"],
        "rows_by_symbol": {"000001": 1},
        "rebuilt_collections": ["stock_fills_compat"],
    }


def test_upsert_xt_runtime_documents_clears_account_scope_even_when_documents_are_empty():
    from freshquant.initialize import _upsert_xt_runtime_documents

    collection = FakeBulkCollection()

    written = _upsert_xt_runtime_documents(
        collection=collection,
        documents=[],
        identity_fields=("account_id", "order_id"),
        scope_query={"account_id": "068000076370"},
    )

    assert written == 0
    assert collection.delete_queries == [{"account_id": "068000076370"}]
    assert collection.bulk_batches == []


def test_default_xt_runtime_sync_runner_returns_empty_summary_when_xt_unavailable(
    monkeypatch,
):
    from freshquant.initialize import _default_xt_runtime_sync_runner

    class FakeTradingManager:
        def get_connection(self):
            return None, None, False

        def update_connection(self, xt_trader, acc, connected):
            raise AssertionError("connection should not be updated when connect fails")

    broker_module = types.ModuleType("morningglory.fqxtrade.fqxtrade.xtquant.broker")
    broker_module.connect = lambda session_id=100: (None, None, False)
    broker_module.trading_manager = FakeTradingManager()
    monkeypatch.setitem(
        sys.modules,
        "morningglory.fqxtrade.fqxtrade.xtquant.broker",
        broker_module,
    )

    monkeypatch.setattr(
        "freshquant.initialize._persist_xt_runtime_truth",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("persist should not run when xt connection is unavailable")
        ),
    )
    monkeypatch.setattr(
        "freshquant.initialize._bootstrap_order_ledger_from_synced_truth",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("rebuild should not run when xt connection is unavailable")
        ),
    )

    assert _default_xt_runtime_sync_runner() == {
        "assets": 0,
        "positions": 0,
        "orders": 0,
        "trades": 0,
        "rebuild": {
            "skipped": True,
            "reason": "xt_connection_unavailable",
        },
    }
