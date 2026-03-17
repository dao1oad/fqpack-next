from __future__ import annotations

import importlib
from pathlib import Path


def test_load_bootstrap_config_reads_yaml_and_env_override(monkeypatch, tmp_path):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 10.0.0.2",
                "  port: 27027",
                "  db: freshquant_runtime",
                "  gantt_db: freshquant_gantt_runtime",
                "redis:",
                "  host: 10.0.0.3",
                "  port: 6380",
                "  db: 1",
                "memory:",
                "  mongodb:",
                "    host: 10.0.0.4",
                "    port: 27028",
                "    db: fq_memory_runtime",
                "  cold_root: D:/fqpack/runtime/memory",
                "  artifact_root: D:/fqpack/runtime/artifacts",
                "order_management:",
                "  mongo_database: freshquant_order_management_runtime",
                "  projection_database: freshquant_runtime",
                "position_management:",
                "  mongo_database: freshquant_position_management_runtime",
                "tdx:",
                "  home: D:/tdx_biduan",
                "  hq:",
                "    endpoint: http://127.0.0.1:15001",
                "api:",
                "  base_url: http://127.0.0.1:15000",
                "xtdata:",
                "  port: 58611",
                "runtime:",
                "  log_dir: D:/fqpack/logs/runtime",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))
    monkeypatch.setenv("FRESHQUANT_MONGODB__PORT", "27099")
    monkeypatch.setenv("FRESHQUANT_RUNTIME__LOG_DIR", "D:/override/runtime")

    import freshquant.bootstrap_config as bootstrap_module

    bootstrap_module = importlib.reload(bootstrap_module)
    config = bootstrap_module.load_bootstrap_config()

    assert config.mongodb.host == "10.0.0.2"
    assert config.mongodb.port == 27099
    assert config.mongodb.db == "freshquant_runtime"
    assert config.mongodb.gantt_db == "freshquant_gantt_runtime"
    assert config.redis.port == 6380
    assert config.memory.mongodb.db == "fq_memory_runtime"
    assert config.order_management.mongo_database == (
        "freshquant_order_management_runtime"
    )
    assert config.position_management.mongo_database == (
        "freshquant_position_management_runtime"
    )
    assert config.tdx.home == "D:/tdx_biduan"
    assert config.tdx.hq_endpoint == "http://127.0.0.1:15001"
    assert config.api.base_url == "http://127.0.0.1:15000"
    assert config.xtdata.port == 58611
    assert config.runtime.log_dir == "D:/override/runtime"


def test_reload_bootstrap_config_refreshes_global_snapshot(monkeypatch, tmp_path):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "runtime:",
                "  log_dir: D:/fqpack/logs/runtime-a",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module

    bootstrap_module = importlib.reload(bootstrap_module)
    assert bootstrap_module.bootstrap_config.runtime.log_dir == (
        "D:/fqpack/logs/runtime-a"
    )

    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "runtime:",
                "  log_dir: D:/fqpack/logs/runtime-b",
            ]
        ),
        encoding="utf-8",
    )

    config = bootstrap_module.reload_bootstrap_config()

    assert config.runtime.log_dir == "D:/fqpack/logs/runtime-b"
    assert bootstrap_module.bootstrap_config.runtime.log_dir == (
        "D:/fqpack/logs/runtime-b"
    )


def test_load_bootstrap_config_reads_screening_db(monkeypatch, tmp_path):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "  gantt_db: freshquant_gantt_runtime",
                "  screening_db: fqscreening_runtime",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import importlib
    import freshquant.bootstrap_config as bootstrap_module

    bootstrap_module = importlib.reload(bootstrap_module)
    config = bootstrap_module.load_bootstrap_config()
    assert config.mongodb.screening_db == "fqscreening_runtime"
