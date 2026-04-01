from __future__ import annotations

from copy import deepcopy

import base62
from bson import ObjectId


class FakeUpdateResult:
    def __init__(self, upserted_id=None):
        self.upserted_id = upserted_id


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [deepcopy(item) for item in (documents or [])]

    def find_one(self, query=None, sort=None):
        query = query or {}
        matched = [doc for doc in self.documents if self._matches(doc, query)]
        if not matched:
            return None
        if sort:
            field, direction = sort[0]
            matched.sort(
                key=lambda item: item.get(field, 0),
                reverse=int(direction) < 0,
            )
        return deepcopy(matched[0])

    def update_one(self, query, update, upsert=False):
        for index, document in enumerate(self.documents):
            if self._matches(document, query):
                updated = deepcopy(document)
                for key, value in update.get("$set", {}).items():
                    updated[key] = deepcopy(value)
                for key, value in update.get("$setOnInsert", {}).items():
                    updated.setdefault(key, deepcopy(value))
                self.documents[index] = updated
                return FakeUpdateResult()
        if not upsert:
            return FakeUpdateResult()
        document = deepcopy(query)
        document.setdefault("_id", ObjectId())
        for key, value in update.get("$setOnInsert", {}).items():
            document[key] = deepcopy(value)
        for key, value in update.get("$set", {}).items():
            document[key] = deepcopy(value)
        self.documents.append(document)
        return FakeUpdateResult(upserted_id=document["_id"])

    @staticmethod
    def _matches(document, query):
        for key, value in query.items():
            if document.get(key) != value:
                return False
        return True


class FakeDatabase:
    def __init__(self, collections):
        self.collections = {
            name: FakeCollection(documents) for name, documents in collections.items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


class BrokenDatabase:
    def __getitem__(self, name):
        raise RuntimeError(f"database unavailable: {name}")


def test_system_settings_reads_runtime_values_and_pm_thresholds():
    from freshquant.system_settings import SystemSettings

    database = FakeDatabase(
        {
            "params": [
                {
                    "code": "notification",
                    "value": {
                        "webhook": {
                            "dingtalk": {
                                "private": "https://private.example",
                                "public": "https://public.example",
                            }
                        }
                    },
                },
                {
                    "code": "monitor",
                    "value": {
                        "xtdata": {
                            "mode": "guardian_1m",
                            "max_symbols": 48,
                            "queue_backlog_threshold": 200,
                            "prewarm": {"max_bars": 120},
                        },
                    },
                },
                {
                    "code": "xtquant",
                    "value": {
                        "path": "D:/miniqmt/userdata_mini",
                        "account": "068000076370",
                        "account_type": "CREDIT",
                        "broker_submit_mode": "observe_only",
                    },
                },
                {
                    "code": "guardian",
                    "value": {
                        "stock": {
                            "lot_amount": 1800,
                            "threshold": {"mode": "atr", "atr": {"period": 14}},
                            "grid_interval": {"mode": "percent", "percent": 3},
                        }
                    },
                },
            ],
            "pm_configs": [
                {
                    "code": "default",
                    "enabled": True,
                    "thresholds": {
                        "allow_open_min_bail": 900000.0,
                        "holding_only_min_bail": 300000.0,
                        "single_symbol_position_limit": 950000.0,
                    },
                }
            ],
            "instrument_strategy": [
                {
                    "instrument_code": "002594.SZ",
                    "strategy_name": "g8txDZY5cclM7zbo",
                    "lot_amount": 1500,
                    "threshold": {"mode": "percent", "percent": 1},
                }
            ],
        }
    )

    settings = SystemSettings(database=database)

    assert settings.notification.dingtalk_private_webhook == "https://private.example"
    assert settings.notification.dingtalk_public_webhook == "https://public.example"
    assert settings.monitor.xtdata_mode == "guardian_1m"
    assert settings.monitor.xtdata_max_symbols == 48
    assert settings.monitor.xtdata_queue_backlog_threshold == 200
    assert settings.monitor.xtdata_prewarm_max_bars == 120
    assert settings.xtquant.path == "D:/miniqmt/userdata_mini"
    assert settings.xtquant.account == "068000076370"
    assert settings.xtquant.account_type == "CREDIT"
    assert settings.xtquant.broker_submit_mode == "observe_only"
    assert settings.guardian.stock_lot_amount == 1800
    assert settings.guardian.stock_threshold == {
        "mode": "atr",
        "atr": {"period": 14},
    }
    assert settings.guardian.stock_grid_interval == {
        "mode": "percent",
        "percent": 3,
    }
    assert settings.position_management.allow_open_min_bail == 900000.0
    assert settings.position_management.holding_only_min_bail == 300000.0
    assert settings.position_management.single_symbol_position_limit == 950000.0
    assert settings.get_instrument_strategy("002594.SZ") == {
        "instrument_code": "002594.SZ",
        "strategy_name": "g8txDZY5cclM7zbo",
        "lot_amount": 1500,
        "threshold": {"mode": "percent", "percent": 1},
    }


def test_system_settings_normalizes_legacy_clx_mode_to_combined_mode():
    from freshquant.system_settings import SystemSettings

    database = FakeDatabase(
        {
            "params": [
                {
                    "code": "monitor",
                    "value": {
                        "xtdata": {
                            "mode": "clx_15_30",
                            "max_symbols": 48,
                            "queue_backlog_threshold": 200,
                            "prewarm": {"max_bars": 120},
                        },
                    },
                },
            ],
            "pm_configs": [],
            "instrument_strategy": [],
        }
    )

    settings = SystemSettings(database=database)

    assert settings.monitor.xtdata_mode == "guardian_and_clx_15_30"


def test_system_settings_ensure_defaults_and_strategy_lookup():
    from freshquant.system_settings import SystemSettings

    guardian_id = ObjectId("65f000000000000000000001")
    database = FakeDatabase(
        {
            "params": [],
            "strategies": [
                {"_id": guardian_id, "code": "Guardian", "name": "守护者策略"},
            ],
            "pm_configs": [],
            "instrument_strategy": [],
        }
    )

    settings = SystemSettings(database=database)
    settings.ensure_default_documents()

    expected_b62 = base62.encodebytes(guardian_id.binary)

    assert settings.get_strategy_id("Guardian") == expected_b62
    assert database["strategies"].find_one({"code": "Guardian"})["b62_uid"] == (
        expected_b62
    )
    assert database["strategies"].find_one({"code": "Manual"}) is not None
    assert database["params"].find_one({"code": "xtquant"}) is not None
    assert database["params"].find_one({"code": "monitor"}) is not None
    assert database["params"].find_one({"code": "guardian"}) is not None
    assert database["pm_configs"].find_one({"code": "default"}) is not None


def test_system_settings_falls_back_to_defaults_when_database_unavailable():
    from freshquant.system_settings import SystemSettings

    settings = SystemSettings(database=BrokenDatabase())

    assert settings.notification.dingtalk_private_webhook == ""
    assert settings.monitor.xtdata_mode == "guardian_1m"
    assert settings.xtquant.account == ""
    assert settings.guardian.stock_lot_amount == 50000
    assert settings.guardian.stock_threshold == {
        "mode": "percent",
        "percent": 1,
    }
    assert settings.position_management.allow_open_min_bail == 800000.0
    assert settings.get_strategy_id("Guardian") == ""
