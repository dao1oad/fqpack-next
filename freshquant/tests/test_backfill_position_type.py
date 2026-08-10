# -*- coding: utf-8 -*-
"""backfill_position_type 回填与 --activate-takeprofit 测试（#549 §11/§13）。"""

from __future__ import annotations

from types import SimpleNamespace

from click.testing import CliRunner

import script.maintenance.backfill_position_type as backfill_module


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query=None):
        return list(self.docs)

    def find_one(self, query=None):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in (query or {}).items()):
                return dict(doc)
        return None

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


def _build_dbs(*, positions=None, entries=None, slices=None, profiles=None):
    projection_db = FakeDatabase({"xt_positions": FakeCollection(positions or [])})
    order_db = FakeDatabase(
        {
            "om_position_entries": FakeCollection(entries or []),
            "om_entry_slices": FakeCollection(slices or []),
            "om_takeprofit_profiles": FakeCollection(profiles or []),
        }
    )
    order_db.client = SimpleNamespace(__getitem__=lambda self, name: FakeDatabase())
    return projection_db, order_db


def _stub_flatten_service(monkeypatch, result):
    class _FakeRebuildService:
        def build_flatten_from_positions(self, **kwargs):
            return result

    monkeypatch.setattr(
        backfill_module,
        "OrderLedgerV2RebuildService",
        lambda: _FakeRebuildService(),
    )


def _run(monkeypatch, projection_db, order_db, *args):
    monkeypatch.setattr(
        backfill_module,
        "get_projection_db",
        lambda: projection_db,
    )
    monkeypatch.setattr(
        backfill_module,
        "get_order_management_db",
        lambda: order_db,
    )
    return CliRunner().invoke(backfill_module.main, list(args))


def test_backfill_dry_run_does_not_write(monkeypatch):
    projection_db, order_db = _build_dbs(
        positions=[{"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.0}],
    )
    result = {
        "position_entry_documents": [
            {
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "entry_slice_documents": [
            {
                "entry_slice_id": "slice_f",
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "flatten": {"invariant_checks": [{"passed": True}]},
    }
    _stub_flatten_service(monkeypatch, result)
    response = _run(monkeypatch, projection_db, order_db, "--dry-run")
    assert response.exit_code == 0, response.output
    assert "dry-run complete" in response.output
    assert order_db["om_position_entries"].docs == []
    assert order_db["om_entry_slices"].docs == []


def test_backfill_execute_preserves_t_marker_and_writes(monkeypatch):
    projection_db, order_db = _build_dbs(
        positions=[{"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.0}],
        entries=[
            {
                "entry_id": "entry_old_t",
                "symbol": "000001",
                "position_type": "t",
                "remaining_quantity": 300,
            }
        ],
    )
    result = {
        "position_entry_documents": [
            {
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "entry_slice_documents": [
            {
                "entry_slice_id": "slice_f",
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "flatten": {"invariant_checks": [{"passed": True}]},
    }
    _stub_flatten_service(monkeypatch, result)
    response = _run(monkeypatch, projection_db, order_db, "--execute")
    assert response.exit_code == 0, response.output
    assert response.output.count("preserved_t=1") == 1
    stored = order_db["om_position_entries"].docs
    assert len(stored) == 1
    # 已有 t 标记保留（全 t → 保留 t）
    assert stored[0]["position_type"] == "t"
    assert order_db["om_entry_slices"].docs[0]["position_type"] == "t"


def test_activate_takeprofit_only_for_holdings_with_profile(monkeypatch):
    projection_db, order_db = _build_dbs(
        positions=[
            {"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.0},
            {"stock_code": "000002.SZ", "volume": 500, "avg_price": 9.0},
        ],
        profiles=[
            {
                "symbol": "000001",
                "tiers": [
                    {"level": 1, "price": 10.0, "manual_enabled": True},
                    {"level": 2, "price": 11.0, "manual_enabled": True},
                ],
            }
        ],
    )
    activated = []

    class _FakeLadder:
        def activate_takeprofit(self, code):
            activated.append(code)
            return True

    monkeypatch.setattr(
        backfill_module,
        "get_guardian_ladder_state",
        lambda: _FakeLadder(),
    )
    response = _run(
        monkeypatch,
        projection_db,
        order_db,
        "--activate-takeprofit",
        "--execute",
    )
    assert response.exit_code == 0, response.output
    assert activated == ["000001"]
    assert "skipped_no_profile=1" in response.output


def test_backfill_execute_does_not_activate_takeprofit(monkeypatch):
    projection_db, order_db = _build_dbs(
        positions=[{"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.0}],
    )
    result = {
        "position_entry_documents": [
            {
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "entry_slice_documents": [
            {
                "entry_slice_id": "slice_f",
                "entry_id": "entry_f",
                "symbol": "000001",
                "position_type": "base",
                "remaining_quantity": 300,
                "original_quantity": 300,
            }
        ],
        "flatten": {"invariant_checks": [{"passed": True}]},
    }
    _stub_flatten_service(monkeypatch, result)
    activated = []

    class _FakeLadder:
        def activate_takeprofit(self, code):
            activated.append(code)
            return True

    monkeypatch.setattr(
        backfill_module,
        "get_guardian_ladder_state",
        lambda: _FakeLadder(),
    )
    response = _run(monkeypatch, projection_db, order_db, "--execute")
    assert response.exit_code == 0, response.output
    assert activated == []
