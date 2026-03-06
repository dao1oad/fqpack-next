import importlib
import types

import pytest

from app.core import database as app_database
from tradingagents.dataflows.cache import mongodb_cache_adapter as cache_module


def test_get_database_returns_initialized_mongo_db(monkeypatch):
    expected_db = object()

    monkeypatch.setattr(app_database.db_manager, "mongo_client", object())
    monkeypatch.setattr(app_database.db_manager, "mongo_db", expected_db)

    assert app_database.get_database() is expected_db


def test_mongodb_cache_adapter_uses_configured_database(monkeypatch):
    fake_db = object()

    class FakeClient:
        def __init__(self):
            self.requested = []

        def get_database(self, name=None):
            self.requested.append(name)
            return fake_db

    fake_client = FakeClient()

    monkeypatch.setenv("MONGODB_DATABASE", "tradingagents_cn")

    adapter = object.__new__(cache_module.MongoDBCacheAdapter)
    adapter.use_app_cache = True
    adapter.mongodb_client = None
    adapter.db = None

    fake_manager = types.SimpleNamespace(get_mongodb_client=lambda: fake_client)
    monkeypatch.setitem(importlib.sys.modules, "tradingagents.config.database_manager", fake_manager)

    cache_module.MongoDBCacheAdapter._init_mongodb_connection(adapter)

    assert fake_client.requested == ["tradingagents_cn"]
    assert adapter.db is fake_db
