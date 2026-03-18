from __future__ import annotations

import importlib


def test_memory_runtime_config_reads_bootstrap_file(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "memory:",
                "  mongodb:",
                "    host: 10.0.0.7",
                "    port: 27028",
                "    db: fq_memory_bootstrap",
                "  cold_root: .memory/cold",
                "  artifact_root: artifacts/bootstrap-memory",
                "  reference_ref: upstream/release-main",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.runtime.memory.config as memory_config_module

    bootstrap_module = importlib.reload(bootstrap_module)
    memory_config_module = importlib.reload(memory_config_module)
    config = memory_config_module.MemoryRuntimeConfig.from_settings(
        repo_root=tmp_path / "repo",
        service_root=tmp_path / "service",
        environ={},
    )

    assert bootstrap_module.bootstrap_config.memory.mongodb.host == "10.0.0.7"
    assert config.mongo_host == "10.0.0.7"
    assert config.mongo_port == 27028
    assert config.mongo_db == "fq_memory_bootstrap"
    assert config.cold_memory_root.as_posix().endswith(".memory/cold")
    assert config.artifact_root.as_posix().endswith("artifacts/bootstrap-memory")
    assert config.reference_ref == "upstream/release-main"
