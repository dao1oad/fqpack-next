# -*- coding: utf-8 -*-

from freshquant.position_management.db import DBPositionManagement


class XtAutoRepayRepository:
    state_collection_name = "xt_auto_repay_state"
    event_collection_name = "xt_auto_repay_events"
    credit_snapshot_collection_name = "pm_credit_asset_snapshots"

    def __init__(self, database=None):
        self.database = database if database is not None else DBPositionManagement

    @property
    def state(self):
        return self.database[self.state_collection_name]

    @property
    def events(self):
        return self.database[self.event_collection_name]

    @property
    def credit_snapshots(self):
        return self.database[self.credit_snapshot_collection_name]

    def get_latest_credit_snapshot(self, account_id=None):
        query = _account_query(account_id)
        return self.credit_snapshots.find_one(query, sort=[("queried_at", -1)])

    def get_state(self, account_id=None):
        query = _account_query(account_id)
        return self.state.find_one(query, sort=[("updated_at", -1)])

    def upsert_state(self, document):
        payload = dict(document or {})
        payload.pop("_id", None)
        account_id = str(payload.get("account_id") or "").strip()
        if not account_id:
            raise ValueError("xt auto repay state requires account_id")
        payload["account_id"] = account_id
        self.state.replace_one({"account_id": account_id}, payload, upsert=True)
        return dict(payload)

    def insert_event(self, document):
        payload = dict(document or {})
        payload.pop("_id", None)
        self.events.insert_one(payload)
        return dict(payload)


def _account_query(account_id):
    normalized_account_id = str(account_id or "").strip()
    if not normalized_account_id:
        return {}
    return {"account_id": normalized_account_id}
