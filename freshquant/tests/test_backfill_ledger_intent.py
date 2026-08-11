# -*- coding: utf-8 -*-
"""backfill_ledger_intent 回填与守恒校验测试（Issue #571 步骤 1）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "script"
    / "maintenance"
    / "backfill_ledger_intent.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "backfill_ledger_intent",
    _SCRIPT_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
backfill_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backfill_module)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(item) for item in docs or []]

    def find(self, query=None):
        return [dict(item) for item in self.docs]

    def find_one(self, query=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in (query or {}).items()):
                return dict(doc)
        return None

    def update_one(self, query, update):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in (query or {}).items()):
                for operator, fields in update.items():
                    if operator == "$set":
                        doc.update(fields)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def update_many(self, _filter, update):
        matched = 0
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in (_filter or {}).items()):
                matched += 1
                for operator, fields in update.items():
                    if operator == "$set":
                        doc.update(fields)
                    elif operator == "$unset":
                        for field in fields:
                            doc.pop(field, None)
        return SimpleNamespace(matched_count=matched, modified_count=matched)

    def delete_many(self, _filter=None):
        count = len(self.docs)
        self.docs = []
        return SimpleNamespace(deleted_count=count)

    def insert_many(self, documents, ordered=False):
        self.docs.extend(dict(item) for item in documents)
        return SimpleNamespace(inserted_count=len(documents))


class FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _build_db(
    *,
    requests=None,
    entries=None,
    slices=None,
    allocations=None,
    trade_facts=None,
    orders=None,
    broker_orders=None,
):
    database = FakeDatabase(
        {
            "om_order_requests": FakeCollection(requests or []),
            "om_position_entries": FakeCollection(entries or []),
            "om_entry_slices": FakeCollection(slices or []),
            "om_exit_allocations": FakeCollection(allocations or []),
            "om_trade_facts": FakeCollection(trade_facts or []),
            "om_orders": FakeCollection(orders or []),
            "om_broker_orders": FakeCollection(broker_orders or []),
        }
    )
    database.client = SimpleNamespace(__getitem__=lambda self, name: FakeDatabase())
    return database


def _run(monkeypatch, database, *args):
    monkeypatch.setattr(backfill_module, "get_order_management_db", lambda: database)
    return CliRunner().invoke(backfill_module.main, list(args))


def test_dry_run_derives_plan_without_writes(monkeypatch):
    database = _build_db(
        requests=[
            {
                "request_id": "req_tp",
                "action": "sell",
                "source": "tpsl_takeprofit",
                "scope_type": "takeprofit_batch",
            },
            {
                "request_id": "req_guardian",
                "action": "sell",
                "strategy_context": {"guardian_sell_sources": {"version": 2}},
            },
            {
                "request_id": "req_base_line",
                "action": "buy",
                "strategy_context": {
                    "buy_ledger": "base_line",
                    "guardian_buy_grid": {"path": "base_line"},
                },
            },
            {
                "request_id": "req_holding_add",
                "action": "buy",
                "strategy_context": {"guardian_buy_grid": {"path": "holding_add"}},
            },
            {
                "request_id": "req_stoploss",
                "action": "sell",
                "scope_type": "symbol_stoploss_batch",
            },
            {"request_id": "req_cancel", "action": "cancel"},
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code == 0, response.output
    assert "requests=5" in response.output
    assert database["om_order_requests"].docs[0].get("ledger_intent") is None


def test_execute_backfills_intents_from_legacy_contexts(monkeypatch):
    database = _build_db(
        requests=[
            {
                "request_id": "req_tp",
                "action": "sell",
                "source": "tpsl_takeprofit",
                "scope_type": "takeprofit_batch",
            },
            {
                "request_id": "req_guardian",
                "action": "sell",
                "strategy_context": {"guardian_sell_sources": {"version": 2}},
            },
            {
                "request_id": "req_base_line",
                "action": "buy",
                "strategy_context": {"buy_ledger": "base_line"},
            },
            {
                "request_id": "req_holding_add",
                "action": "buy",
                "strategy_context": {"guardian_buy_grid": {"path": "holding_add"}},
            },
            {
                "request_id": "req_stoploss",
                "action": "sell",
                "scope_type": "symbol_stoploss_batch",
            },
            {
                "request_id": "req_manual_sell",
                "action": "sell",
                "source": "web",
            },
            {
                "request_id": "req_existing",
                "action": "sell",
                "ledger_intent": "t",
                "strategy_context": {},
            },
        ]
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code == 0, response.output
    by_id = {item["request_id"]: item for item in database["om_order_requests"].docs}
    assert by_id["req_tp"]["ledger_intent"] == "base"
    assert by_id["req_guardian"]["ledger_intent"] == "t"
    assert by_id["req_base_line"]["ledger_intent"] == "base"
    assert by_id["req_holding_add"]["ledger_intent"] == "t"
    assert by_id["req_stoploss"]["ledger_intent"] == "-"
    assert by_id["req_manual_sell"]["ledger_intent"] == "-"
    assert by_id["req_existing"]["ledger_intent"] == "t"
    assert "backfill verify" in response.output


def test_execute_backfills_position_type_and_members(monkeypatch):
    database = _build_db(
        entries=[
            {
                "entry_id": "entry_t",
                "symbol": "000001",
                "position_type": "t",
                "original_quantity": 300,
                "remaining_quantity": 300,
                "aggregation_members": [{"broker_order_key": "k1", "quantity": 300}],
            },
            {
                "entry_id": "entry_missing",
                "symbol": "000002",
                "original_quantity": 100,
                "remaining_quantity": 100,
                "aggregation_members": [{"broker_order_key": "k2", "quantity": 100}],
            },
        ],
        slices=[
            {
                "entry_slice_id": "slice_t",
                "entry_id": "entry_t",
                "symbol": "000001",
                "position_type": "t",
                "original_quantity": 300,
                "remaining_quantity": 300,
            },
            {
                "entry_slice_id": "slice_missing",
                "entry_id": "entry_missing",
                "symbol": "000002",
                "original_quantity": 100,
                "remaining_quantity": 100,
            },
        ],
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code == 0, response.output
    entries = {item["entry_id"]: item for item in database["om_position_entries"].docs}
    slices = {item["entry_slice_id"]: item for item in database["om_entry_slices"].docs}
    assert entries["entry_t"]["position_type"] == "t"
    assert entries["entry_missing"]["position_type"] == "base"
    assert entries["entry_missing"]["aggregation_members"][0]["position_type"] == "base"
    assert slices["slice_missing"]["position_type"] == "base"
    assert slices["slice_t"]["position_type"] == "t"


def test_execute_is_idempotent_and_conservation_passes(monkeypatch):
    database = _build_db(
        requests=[
            {
                "request_id": "req_tp",
                "action": "sell",
                "source": "tpsl_takeprofit",
                "scope_type": "takeprofit_batch",
            }
        ],
        entries=[
            {
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 200,
                "remaining_quantity": 200,
            }
        ],
        slices=[
            {
                "entry_slice_id": "slice_1",
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 200,
                "remaining_quantity": 200,
            }
        ],
    )
    first = _run(monkeypatch, database, "--execute")
    assert first.exit_code == 0, first.output
    second = _run(monkeypatch, database, "--execute")
    assert second.exit_code == 0, second.output
    assert "repeat_requests=0" in second.output
    assert "repeat_entries=0" in second.output
    assert "repeat_slices=0" in second.output


def test_execute_aborts_on_l1_conservation_mismatch(monkeypatch):
    database = _build_db(
        entries=[
            {
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 200,
                "remaining_quantity": 200,
            }
        ],
        slices=[
            {
                "entry_slice_id": "slice_1",
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 100,
                "remaining_quantity": 100,
            }
        ],
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code != 0
    assert "L1" in response.output


def test_execute_aborts_on_allocation_integrity_mismatch(monkeypatch):
    database = _build_db(
        entries=[
            {
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 200,
                "remaining_quantity": 100,
            }
        ],
        slices=[
            {
                "entry_slice_id": "slice_1",
                "entry_id": "entry_1",
                "symbol": "000001",
                "original_quantity": 200,
                "remaining_quantity": 100,
            }
        ],
        allocations=[
            {
                "allocation_id": "alloc_1",
                "internal_order_id": "ord_1",
                "entry_id": "entry_1",
                "entry_slice_id": "slice_missing",
                "allocated_quantity": 100,
            }
        ],
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code != 0
    assert "allocation integrity" in response.output


def test_dry_run_and_execute_are_mutually_exclusive(monkeypatch):
    database = _build_db()
    response = _run(monkeypatch, database, "--dry-run", "--execute")
    assert response.exit_code != 0


def test_dry_run_conflicts_on_unknown_buy_path(monkeypatch):
    """#571：未知 buy path 无法确定归属 → dry-run 显式冲突并停止，不静默归 base。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_unknown_path",
                "action": "buy",
                "source": "strategy",
                "strategy_context": {"guardian_buy_grid": {"path": "weird_path"}},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output
    assert "req_unknown_path" in response.output
    assert database["om_order_requests"].docs[0].get("ledger_intent") is None


def test_dry_run_conflicts_on_empty_buy_path_with_strategy_source(monkeypatch):
    """#571：空 buy path + strategy source 无确定证据 → 冲突停止。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_empty_path",
                "action": "buy",
                "source": "strategy",
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output


def test_dry_run_conflicts_on_unresolved_strategy_sell(monkeypatch):
    """#571：strategy 卖单无 TP/stoploss/guardian_sell_sources 证据 → 冲突停止。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_strategy_sell",
                "action": "sell",
                "source": "strategy",
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output
    assert "req_strategy_sell" in response.output


def test_execute_stops_before_any_write_on_conflict(monkeypatch):
    """#571：冲突存在时 execute 不写任何文档（可解析项也不写）。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_resolvable",
                "action": "buy",
                "source": "web",
                "strategy_context": {},
            },
            {
                "request_id": "req_conflict",
                "action": "buy",
                "source": "strategy",
                "strategy_context": {"guardian_buy_grid": {"path": "unknown"}},
            },
        ]
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output
    assert all(
        item.get("ledger_intent") is None for item in database["om_order_requests"].docs
    )


def test_execute_backfills_rebuild_flatten_request_as_base(monkeypatch):
    """#571：flatten 重建 broker-only open entry（严格证据组合）→ base。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_rebuilt_flatten_1",
                "action": "buy",
                "source": "order_ledger_rebuild",
                "rebuild_source": "position_snapshot_flatten",
                "rebuilt_open": True,
                "data_quality": "reconstructed",
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code == 0, response.output
    assert database["om_order_requests"].docs[0]["ledger_intent"] == "base"


def test_dry_run_conflicts_on_rebuild_flatten_missing_rebuilt_open(monkeypatch):
    """#571：rebuilt_open 缺失 → 严格证据组合不成立 → fail-closed。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_rebuilt_missing_open",
                "action": "buy",
                "source": "order_ledger_rebuild",
                "rebuild_source": "position_snapshot_flatten",
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output
    assert "req_rebuilt_missing_open" in response.output


def test_dry_run_conflicts_on_rebuild_flatten_missing_rebuild_source(monkeypatch):
    """#571：rebuild_source 缺失 → 严格证据组合不成立 → fail-closed。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_rebuilt_missing_rs",
                "action": "buy",
                "source": "order_ledger_rebuild",
                "rebuilt_open": True,
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output
    assert "req_rebuilt_missing_rs" in response.output


def test_dry_run_conflicts_on_rebuild_flatten_wrong_rebuild_source(monkeypatch):
    """#571：rebuild_source 不匹配 → 严格证据组合不成立 → fail-closed。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_rebuilt_wrong_rs",
                "action": "buy",
                "source": "order_ledger_rebuild",
                "rebuild_source": "position_snapshot_legacy",
                "rebuilt_open": True,
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output


def test_dry_run_conflicts_on_rebuild_flatten_sell(monkeypatch):
    """#571：sell 方向带重建标记 → 卖分支无证据 → fail-closed。"""

    database = _build_db(
        requests=[
            {
                "request_id": "req_rebuilt_sell",
                "action": "sell",
                "source": "order_ledger_rebuild",
                "rebuild_source": "position_snapshot_flatten",
                "rebuilt_open": True,
                "strategy_context": {},
            }
        ]
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved ledger_intent" in response.output


def test_execute_backfills_allocation_internal_order_id_via_unique_trade_fact(
    monkeypatch,
):
    """#571：exit allocations 缺 internal_order_id 时经 exit_trade_fact_id
    唯一关联 om_trade_facts 回填（幂等复验 0 变更）。"""

    database = _build_db(
        entries=[
            {
                "entry_id": "entry_a",
                "symbol": "000001",
                "original_quantity": 900,
                "remaining_quantity": 0,
            }
        ],
        slices=[
            {
                "entry_slice_id": "slice_a",
                "entry_id": "entry_a",
                "symbol": "000001",
                "original_quantity": 900,
                "remaining_quantity": 0,
            }
        ],
        allocations=[
            {
                "allocation_id": "alloc_audit_1",
                "exit_trade_fact_id": "fact_sell_1",
                "entry_id": "entry_a",
                "entry_slice_id": "slice_a",
                "position_type": "base",
                "allocated_quantity": 900,
            }
        ],
        trade_facts=[
            {
                "trade_fact_id": "fact_sell_1",
                "internal_order_id": "ord_broker_b859cfc3",
                "request_id": None,
            }
        ],
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code == 0, response.output
    stored = database["om_exit_allocations"].docs[0]
    assert stored["internal_order_id"] == "ord_broker_b859cfc3"
    assert "repeat_allocations=0" in response.output


def test_dry_run_conflicts_on_allocation_without_trade_fact(monkeypatch):
    """#571：exit_trade_fact_id 无对应 trade_fact → fail-closed 冲突停止。"""

    database = _build_db(
        allocations=[
            {
                "allocation_id": "alloc_orphan",
                "exit_trade_fact_id": "fact_missing",
            }
        ],
        trade_facts=[],
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "unresolved allocation internal_order_id" in response.output
    assert "alloc_orphan" in response.output


def test_dry_run_conflicts_on_allocation_with_ambiguous_trade_fact(monkeypatch):
    """#571：trade_fact_id 多条候选 → 无法唯一关联 → fail-closed。"""

    database = _build_db(
        allocations=[
            {
                "allocation_id": "alloc_amb",
                "exit_trade_fact_id": "fact_dup",
            }
        ],
        trade_facts=[
            {"trade_fact_id": "fact_dup", "internal_order_id": "ord_1"},
            {"trade_fact_id": "fact_dup", "internal_order_id": "ord_2"},
        ],
    )
    response = _run(monkeypatch, database, "--dry-run")
    assert response.exit_code != 0
    assert "candidates=2" in response.output


def test_execute_unsets_filled_quantity_and_converges_broker_state(monkeypatch):
    """#571 目标形态：broker-only 卖单 filled=requested=9000、om_orders
    非终态 → broker state 收敛 FILLED；om_orders.filled_quantity 死字段清除；
    CANCELED 终态不回退。"""

    database = _build_db(
        orders=[
            {
                "internal_order_id": "ord_broker_tgt",
                "state": "PARTIAL_FILLED",
                "filled_quantity": 0,
            },
            {
                "internal_order_id": "ord_canceled",
                "state": "CANCELED",
                "filled_quantity": 0,
            },
        ],
        broker_orders=[
            {
                "broker_order_key": "k_tgt",
                "internal_order_id": "ord_broker_tgt",
                "state": "PARTIAL_FILLED",
                "filled_quantity": 9000,
                "requested_quantity": 9000,
            },
            {
                "broker_order_key": "k_canceled",
                "internal_order_id": "ord_canceled",
                "state": "PARTIAL_FILLED",
                "filled_quantity": 500,
                "requested_quantity": 500,
            },
        ],
    )
    response = _run(monkeypatch, database, "--execute")
    assert response.exit_code == 0, response.output
    orders = {item["internal_order_id"]: item for item in database["om_orders"].docs}
    assert "filled_quantity" not in orders["ord_broker_tgt"]
    assert "filled_quantity" not in orders["ord_canceled"]
    brokers = {
        item["broker_order_key"]: item for item in database["om_broker_orders"].docs
    }
    assert brokers["k_tgt"]["state"] == "FILLED"
    assert brokers["k_canceled"]["state"] == "CANCELED"
    assert "repeat_broker_states=0" in response.output
    assert "repeat_filled_quantity_docs=0" in response.output
