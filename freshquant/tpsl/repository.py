# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.order_management.db import DBOrderManagement


class TpslRepository:
    def __init__(self, database=None):
        self.database = database or DBOrderManagement

    @property
    def takeprofit_profiles(self):
        return self.database["om_takeprofit_profiles"]

    @property
    def takeprofit_states(self):
        return self.database["om_takeprofit_states"]

    @property
    def exit_trigger_events(self):
        return self.database["om_exit_trigger_events"]

    def find_takeprofit_profile(self, symbol):
        return self.takeprofit_profiles.find_one({"symbol": symbol})

    def upsert_takeprofit_profile(self, document):
        self.takeprofit_profiles.replace_one(
            {"symbol": document["symbol"]},
            document,
            upsert=True,
        )
        return self.find_takeprofit_profile(document["symbol"])

    def find_takeprofit_state(self, symbol):
        return self.takeprofit_states.find_one({"symbol": symbol})

    def upsert_takeprofit_state(self, document):
        self.takeprofit_states.replace_one(
            {"symbol": document["symbol"]},
            document,
            upsert=True,
        )
        return self.find_takeprofit_state(document["symbol"])

    def insert_exit_trigger_event(self, document):
        self.exit_trigger_events.insert_one(document)
        return document

    def list_exit_trigger_events(self, *, symbol=None, batch_id=None, limit=50):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if batch_id is not None:
            query["batch_id"] = batch_id
        cursor = self.exit_trigger_events.find(query).sort("created_at", -1)
        if limit is not None:
            cursor = cursor.limit(int(limit))
        return list(cursor)
