# -*- coding: utf-8 -*-

from freshquant.position_management.db import DBPositionManagement


class PositionManagementRepository:
    config_collection_name = "pm_configs"
    snapshot_collection_name = "pm_credit_asset_snapshots"
    current_state_collection_name = "pm_current_state"
    decision_collection_name = "pm_strategy_decisions"
    symbol_snapshot_collection_name = "pm_symbol_position_snapshots"

    def __init__(self, database=None):
        self.database = database if database is not None else DBPositionManagement

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

    @property
    def symbol_position_snapshots(self):
        return self.database[self.symbol_snapshot_collection_name]

    def get_config(self):
        document = self.configs.find_one({"enabled": True}, sort=[("updated_at", -1)])
        if document is not None:
            return document
        return self.configs.find_one({"code": "default"})

    def upsert_config(self, document):
        payload = dict(document or {})
        payload.pop("_id", None)
        code = str(payload.get("code") or "default").strip() or "default"
        payload["code"] = code
        self.configs.update_one({"code": code}, {"$set": payload}, upsert=True)
        return self.get_config() or payload

    def insert_snapshot(self, document):
        self.credit_asset_snapshots.insert_one(document)
        return document

    def get_snapshot(self, snapshot_id):
        if not snapshot_id:
            return None
        return self.credit_asset_snapshots.find_one({"snapshot_id": snapshot_id})

    def get_latest_snapshot(self):
        return self.credit_asset_snapshots.find_one(sort=[("queried_at", -1)])

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

    def list_recent_decisions(self, limit=10):
        try:
            resolved_limit = max(int(limit), 0)
        except (TypeError, ValueError):
            resolved_limit = 10
        cursor = self.strategy_decisions.find().sort([("evaluated_at", -1)])
        if resolved_limit > 0:
            cursor = cursor.limit(resolved_limit)
        return list(cursor)

    def upsert_symbol_snapshot(self, document):
        payload = dict(document or {})
        payload.pop("_id", None)
        symbol = str(payload.get("symbol") or "").strip()
        if not symbol:
            raise ValueError("symbol snapshot requires symbol")
        payload["symbol"] = symbol
        self.symbol_position_snapshots.update_one(
            {"symbol": symbol},
            {"$set": payload},
            upsert=True,
        )
        return self.get_symbol_snapshot(symbol) or payload

    def get_symbol_snapshot(self, symbol):
        normalized_symbol = str(symbol or "").strip()
        if not normalized_symbol:
            return None
        return self.symbol_position_snapshots.find_one({"symbol": normalized_symbol})

    def list_symbol_snapshots(self, symbols=None):
        query = {}
        if symbols:
            query["symbol"] = {
                "$in": [
                    str(item).strip() for item in list(symbols) if str(item).strip()
                ]
            }
        cursor = self.symbol_position_snapshots.find(query).sort([("symbol", 1)])
        return list(cursor)

    def delete_symbol_snapshots_missing_symbols(self, symbols):
        normalized_symbols = [
            str(item).strip() for item in list(symbols or []) if str(item).strip()
        ]
        query = {"symbol": {"$nin": normalized_symbols}} if normalized_symbols else {}
        return self.symbol_position_snapshots.delete_many(query)
