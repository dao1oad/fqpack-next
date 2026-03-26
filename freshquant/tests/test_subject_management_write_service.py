import importlib

import pytest

from freshquant.subject_management.write_service import SubjectManagementWriteService


class FakeCollection:
    def __init__(self):
        self.updates = []

    def update_one(self, query, update, upsert=False):
        self.updates.append(
            {
                "query": dict(query),
                "update": dict(update),
                "upsert": bool(upsert),
            }
        )


class FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _instrument_general_module():
    return importlib.import_module("freshquant.instrument.general")


@pytest.mark.parametrize("field_name", ["initial_lot_amount", "lot_amount"])
def test_update_must_pool_rejects_fractional_lot_amounts(monkeypatch, field_name):
    monkeypatch.setattr(
        _instrument_general_module(),
        "query_instrument_info",
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
        _instrument_general_module(),
        "query_instrument_info",
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
