from __future__ import annotations

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
                    "stock": {"periods": ["1min", "5min"]},
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
                        "position_pct": 31,
                        "auto_open": True,
                        "lot_amount": 1800,
                        "min_amount": 1200,
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


def test_run_runtime_bootstrap_syncs_xt_credit_subjects_and_instrument_strategy_defaults():
    from freshquant.initialize import run_runtime_bootstrap

    instrument_strategy_calls = []

    summary = run_runtime_bootstrap(
        settings_provider=SimpleNamespace(
            monitor=SimpleNamespace(xtdata_mode="guardian_1m", xtdata_max_symbols=20),
            get_strategy_id=lambda code: "guardian_strategy_id" if code == "Guardian" else "",
        ),
        xt_runtime_sync_runner=lambda: {
            "assets": 1,
            "positions": 2,
            "orders": 3,
            "trades": 4,
        },
        credit_subject_sync_runner=lambda: {"count": 5},
        monitor_code_loader=lambda mode, max_symbols: ["sz000001", "sh510050"],
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
    assert instrument_strategy_calls == [
        ("000001.SZ", "stock", "guardian_strategy_id"),
        ("510050.SH", "etf", "guardian_strategy_id"),
    ]
