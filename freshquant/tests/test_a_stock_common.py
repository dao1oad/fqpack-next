from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace
from typing import Any

import pendulum


class FakePrePoolCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def _match(self, doc: dict, query: dict) -> bool:
        for key, value in query.items():
            if key == "$or":
                if not any(self._match(doc, item) for item in value):
                    return False
                continue

            if isinstance(value, dict) and "$exists" in value:
                exists = key in doc
                if exists != value["$exists"]:
                    return False
                continue

            if doc.get(key) != value:
                return False

        return True

    def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if self._match(doc, query):
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


class FakeStockPoolCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def insert_one(self, document: dict):
        self.docs.append(dict(document))
        return SimpleNamespace(acknowledged=True)

    def update_one(self, query: dict, update: dict):
        doc = self.find_one(query)
        if doc is None:
            return SimpleNamespace(acknowledged=False)
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        return SimpleNamespace(acknowledged=True)


class FakeDB:
    def __init__(self) -> None:
        self.stock_pre_pools = FakePrePoolCollection()
        self.stock_pools = FakeStockPoolCollection()


def _import_a_stock_common_with_stubs(monkeypatch, fake_db: FakeDB):
    basic_module: Any = types.ModuleType("freshquant.data.astock.basic")
    basic_module.fq_fetch_a_stock_category = lambda code: "stock"

    db_module: Any = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = fake_db
    db_module.DBQuantAxis = SimpleNamespace()

    instrument_module: Any = types.ModuleType("freshquant.instrument.general")
    instrument_module.query_instrument_info = lambda code: {
        "code": code,
        "name": "alpha",
    }

    holding_module: Any = types.ModuleType("freshquant.data.astock.holding")
    holding_module.get_stock_holding_codes = lambda: []

    datetime_helper_module: Any = types.ModuleType("freshquant.util.datetime_helper")
    datetime_helper_module.fq_util_datetime_localize = lambda value: value

    monkeypatch.setitem(sys.modules, "freshquant.data.astock.basic", basic_module)
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)
    monkeypatch.setitem(sys.modules, "freshquant.instrument.general", instrument_module)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.holding", holding_module)
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


def test_save_a_stock_pre_pools_without_remark_does_not_overwrite_remark_rows(
    monkeypatch,
):
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
        dt=pendulum.datetime(2026, 3, 18),
        screening_run_id="legacy-run",
    )

    assert len(fake_db.stock_pre_pools.docs) == 2
    docs_by_remark = {
        doc.get("remark"): {
            "code": doc["code"],
            "category": doc["category"],
            "extra": doc["extra"],
        }
        for doc in fake_db.stock_pre_pools.docs
    }
    assert docs_by_remark == {
        "daily-screening:clxs": {
            "code": "000001",
            "category": "chanlun_service",
            "extra": {"screening_run_id": "run-clxs"},
        },
        None: {
            "code": "000001",
            "category": "chanlun_service",
            "extra": {"screening_run_id": "legacy-run"},
        },
    }


def test_save_a_stock_pools_persists_pre_pool_provenance_top_level(monkeypatch):
    fake_db = FakeDB()
    a_stock_common = _import_a_stock_common_with_stubs(monkeypatch, fake_db)

    added_at = pendulum.datetime(2026, 3, 20, 9, 31)
    expire_at = pendulum.datetime(2026, 4, 20, 0, 0)
    memberships = [
        {
            "source": "daily-screening",
            "category": "CLXS_10008",
            "added_at": added_at,
            "expire_at": expire_at,
            "extra": {"screening_run_id": "run-1"},
        },
        {
            "source": "shouban30",
            "category": "plate:11",
            "added_at": added_at,
            "expire_at": None,
            "extra": {"shouban30_plate_key": "11"},
        },
    ]

    a_stock_common.save_a_stock_pools(
        code="000001",
        category="自选股",
        dt=added_at,
        expire_at=expire_at,
        stop_loss_price=9.8,
        screening_source="daily-screening:clxs",
        sources=["daily-screening", "shouban30"],
        categories=["CLXS_10008", "plate:11"],
        memberships=memberships,
    )

    assert len(fake_db.stock_pools.docs) == 1
    saved = fake_db.stock_pools.docs[0]
    assert saved["sources"] == ["daily-screening", "shouban30"]
    assert saved["categories"] == ["CLXS_10008", "plate:11"]
    assert saved["memberships"] == memberships
    assert saved["extra"] == {"screening_source": "daily-screening:clxs"}


def test_save_a_stock_pools_merges_pre_pool_provenance_for_existing_doc(monkeypatch):
    fake_db = FakeDB()
    fake_db.stock_pools.docs.append(
        {
            "code": "000001",
            "category": "自选股",
            "name": "alpha",
            "datetime": pendulum.datetime(2026, 3, 19, 0, 0),
            "expire_at": pendulum.datetime(2026, 4, 19, 0, 0),
            "stop_loss_price": None,
            "extra": {"screening_source": "daily-screening:clxs"},
            "sources": ["daily-screening"],
            "categories": ["CLXS_10008"],
            "memberships": [
                {
                    "source": "daily-screening",
                    "category": "CLXS_10008",
                    "added_at": pendulum.datetime(2026, 3, 19, 0, 0),
                    "expire_at": pendulum.datetime(2026, 4, 19, 0, 0),
                    "extra": {"screening_run_id": "run-1"},
                }
            ],
        }
    )
    a_stock_common = _import_a_stock_common_with_stubs(monkeypatch, fake_db)

    a_stock_common.save_a_stock_pools(
        code="000001",
        category="自选股",
        dt=pendulum.datetime(2026, 3, 20, 9, 31),
        expire_at=pendulum.datetime(2026, 4, 20, 0, 0),
        stop_loss_price=9.8,
        shouban30_source="pre_pool",
        sources=["shouban30"],
        categories=["plate:11"],
        memberships=[
            {
                "source": "shouban30",
                "category": "plate:11",
                "added_at": pendulum.datetime(2026, 3, 20, 9, 31),
                "expire_at": None,
                "extra": {"shouban30_plate_key": "11"},
            }
        ],
    )

    saved = fake_db.stock_pools.docs[0]
    assert saved["sources"] == ["daily-screening", "shouban30"]
    assert saved["categories"] == ["CLXS_10008", "plate:11"]
    assert {(item["source"], item["category"]) for item in saved["memberships"]} == {
        ("daily-screening", "CLXS_10008"),
        ("shouban30", "plate:11"),
    }
    assert saved["extra"] == {
        "screening_source": "daily-screening:clxs",
        "shouban30_source": "pre_pool",
    }
