# -*- coding: utf-8 -*-

import importlib

from freshquant.position_management.db import DEFAULT_POSITION_MANAGEMENT_DB
from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.repository import PositionManagementRepository


def test_position_management_uses_dedicated_database():
    assert DEFAULT_POSITION_MANAGEMENT_DB == "freshquant_position_management"


def test_position_management_db_uses_bootstrap_dedicated_database(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "position_management:",
                "  mongo_database: unit_test_position_management",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.position_management.db as pm_db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    pm_db_module = importlib.reload(pm_db_module)

    assert (
        bootstrap_module.bootstrap_config.position_management.mongo_database
        == "unit_test_position_management"
    )
    assert pm_db_module.DBPositionManagement.name == "unit_test_position_management"
    assert (
        pm_db_module.get_position_management_db() == pm_db_module.DBPositionManagement
    )


def test_repository_exposes_expected_collection_names():
    repository = PositionManagementRepository(database={})

    assert repository.config_collection_name == "pm_configs"
    assert repository.snapshot_collection_name == "pm_credit_asset_snapshots"
    assert repository.current_state_collection_name == "pm_current_state"
    assert repository.decision_collection_name == "pm_strategy_decisions"


def test_models_export_expected_states():
    assert ALLOW_OPEN == "ALLOW_OPEN"
    assert HOLDING_ONLY == "HOLDING_ONLY"
    assert FORCE_PROFIT_REDUCE == "FORCE_PROFIT_REDUCE"
