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

    def get_config(self):
        document = self.configs.find_one({"enabled": True}, sort=[("updated_at", -1)])
        if document is not None:
            return document
        return self.configs.find_one({"code": "default"})

    def insert_snapshot(self, document):
        self.credit_asset_snapshots.insert_one(document)
        return document

    def upsert_current_state(self, document):
        account_id = document.get("account_id")
        query = {"account_id": account_id} if account_id else {"code": "default"}
        self.current_state.replace_one(query, document, upsert=True)
        return document

    def get_current_state(self, account_id=None):
        query = {"account_id": account_id} if account_id else {}
        return self.current_state.find_one(query, sort=[("evaluated_at", -1)])

    def insert_decision(self, document):
        self.strategy_decisions.insert_one(document)
        return document
