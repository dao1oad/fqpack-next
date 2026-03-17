from __future__ import annotations

import importlib


def test_db_module_exposes_screening_database(monkeypatch, tmp_path):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "  screening_db: unit_test_screening_db",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    db_module = importlib.reload(db_module)

    assert bootstrap_module.bootstrap_config.mongodb.screening_db == (
        "unit_test_screening_db"
    )
    assert db_module.DBScreening.name == "unit_test_screening_db"
    assert db_module.get_db("screening") is db_module.DBScreening
    assert db_module.get_db("unit_test_screening_db") is db_module.DBScreening
