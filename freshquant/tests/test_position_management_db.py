# -*- coding: utf-8 -*-

from freshquant.position_management.db import DEFAULT_POSITION_MANAGEMENT_DB
from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)
from freshquant.position_management.repository import PositionManagementRepository


def test_position_management_uses_dedicated_database():
    assert DEFAULT_POSITION_MANAGEMENT_DB == "freshquant_position_management"


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
