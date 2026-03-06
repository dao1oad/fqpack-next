import importlib

from freshquant.config import settings


def test_order_management_db_uses_dedicated_database(monkeypatch):
    monkeypatch.setenv(
        "FRESHQUANT_ORDER_MANAGEMENT__MONGO_DATABASE",
        "unit_test_order_management",
    )
    settings.reload()

    try:
        import freshquant.db as db_module
        import freshquant.order_management.db as om_db_module

        db_module = importlib.reload(db_module)
        om_db_module = importlib.reload(om_db_module)

        assert om_db_module.DBOrderManagement.name == "unit_test_order_management"
        assert db_module.get_db("order_management") == om_db_module.DBOrderManagement
    finally:
        monkeypatch.delenv(
            "FRESHQUANT_ORDER_MANAGEMENT__MONGO_DATABASE",
            raising=False,
        )
        settings.reload()


def test_order_management_projection_db_defaults_to_freshquant(monkeypatch):
    monkeypatch.delenv(
        "FRESHQUANT_ORDER_MANAGEMENT__PROJECTION_DATABASE",
        raising=False,
    )
    settings.reload()

    try:
        import freshquant.order_management.db as om_db_module

        om_db_module = importlib.reload(om_db_module)

        assert om_db_module.DBOrderProjection.name == "freshquant"
        assert om_db_module.get_projection_db() == om_db_module.DBOrderProjection
    finally:
        settings.reload()
