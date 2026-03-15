import importlib

def test_order_management_db_uses_bootstrap_dedicated_database(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "order_management:",
                "  mongo_database: unit_test_order_management",
                "  projection_database: unit_test_projection",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as db_module
    import freshquant.order_management.db as om_db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    db_module = importlib.reload(db_module)
    om_db_module = importlib.reload(om_db_module)

    assert (
        bootstrap_module.bootstrap_config.order_management.mongo_database
        == "unit_test_order_management"
    )
    assert om_db_module.DBOrderManagement.name == "unit_test_order_management"
    assert om_db_module.DBOrderProjection.name == "unit_test_projection"
    assert db_module.get_db("order_management") == om_db_module.DBOrderManagement


def test_order_management_projection_db_defaults_to_bootstrap_mongodb_db(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "order_management:",
                "  mongo_database: freshquant_order_management",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.order_management.db as om_db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    om_db_module = importlib.reload(om_db_module)

    assert bootstrap_module.bootstrap_config.mongodb.db == "freshquant_runtime"
    assert om_db_module.DBOrderProjection.name == "freshquant_runtime"
    assert om_db_module.get_projection_db() == om_db_module.DBOrderProjection
