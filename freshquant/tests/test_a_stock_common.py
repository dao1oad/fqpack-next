from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace

import pendulum


class FakePrePoolCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def find_one_and_update(self, query: dict, update: dict, upsert: bool = False):
        existing = self.find_one(query)
        if existing is None:
            if not upsert:
                return None
            existing = dict(query)
            self.docs.append(existing)
            for key, value in update.get("$setOnInsert", {}).items():
                existing.setdefault(key, value)

        for key, value in update.get("$set", {}).items():
            existing[key] = value
        return existing


class FakeDB:
    def __init__(self) -> None:
        self.stock_pre_pools = FakePrePoolCollection()


def _import_a_stock_common_with_stubs(monkeypatch, fake_db: FakeDB):
    basic_module = types.ModuleType("freshquant.data.astock.basic")
    basic_module.fq_fetch_a_stock_category = lambda code: "stock"

    db_module = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = fake_db
    db_module.DBQuantAxis = SimpleNamespace()

    instrument_module = types.ModuleType("freshquant.instrument.general")
    instrument_module.query_instrument_info = lambda code: {"code": code, "name": "alpha"}

    holding_module = types.ModuleType("freshquant.data.astock.holding")
    holding_module.get_stock_holding_codes = lambda: []

    datetime_helper_module = types.ModuleType("freshquant.util.datetime_helper")
    datetime_helper_module.fq_util_datetime_localize = lambda value: value

    monkeypatch.setitem(sys.modules, "freshquant.data.astock.basic", basic_module)
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.general", instrument_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.data.astock.holding", holding_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.util.datetime_helper", datetime_helper_module
    )

    import freshquant.signal.a_stock_common as a_stock_common

    return importlib.reload(a_stock_common)


def test_save_a_stock_pre_pools_writes_top_level_remark(monkeypatch):
    fake_db = FakeDB()
    a_stock_common = _import_a_stock_common_with_stubs(monkeypatch, fake_db)

    a_stock_common.save_a_stock_pre_pools(
        code="000001",
        category="CLXS_10001",
        dt=pendulum.datetime(2026, 3, 17),
        remark="daily-screening:clxs",
        screening_run_id="run-1",
    )

    assert len(fake_db.stock_pre_pools.docs) == 1
    saved = fake_db.stock_pre_pools.docs[0]
    assert saved["code"] == "000001"
    assert saved["category"] == "CLXS_10001"
    assert saved["name"] == "alpha"
    assert saved["remark"] == "daily-screening:clxs"
    assert saved["extra"] == {"screening_run_id": "run-1"}
    assert saved["datetime"] == pendulum.datetime(
        2026, 3, 17, tz=pendulum.now().timezone
    )
    assert saved["expire_at"].date() == pendulum.now().add(days=89).date()


def test_save_a_stock_pre_pools_keeps_rows_isolated_by_remark(monkeypatch):
    fake_db = FakeDB()
    a_stock_common = _import_a_stock_common_with_stubs(monkeypatch, fake_db)

    a_stock_common.save_a_stock_pre_pools(
        code="000001",
        category="chanlun_service",
        dt=pendulum.datetime(2026, 3, 17),
        remark="daily-screening:clxs",
        screening_run_id="run-clxs",
    )
    a_stock_common.save_a_stock_pre_pools(
        code="000001",
        category="chanlun_service",
        dt=pendulum.datetime(2026, 3, 17),
        remark="daily-screening:chanlun",
        screening_run_id="run-chanlun",
    )

    assert len(fake_db.stock_pre_pools.docs) == 2
    assert {
        (doc["code"], doc["category"], doc.get("remark"))
        for doc in fake_db.stock_pre_pools.docs
    } == {
        ("000001", "chanlun_service", "daily-screening:clxs"),
        ("000001", "chanlun_service", "daily-screening:chanlun"),
    }
