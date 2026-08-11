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


def _build_db(*, requests=None, entries=None, slices=None, allocations=None):
    database = FakeDatabase(
        {
            "om_order_requests": FakeCollection(requests or []),
            "om_position_entries": FakeCollection(entries or []),
            "om_entry_slices": FakeCollection(slices or []),
            "om_exit_allocations": FakeCollection(allocations or []),
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
