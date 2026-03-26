import importlib
import sys
import types
from typing import Any

import pytest
import freshquant.instrument as instrument_package

SubjectManagementWriteService = None


@pytest.fixture(autouse=True)
def _install_write_service_stubs(monkeypatch):
    global SubjectManagementWriteService

    code_module: Any = types.ModuleType("freshquant.util.code")
    code_module.normalize_to_base_code = (
        lambda value: str(value or "").strip().split(".")[0]
    )
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_module)

    db_module: Any = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = {}
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)

    strategy_common_module: Any = types.ModuleType("freshquant.strategy.common")
    strategy_common_module.get_trade_amount = lambda code: 50000
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.common", strategy_common_module
    )

    instrument_module: Any = types.ModuleType("freshquant.instrument.general")
    instrument_module.query_instrument_info = lambda symbol: None
    monkeypatch.setitem(sys.modules, "freshquant.instrument.general", instrument_module)
    monkeypatch.setattr(instrument_package, "general", instrument_module, raising=False)

    monkeypatch.delitem(sys.modules, "freshquant.data.astock.must_pool", raising=False)
    monkeypatch.delitem(
        sys.modules, "freshquant.subject_management.write_service", raising=False
    )

    import freshquant.subject_management.write_service as write_service_module

    write_service_module = importlib.reload(write_service_module)
    SubjectManagementWriteService = write_service_module.SubjectManagementWriteService
    yield


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(item) for item in (docs or [])]
        self.updates = []

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in dict(query or {}).items()):
                return dict(doc)
        return None

    def update_one(self, query, update, upsert=False):
        self.updates.append(
            {
                "query": dict(query),
                "update": dict(update),
                "upsert": bool(upsert),
            }
        )


class FakeDatabase(dict):
    def __init__(self, initial=None):
        super().__init__(initial or {})

    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


@pytest.mark.parametrize("field_name", ["initial_lot_amount", "lot_amount"])
def test_update_must_pool_rejects_fractional_lot_amounts(monkeypatch, field_name):
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_info",
        lambda symbol: {"name": "浦发银行", "sec": "stock"},
    )
    database = FakeDatabase()
    service = SubjectManagementWriteService(database=database)
    payload = {
        "category": "银行",
        "stop_loss_price": 9.2,
        "initial_lot_amount": 80000,
        "lot_amount": 50000,
        "forever": True,
        field_name: 50000.9,
    }

    with pytest.raises(ValueError, match=rf"^{field_name} must be integer$"):
        service.update_must_pool("600000.SH", payload)


def test_update_guardian_buy_grid_forwards_per_level_switches():
    captured = {}

    class FakeGuardianService:
        def upsert_config(self, symbol, **kwargs):
            captured["call"] = (symbol, kwargs)
            return {
                "code": symbol,
                "enabled": True,
                "BUY-1": 10.2,
                "BUY-2": 9.9,
                "BUY-3": 9.5,
                "buy_enabled": [True, False, True],
            }

    service = SubjectManagementWriteService(
        database=FakeDatabase(),
        guardian_service=FakeGuardianService(),
    )

    result = service.update_guardian_buy_grid(
        "600000.SH",
        {
            "buy_1": 10.2,
            "buy_2": 9.9,
            "buy_3": 9.5,
            "buy_enabled": [True, False, True],
            "updated_by": "pytest",
        },
    )

    assert captured["call"] == (
        "600000",
        {
            "buy_1": 10.2,
            "buy_2": 9.9,
            "buy_3": 9.5,
            "buy_enabled": [True, False, True],
            "enabled": None,
            "updated_by": "pytest",
        },
    )
    assert result["symbol"] == "600000"
    assert result["buy_enabled"] == [True, False, True]


def test_update_must_pool_forces_forever_true(monkeypatch):
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_info",
        lambda symbol: {"name": "浦发银行", "sec": "stock"},
    )
    database = FakeDatabase()
    service = SubjectManagementWriteService(database=database)

    result = service.update_must_pool(
        "600000.SH",
        {
            "category": "银行",
            "stop_loss_price": 9.2,
            "initial_lot_amount": 80000,
            "lot_amount": 50000,
            "forever": False,
        },
    )

    assert result["forever"] is True
    assert database["must_pool"].updates[0]["update"]["$set"]["forever"] is True


def test_update_must_pool_keeps_existing_memberships(monkeypatch):
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_info",
        lambda symbol: {"name": "浦发银行", "sec": "stock"},
    )
    existing_memberships = [
        {
            "source": "shouban30",
            "category": "plate:11",
            "added_at": "2026-03-20T09:00:00",
            "expire_at": None,
            "extra": {"shouban30_plate_key": "11"},
        }
    ]
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "category": "旧分类",
                        "sources": ["shouban30"],
                        "categories": ["plate:11"],
                        "memberships": existing_memberships,
                        "workspace_order_hint": 5,
                    }
                ]
            )
        }
    )
    service = SubjectManagementWriteService(database=database)

    result = service.update_must_pool(
        "600000.SH",
        {
            "category": "银行",
            "stop_loss_price": 9.2,
            "initial_lot_amount": 80000,
            "lot_amount": 50000,
            "updated_by": "pytest",
        },
    )

    saved = database["must_pool"].updates[0]["update"]["$set"]
    assert result["category"] == "银行"
    assert saved["manual_category"] == "银行"
    assert saved["category"] == "银行"
    assert saved["sources"] == ["shouban30"]
    assert saved["categories"] == ["plate:11"]
    assert saved["memberships"] == existing_memberships
    assert saved["workspace_order_hint"] == 5
