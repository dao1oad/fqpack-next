# -*- coding: utf-8 -*-

from freshquant.position_management.db import DBPositionManagement


class PositionManagementRepository:
    config_collection_name = "pm_configs"
    snapshot_collection_name = "pm_credit_asset_snapshots"
    current_state_collection_name = "pm_current_state"
    decision_collection_name = "pm_strategy_decisions"

    def __init__(self, database=None):
        self.database = database or DBPositionManagement

    @property
    def configs(self):
        return self.database[self.config_collection_name]

    @property
    def credit_asset_snapshots(self):
        return self.database[self.snapshot_collection_name]

    @property
    def current_state(self):
        return self.database[self.current_state_collection_name]

    @property
    def strategy_decisions(self):
        return self.database[self.decision_collection_name]
