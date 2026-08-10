from __future__ import annotations

import sys
import types
from dataclasses import dataclass

sys.modules.setdefault("freshquant.message", types.ModuleType("freshquant.message"))

from freshquant.strategy.guardian_buy_grid import GuardianBuyGridService

sys.modules.pop("freshquant.message", None)


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
    assert decision_three["initial_amount"] == 100000
    assert decision_three["quantity"] == 10000
    assert decision_four["initial_amount"] == 100000
    assert decision_four["quantity"] == 10000


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
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_cap_unconfigured"
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
    assert decision["hit_levels"] == ["BUY-1", "BUY-2"]
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 0


def test_holding_add_skips_levels_disabled_by_manual_config_switch():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [True, False, True],
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
    assert decision["hit_levels"] == ["BUY-1", "BUY-3"]
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 0


def test_holding_add_without_config_falls_back_to_base_amount():
    service = _build_service(FakeDatabase())

    decision = service.build_holding_add_decision("000001", 10.0)

    assert decision["grid_level"] is None
    assert decision["hit_levels"] == []
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 5000


def test_missing_state_is_audit_only_and_does_not_gate_levels():
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
            )
        }
    )
    service = _build_service(database)

    state = service.get_state("000001")
    decision = service.build_holding_add_decision("000001", 7.8)

    assert state["buy_active"] == [False, False, False]
    assert decision["buy_active_before"] == [False, False, False]
    assert decision["grid_level"] == "BUY-3"
    assert decision["hit_levels"] == ["BUY-1", "BUY-2", "BUY-3"]
    assert decision["multiplier"] == 1
    assert decision["quantity"] == 0


def test_accepting_buy_keeps_buy_active_as_audit_only_state():
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

    assert state["buy_active"] == [True, True, True]
    assert state["last_hit_level"] == "BUY-3"
    assert state["last_hit_price"] == 7.8


def test_position_cap_limits_each_buy_to_base_amount_and_remaining_capacity():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [200000, 350000, 500000],
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [False, False, False]}]
            ),
        }
    )
    service = _build_service(database)
    service._load_position_capacity = lambda _code: (330000.0, 800000.0)

    decision = service.build_holding_add_decision("000001", 9.5)

    assert decision["stage"] == "BUY-1_TO_BUY-2"
    assert decision["effective_stage_cap"] == 350000
    assert decision["remaining_amount"] == 20000
    assert decision["capacity_ratio"] == 0.5
    assert decision["capacity_quantity"] == 1000
    assert decision["quantity"] == 1000


def test_holding_add_half_capacity_applies_to_buy3_below_stage():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [200000, 350000, 500000],
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                    }
                ]
            )
        }
    )
    service = _build_service(database)
    service._load_position_capacity = lambda _code: (750000.0, 800000.0)

    decision = service.build_holding_add_decision("000001", 7.5)

    assert decision["stage"] == "BUY-3_BELOW"
    assert decision["effective_stage_cap"] == 800000
    assert decision["remaining_amount"] == 50000
    assert decision["capacity_ratio"] == 0.5
    assert decision["capacity_quantity"] == 3300
    assert decision["quantity"] == 3300


def test_new_open_uses_full_capacity_ratio():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [200000, 350000, 500000],
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                    }
                ]
            )
        }
    )
    service = _build_service(database)
    service._load_position_capacity = lambda _code: (0.0, 800000.0)

    decision = service.build_new_open_decision("000001", 9.5)

    assert decision["path"] == "new_open"
    assert decision["stage"] == "BUY-1_TO_BUY-2"
    assert decision["remaining_amount"] == 350000
    assert decision["capacity_ratio"] == 1.0
    assert decision["capacity_quantity"] == 36800
    assert decision["quantity"] == 10500


def test_holding_add_half_capacity_below_one_lot_skips():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [200000, 350000, 500000],
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                    }
                ]
            )
        }
    )
    service = _build_service(database)
    service._load_position_capacity = lambda _code: (349000.0, 800000.0)

    decision = service.build_holding_add_decision("000001", 9.5)

    assert decision["stage"] == "BUY-1_TO_BUY-2"
    assert decision["remaining_amount"] == 1000
    assert decision["capacity_ratio"] == 0.5
    assert decision["capacity_quantity"] == 0
    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_capacity_exhausted"


def test_new_open_with_existing_grid_and_missing_caps_fails_closed():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                    }
                ]
            )
        }
    )

    decision = _build_service(database).build_new_open_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_cap_unconfigured"


def test_grid_with_invalid_cap_shape_fails_closed_as_invalid():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [200000, 350000],
                    }
                ]
            )
        }
    )

    decision = _build_service(database).build_new_open_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_config_invalid"


def test_grid_with_invalid_cap_type_fails_closed_as_invalid():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": "200000,350000,500000",
                    }
                ]
            )
        }
    )

    decision = _build_service(database).build_new_open_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_config_invalid"


def test_grid_with_non_positive_caps_fails_closed_as_invalid():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [-1, 350000, 500000],
                    }
                ]
            )
        }
    )

    decision = _build_service(database).build_new_open_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_config_invalid"


def test_grid_with_descending_caps_fails_closed_as_invalid():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "max_position_amounts": [350000, 200000, 500000],
                    }
                ]
            )
        }
    )

    decision = _build_service(database).build_new_open_decision("000001", 9.5)

    assert decision["quantity"] == 0
    assert decision["skip_reason"] == "grid_position_config_invalid"


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
        buy_enabled=[True, False, True],
        enabled=True,
        updated_by="cli",
    )

    assert result["BUY-1"] == 10.1
    assert result["buy_enabled"] == [True, False, True]
    assert service.get_state("000001")["buy_active"] == [True, True, True]
    assert (
        database["audit_log"].docs[-1]["operation"]
        == "guardian_buy_grid_config_updated"
    )
    assert database["audit_log"].docs[-1]["state_reset"] is True


def test_enabled_true_without_buy_enabled_reopens_all_levels_for_legacy_callers():
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [False, False, False],
                        "enabled": False,
                    }
                ]
            )
        }
    )
    service = _build_service(database)

    result = service.upsert_config(
        "000001",
        enabled=True,
        updated_by="cli",
    )

    assert result["buy_enabled"] == [True, True, True]
    assert result["enabled"] is True


def test_disable_grid_flips_buy_enabled_and_state_off_without_caps_validation():
    # M2：config 带 max_position_amounts 且 capacity 不可用（全局限额无法解析）
    # 时，upsert_config 的 caps 校验会失败；disable_grid 必须直写绕过、仍能关闭。
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                        "max_position_amounts": [999999, 1999999, 2999999],
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [True, True, True]}]
            ),
            "audit_log": FakeCollection(),
        }
    )
    service = _build_service(database)

    result = service.disable_grid("000001", updated_by="xt_account_sync")

    assert result["buy_enabled"] == [False, False, False]
    assert result["enabled"] is False
    # 价位保留（历史配置供重配参考）
    assert result["BUY-1"] == 10.0
    assert service.get_state("000001")["buy_active"] == [False, False, False]


def test_disable_grid_missing_config_is_noop():
    database = FakeDatabase({})
    service = _build_service(database)

    assert service.disable_grid("000001") is None
    assert database["guardian_buy_grid_configs"].docs == []


def test_disabled_grid_blocks_new_open_until_reconfigured(monkeypatch):
    # M3：关闭后 build_new_open_decision 被阻断（quantity=0）；重配后恢复
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [{"code": "000001", "initial_lot_amount": 80000}]
            ),
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [True, True, True],
                        "enabled": True,
                        "max_position_amounts": [10000, 20000, 30000],
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(),
            "audit_log": FakeCollection(),
        }
    )
    service = _build_service(database)
    # 注入 position capacity：未注入时 _load_position_capacity 会连真实
    # PositionManagementRepository（Mongo），CI 无 Mongo 时返回 None 导致
    # quantity=0，测试与运行环境耦合。
    monkeypatch.setattr(
        service, "_load_position_capacity", lambda code: (0.0, 999999.0)
    )

    before = service.build_new_open_decision("000001", 9.5)
    assert before["quantity"] > 0

    service.disable_grid("000001", updated_by="xt_account_sync")
    blocked = service.build_new_open_decision("000001", 9.5)
    assert blocked["quantity"] == 0
    assert blocked["skip_reason"] == "grid_disabled"

    # 重新开仓必须重配价位：恢复 enabled 后可正常开仓
    service.upsert_config(
        "000001",
        buy_1=10.0,
        buy_2=9.0,
        buy_3=8.0,
        buy_enabled=[True, True, True],
        enabled=True,
        max_position_amounts=[10000, 20000, 30000],
        updated_by="manual",
    )
    restored = service.build_new_open_decision("000001", 9.5)
    assert restored["quantity"] > 0


def test_disabled_config_gates_holding_add_even_after_late_sell_reset():
    # 顺序竞态：先关闭，后迟到 sell trade 触发 reset_after_sell_trade
    # （buy_active 变回 [T,T,T]）；config buy_enabled=[F,F,F] 是真正守门人，
    # _resolve_hit_levels 仍返回空，双闸不冲突。
    database = FakeDatabase(
        {
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "000001",
                        "BUY-1": 10.0,
                        "BUY-2": 9.0,
                        "BUY-3": 8.0,
                        "buy_enabled": [False, False, False],
                        "enabled": False,
                        "max_position_amounts": [10000, 20000, 30000],
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [{"code": "000001", "buy_active": [True, True, True]}]
            ),
            "audit_log": FakeCollection(),
        }
    )
    service = _build_service(database)

    decision = service.build_holding_add_decision("000001", 8.5)

    assert decision["hit_levels"] == []
    assert decision["quantity"] == 0


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
