import importlib
import sys
import types
from datetime import datetime


class FakeMustPoolCollection:
    def __init__(self, existing=None):
        self.existing = dict(existing) if existing else None
        self.inserted = None
        self.updated = None

    def find_one(self, query):
        if self.existing and self.existing.get("code") == query.get("code"):
            return dict(self.existing)
        return None

    def insert_one(self, doc):
        self.inserted = dict(doc)
        self.existing = dict(doc)

    def update_one(self, query, update):
        self.updated = {"query": dict(query), "update": dict(update)}
        if self.existing and self.existing.get("_id") == query.get("_id"):
            next_doc = dict(self.existing)
            next_doc.update(dict(update.get("$set") or {}))
            self.existing = next_doc


def _import_must_pool_with_stubs(monkeypatch, *, collection=None):
    fake_db = types.SimpleNamespace(must_pool=collection or FakeMustPoolCollection())
    fake_db_module = types.ModuleType("freshquant.db")
    fake_db_module.DBfreshquant = fake_db

    fake_instrument_module = types.ModuleType("freshquant.instrument.general")
    fake_instrument_module.query_instrument_info = lambda code: {
        "name": f"name-{code}",
        "sec": "stock",
    }

    fake_strategy_common_module = types.ModuleType("freshquant.strategy.common")
    fake_strategy_common_module.get_trade_amount = lambda code: 50000

    fake_pyperclip_module = types.ModuleType("pyperclip")
    fake_pyperclip_module.copy = lambda text: None

    fake_bson_module = types.ModuleType("bson")
    fake_bson_module.ObjectId = lambda value: value

    monkeypatch.setitem(sys.modules, "freshquant.db", fake_db_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.general", fake_instrument_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.common", fake_strategy_common_module
    )
    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip_module)
    monkeypatch.setitem(sys.modules, "bson", fake_bson_module)

    import freshquant.data.astock.must_pool as must_pool

    return importlib.reload(must_pool)


def test_merge_provenance_preserves_manual_category_and_dedupes_memberships(
    monkeypatch,
):
    must_pool = _import_must_pool_with_stubs(monkeypatch)

    existing = {
        "code": "600001",
        "manual_category": "人工观察",
        "sources": ["legacy"],
        "categories": ["银行"],
        "memberships": [
            {
                "source": "legacy",
                "category": "银行",
                "added_at": datetime(2026, 3, 20, 9, 0),
                "extra": {"legacy": True},
            }
        ],
    }
    incoming = {
        "sources": ["shouban30"],
        "categories": ["plate:11"],
        "memberships": [
            {
                "source": "shouban30",
                "category": "plate:11",
                "added_at": datetime(2026, 3, 21, 9, 0),
                "extra": {"shouban30_order": 3},
            },
            {
                "source": "legacy",
                "category": "银行",
                "added_at": datetime(2026, 3, 22, 9, 0),
                "extra": {"legacy": False, "refreshed": True},
            },
        ],
    }

    merged = must_pool.merge_provenance(existing, incoming)

    assert merged["manual_category"] == "人工观察"
    assert merged["category"] == "人工观察"
    assert merged["sources"] == ["legacy", "shouban30"]
    assert merged["categories"] == ["plate:11", "银行"]
    assert {(item["source"], item["category"]) for item in merged["memberships"]} == {
        ("legacy", "银行"),
        ("shouban30", "plate:11"),
    }
    legacy_membership = next(
        item
        for item in merged["memberships"]
        if item["source"] == "legacy" and item["category"] == "银行"
    )
    assert legacy_membership["added_at"] == datetime(2026, 3, 20, 9, 0)
    assert legacy_membership["extra"] == {"legacy": False, "refreshed": True}


def test_merge_provenance_uses_primary_membership_when_manual_category_missing(
    monkeypatch,
):
    must_pool = _import_must_pool_with_stubs(monkeypatch)

    merged = must_pool.merge_provenance(
        {"category": ""},
        {
            "memberships": [
                {
                    "source": "daily-screening",
                    "category": "CLXS_10008",
                    "added_at": datetime(2026, 3, 20, 9, 0),
                    "extra": {},
                },
                {
                    "source": "shouban30",
                    "category": "plate:11",
                    "added_at": datetime(2026, 3, 20, 9, 1),
                    "extra": {},
                },
            ]
        },
    )

    assert merged["manual_category"] == ""
    assert merged["category"] == "plate:11"


def test_build_stock_pool_provenance_preserves_memberships_and_order_hint(
    monkeypatch,
):
    must_pool = _import_must_pool_with_stubs(monkeypatch)

    provenance = must_pool.build_stock_pool_provenance(
        {
            "category": "CLXS_10008",
            "sources": ["daily-screening", "shouban30"],
            "categories": ["CLXS_10008", "plate:11"],
            "memberships": [
                {
                    "source": "daily-screening",
                    "category": "CLXS_10008",
                    "added_at": datetime(2026, 3, 20, 9, 31),
                    "extra": {"screening_run_id": "run-1"},
                },
                {
                    "source": "shouban30",
                    "category": "plate:11",
                    "added_at": datetime(2026, 3, 20, 9, 35),
                    "extra": {"shouban30_plate_key": "11"},
                },
            ],
            "extra": {"shouban30_order": 7},
        }
    )

    assert provenance == {
        "sources": ["daily-screening", "shouban30"],
        "categories": ["CLXS_10008", "plate:11"],
        "memberships": [
            {
                "source": "daily-screening",
                "category": "CLXS_10008",
                "added_at": datetime(2026, 3, 20, 9, 31),
                "expire_at": None,
                "extra": {"screening_run_id": "run-1"},
            },
            {
                "source": "shouban30",
                "category": "plate:11",
                "added_at": datetime(2026, 3, 20, 9, 35),
                "expire_at": None,
                "extra": {"shouban30_plate_key": "11"},
            },
        ],
        "workspace_order_hint": 7,
    }


def test_import_pool_persists_provenance_for_new_doc(monkeypatch):
    collection = FakeMustPoolCollection()
    must_pool = _import_must_pool_with_stubs(monkeypatch, collection=collection)

    must_pool.import_pool(
        code="000001",
        category="CLXS_10008",
        stop_loss_price=9.2,
        initial_lot_amount=80000,
        lot_amount=50000,
        forever=True,
        provenance={
            "sources": ["daily-screening", "shouban30"],
            "categories": ["CLXS_10008", "plate:11"],
            "memberships": [
                {
                    "source": "daily-screening",
                    "category": "CLXS_10008",
                    "added_at": datetime(2026, 3, 20, 9, 31),
                    "extra": {"screening_run_id": "run-1"},
                },
                {
                    "source": "shouban30",
                    "category": "plate:11",
                    "added_at": datetime(2026, 3, 20, 9, 35),
                    "extra": {"shouban30_plate_key": "11"},
                },
            ],
            "workspace_order_hint": 7,
        },
    )

    assert collection.inserted is not None
    assert collection.inserted["code"] == "000001"
    assert collection.inserted["manual_category"] == ""
    assert collection.inserted["category"] == "CLXS_10008"
    assert collection.inserted["sources"] == ["daily-screening", "shouban30"]
    assert collection.inserted["categories"] == ["CLXS_10008", "plate:11"]
    assert collection.inserted["workspace_order_hint"] == 7
