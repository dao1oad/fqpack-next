from __future__ import annotations

import sys
import types
from dataclasses import dataclass

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

from freshquant.strategy.guardian_buy_grid import GuardianBuyGridService


@dataclass
class _UpdateResult:
    matched_count: int
    modified_count: int
    upserted_id: str | None = None


@dataclass
class _InsertResult:
    inserted_id: str


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query, projection=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                if projection:
                    projected = {}
                    include_id = projection.get("_id", 1)
                    for key, include in projection.items():
                        if include and key != "_id" and key in doc:
                            projected[key] = doc[key]
                    if include_id and "_id" in doc:
                        projected["_id"] = doc["_id"]
                    return projected
                return dict(doc)
        return None

    def insert_one(self, document):
        self.docs.append(dict(document))
        return _InsertResult(inserted_id=str(len(self.docs)))

    def update_one(self, query, update, upsert=False):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                updated = dict(doc)
                updated.update(update.get("$set", {}))
                self.docs[index] = updated
                return _UpdateResult(matched_count=1, modified_count=1)
        if not upsert:
            return _UpdateResult(matched_count=0, modified_count=0)
        new_doc = dict(query)
        new_doc.update(update.get("$set", {}))
        self.docs.append(new_doc)
        return _UpdateResult(
            matched_count=0,
            modified_count=0,
            upserted_id=str(len(self.docs)),
        )


class FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _build_service(database=None):
    return GuardianBuyGridService(
        database=database or FakeDatabase(),
        get_trade_amount_fn=lambda _code: 50000,
    )


def test_new_open_prefers_initial_lot_amount_then_lot_amount_then_default():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "000001",
                        "initial_lot_amount": 180000,
                        "lot_amount": 60000,
                    },
                    {"code": "000002", "lot_amount": 80000},
                    {"code": "000003"},
                ]
            )
        }
    )
    service = _build_service(database)

    decision_one = service.build_new_open_decision("000001", 10.0)
    decision_two = service.build_new_open_decision("000002", 10.0)
    decision_three = service.build_new_open_decision("000003", 10.0)
    decision_four = service.build_new_open_decision("000004", 10.0)

    assert decision_one["initial_amount"] == 180000
    assert decision_one["quantity"] == 18000
    assert decision_two["initial_amount"] == 80000
    assert decision_two["quantity"] == 8000
    assert decision_three["initial_amount"] == 150000
    assert decision_three["quantity"] == 15000
    assert decision_four["initial_amount"] == 150000
    assert decision_four["quantity"] == 15000


def test_holding_add_uses_deepest_active_hit_level():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [True, True, True]}]
            ),
        }
    )
    service = _build_service(database)

    decision = service.build_holding_add_decision("000001", 7.8)

    assert decision["grid_level"] == "BUY-3"
    assert decision["hit_levels"] == ["BUY-1", "BUY-2", "BUY-3"]
    assert decision["multiplier"] == 4
    assert decision["quantity"] == 25600
    assert decision["buy_active_before"] == [True, True, True]


def test_holding_add_skips_inactive_levels_and_uses_next_active_match():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [False, True, True]}]
            ),
        }
    )
    service = _build_service(database)

    decision = service.build_holding_add_decision("000001", 8.5)

    assert decision["grid_level"] == "BUY-2"
    assert decision["hit_levels"] == ["BUY-2"]
    assert decision["multiplier"] == 3
    assert decision["quantity"] == 17600


def test_holding_add_without_config_falls_back_to_base_amount():
    service = _build_service(FakeDatabase())

    decision = service.build_holding_add_decision("000001", 10.0)

    assert decision["grid_level"] is None
    assert decision["hit_levels"] == []
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 5000


def test_accepting_buy_deactivates_all_hit_levels():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [True, True, True]}]
            ),
        }
    )
    service = _build_service(database)
    decision = service.build_holding_add_decision("000001", 7.8)

    state = service.mark_buy_order_accepted(
        "000001",
        hit_levels=decision["hit_levels"],
        grid_level=decision["grid_level"],
        source_price=decision["source_price"],
    )

    assert state["buy_active"] == [False, False, False]
    assert state["last_hit_level"] == "BUY-3"
    assert state["last_hit_price"] == 7.8


def test_sell_trade_resets_all_buy_levels():
    database = FakeDatabase(
        {
            "guardian_buy_grid_states": FakeCollection(
                [
                    {
                        "code": "000001",
                        "buy_active": [False, False, True],
                        "last_hit_level": "BUY-2",
                        "last_hit_price": 8.9,
                    }
                ]
            )
        }
    )
    service = _build_service(database)

    state = service.reset_after_sell_trade("000001")

    assert state["buy_active"] == [True, True, True]
    assert state["last_hit_level"] is None
    assert state["last_hit_price"] is None
    assert state["last_reset_reason"] == "sell_trade_fact"


def test_updating_config_resets_buy_active_and_records_audit_log():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [False, False, True]}]
            ),
            "audit_log": FakeCollection(),
        }
    )
    service = _build_service(database)

    result = service.upsert_config(
        "000001",
        buy_1=10.1,
        buy_2=9.1,
        buy_3=8.1,
        enabled=True,
        updated_by="cli",
    )

    assert result["BUY-1"] == 10.1
    assert service.get_state("000001")["buy_active"] == [True, True, True]
    assert (
        database["audit_log"].docs[-1]["operation"]
        == "guardian_buy_grid_config_updated"
    )
    assert database["audit_log"].docs[-1]["state_reset"] is True


def test_manual_state_changes_and_manual_reset_are_audited():
    database = FakeDatabase({"audit_log": FakeCollection()})
    service = _build_service(database)

    service.upsert_state(
        "000001",
        buy_active=[False, True, True],
        last_hit_level="BUY-1",
        last_hit_price=9.8,
        updated_by="api",
    )
    service.reset_after_sell_trade(
        "000001",
        updated_by="cli",
        reason="manual_reset",
    )

    operations = [item["operation"] for item in database["audit_log"].docs]
    assert operations == [
        "guardian_buy_grid_state_updated",
        "guardian_buy_grid_state_reset",
    ]
