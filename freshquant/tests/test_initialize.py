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
    sync_calls = []
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

    def fake_connect(session_id=100):
        connect_calls.append(session_id)
        return "xt-trader", SimpleNamespace(account_id="068000076370"), True

    broker_module.connect = fake_connect
    broker_module.trading_manager = fake_manager
    monkeypatch.setitem(
        sys.modules,
        "morningglory.fqxtrade.fqxtrade.xtquant.broker",
        broker_module,
    )

    puppet_module = types.ModuleType("morningglory.fqxtrade.fqxtrade.xtquant.puppet")

    def sync_summary():
        sync_calls.append("summary")
        assert connection_state["connected"] is True
        return {"account_id": "068000076370"}

    def sync_positions():
        sync_calls.append("positions")
        assert connection_state["connected"] is True
        return [{"stock_code": "000001.SZ"}]

    def sync_orders():
        sync_calls.append("orders")
        assert connection_state["connected"] is True
        return [{"order_id": "order-1"}]

    def sync_trades():
        sync_calls.append("trades")
        assert connection_state["connected"] is True
        return [{"traded_id": "trade-1"}]

    puppet_module.sync_summary = sync_summary
    puppet_module.sync_positions = sync_positions
    puppet_module.sync_orders = sync_orders
    puppet_module.sync_trades = sync_trades
    monkeypatch.setitem(
        sys.modules,
        "morningglory.fqxtrade.fqxtrade.xtquant.puppet",
        puppet_module,
    )

    summary = _default_xt_runtime_sync_runner()

    assert connect_calls == [100]
    assert sync_calls == ["summary", "positions", "orders", "trades"]
    assert summary == {
        "assets": 1,
        "positions": 1,
        "orders": 1,
        "trades": 1,
    }
