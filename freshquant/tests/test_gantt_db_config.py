import importlib


def test_get_gantt_db_uses_bootstrap_mongodb_gantt_db(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant",
                "  gantt_db: unit_test_gantt_db",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    db_module = importlib.reload(db_module)

    assert bootstrap_module.bootstrap_config.mongodb.gantt_db == "unit_test_gantt_db"
    assert db_module.DBGantt.name == "unit_test_gantt_db"
    assert db_module.get_db("gantt") == db_module.DBGantt
