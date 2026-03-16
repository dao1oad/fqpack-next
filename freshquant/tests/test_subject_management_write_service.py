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
