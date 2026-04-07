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

    def find_one(self, _query=None):
        return self.documents[0] if self.documents else None

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

        def query_stock_orders(self, account):
            query_calls.append(("orders", account.account_id))
            return [
                SimpleNamespace(
                    account_id=account.account_id,
                    stock_code="000001.SZ",
                    order_id="order-1",
                    order_sysid="sys-1",
                    order_time=1710000000,
                    order_type=23,
                    order_volume=100,
                    price_type=11,
                    price=12.5,
                    traded_volume=100,
                    traded_price=12.5,
                    order_status=56,
                    status_msg="filled",
                    strategy_name="Guardian",
                    order_remark="bootstrap",
                )
            ]

        def query_stock_trades(self, account):
            query_calls.append(("trades", account.account_id))
            return [
                SimpleNamespace(
                    account_id=account.account_id,
                    order_type=23,
                    stock_code="000001.SZ",
                    traded_id="trade-1",
                    traded_time=1710000001,
                    traded_price=12.5,
                    traded_volume=100,
                    traded_amount=1250.0,
                    order_id="order-1",
                    order_sysid="sys-1",
                    strategy_name="Guardian",
                    order_remark="bootstrap",
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
        ("orders", "068000076370"),
        ("trades", "068000076370"),
    ]
    assert persisted_truth["account_id"] == "068000076370"
    assert persisted_truth["positions"][0]["avg_price"] == 12.5
    assert persisted_truth["orders"][0]["order_id"] == "order-1"
    assert persisted_truth["trades"][0]["traded_id"] == "trade-1"
    assert rebuild_calls == [
        {
            "xt_orders": persisted_truth["orders"],
            "xt_trades": persisted_truth["trades"],
            "xt_positions": persisted_truth["positions"],
        }
    ]
    assert summary == {
        "assets": 1,
        "positions": 1,
        "orders": 1,
        "trades": 1,
        "rebuild": {
            "skipped": False,
            "position_entries": 1,
            "auto_open_entries": 1,
        },
    }


def test_bootstrap_order_ledger_from_synced_truth_writes_rebuild_result_when_empty():
    from freshquant.initialize import _bootstrap_order_ledger_from_synced_truth

    database = FakeDatabase()

    class FakeRebuildService:
        def build_from_truth(self, *, xt_orders, xt_trades, xt_positions):
            assert xt_orders == [{"order_id": "order-1"}]
            assert xt_trades == [{"traded_id": "trade-1"}]
            assert xt_positions == [{"stock_code": "000001.SZ", "avg_price": 12.5}]
            return {
                "broker_orders": 1,
                "execution_fills": 1,
                "position_entries": 1,
                "entry_slices": 1,
                "exit_allocations": 0,
                "reconciliation_gaps": 0,
                "reconciliation_resolutions": 1,
                "auto_open_entries": 1,
                "auto_close_allocations": 0,
                "ingest_rejections": 0,
                "broker_order_documents": [{"broker_order_key": "broker-order-1"}],
                "execution_fill_documents": [{"execution_fill_id": "fill-1"}],
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
        xt_orders=[{"order_id": "order-1"}],
        xt_trades=[{"traded_id": "trade-1"}],
        xt_positions=[{"stock_code": "000001.SZ", "avg_price": 12.5}],
        database=database,
        rebuild_service=FakeRebuildService(),
    )

    assert summary == {
        "skipped": False,
        "broker_orders": 1,
        "execution_fills": 1,
        "position_entries": 1,
        "entry_slices": 1,
        "exit_allocations": 0,
        "reconciliation_gaps": 0,
        "reconciliation_resolutions": 1,
        "auto_open_entries": 1,
        "auto_close_allocations": 0,
        "ingest_rejections": 0,
    }
    assert database["om_broker_orders"].documents == [
        {"broker_order_key": "broker-order-1"}
    ]
    assert database["om_position_entries"].documents == [{"entry_id": "entry-1"}]
    assert database["om_reconciliation_resolutions"].documents == [
        {"resolution_id": "resolution-1"}
    ]


def test_bootstrap_order_ledger_from_synced_truth_skips_when_order_ledger_not_empty():
    from freshquant.initialize import _bootstrap_order_ledger_from_synced_truth

    database = FakeDatabase({"om_position_entries": [{"entry_id": "existing-entry"}]})

    class FailingRebuildService:
        def build_from_truth(self, **kwargs):
            raise AssertionError("rebuild should be skipped when ledger is not empty")

    summary = _bootstrap_order_ledger_from_synced_truth(
        xt_orders=[],
        xt_trades=[],
        xt_positions=[],
        database=database,
        rebuild_service=FailingRebuildService(),
    )

    assert summary == {
        "skipped": True,
        "reason": "order_ledger_not_empty",
    }
