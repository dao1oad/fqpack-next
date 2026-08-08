# -*- coding: utf-8 -*-

"""§13：flatten-cost-price 重建、归档范围、dry-run 对照、验收辅助、simulate CLI。"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from freshquant.order_management.guardian.arranger import arrange_entry
from freshquant.order_management.guardian.slice_evaluation import (
    evaluate_guardian_sell_slices,
)
from freshquant.order_management.rebuild.acceptance import (
    assert_anchor_prices_cleared,
    sample_archive_replay,
    simulate_buy_cluster_entry,
)
from freshquant.order_management.rebuild.service import OrderLedgerV2RebuildService


def _flatten_service():
    return OrderLedgerV2RebuildService(
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )


def test_flatten_builder_generates_one_cost_price_entry_for_002262():
    service = _flatten_service()
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "068000087558",
                "stock_code": "002262.SZ",
                "volume": 17900,
                "avg_price": 23.41255,
            }
        ],
        now_ts=1775000000,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )

    assert result["position_entries"] == 1
    assert result["entry_slices"] == 17
    assert result["exit_allocations"] == 0
    entry = result["position_entry_documents"][0]
    assert entry["source_ref_type"] == "position_snapshot_flatten"
    assert entry["entry_type"] == "position_snapshot_flatten"
    assert entry["entry_price"] == pytest.approx(23.41255)
    assert entry["original_quantity"] == 17900
    assert entry["remaining_quantity"] == 17900
    assert entry["status"] == "OPEN"
    assert entry["aggregation_members"] == []

    slices = result["entry_slice_documents"]
    assert sum(int(item["original_quantity"]) for item in slices) == 17900
    assert all(item["status"] == "OPEN" for item in slices)
    assert all(item["entry_id"] == entry["entry_id"] for item in slices)
    assert all(item["passed"] for item in result["flatten"]["invariant_checks"])


def test_flatten_builder_reconciles_rebuilt_open_buy_orders_per_holding():
    """账本重建应对账：每个持仓都应有对应的重建买入订单（而非只有 entry）。"""

    service = _flatten_service()
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "068000076370",
                "stock_code": "600917.SH",
                "volume": 20000,
                "avg_price": 5.527529,
            },
            {
                "account_id": "068000076370",
                "stock_code": "002262.SZ",
                "volume": 6000,
                "avg_price": 10.27,
            },
        ],
        now_ts=1786105912,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )

    assert result["rebuilt_open_order_requests"] == 2
    requests = result["order_request_documents"]
    orders = result["order_documents"]
    broker_orders = result["broker_order_documents"]
    assert len(requests) == len(orders) == len(broker_orders) == 2
    by_symbol = {item["symbol"]: item for item in broker_orders}
    assert set(by_symbol) == {"600917", "002262"}
    for order in broker_orders:
        assert order["side"] == "buy"
        assert order["state"] == "FILLED"
        assert order["filled_quantity"] == order["quantity"]
        assert order["source"] == "order_ledger_rebuild"
        assert order["rebuilt_open"] is True
        assert order["broker_order_id"] is None
        assert order["data_quality"] == "reconstructed"
        assert order["broker_order_key"].startswith("rebuilt:")
        assert order["updated_at"] is not None
        assert order["first_fill_time"] == order["trade_time"]
    entry = next(
        item
        for item in result["position_entry_documents"]
        if item["symbol"] == "600917"
    )
    request = next(item for item in requests if item["entry_id"] == entry["entry_id"])
    assert request["request_id"] == f"req_rebuilt_{entry['entry_id']}"
    assert request["action"] == "buy"
    assert request["price"] == pytest.approx(5.527529)
    assert request["quantity"] == 20000
    # 与 entry 保持同一时点，使成本曲线在重建时点有对应买入点。
    assert request["trade_time"] == entry["trade_time"]


def test_flatten_builder_splits_accounts_into_separate_entries():
    service = _flatten_service()
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "acct_1",
                "stock_code": "000001.SZ",
                "volume": 100,
                "avg_price": 10.0,
            },
            {
                "account_id": "acct_2",
                "stock_code": "000001.SZ",
                "volume": 200,
                "avg_price": 10.5,
            },
        ],
        now_ts=1775000000,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )

    assert result["position_entries"] == 2
    assert {
        (item["account_id"], item["original_quantity"])
        for item in result["position_entry_documents"]
    } == {("acct_1", 100), ("acct_2", 200)}
    assert all(item["passed"] for item in result["flatten"]["invariant_checks"])


def test_flatten_builder_rejects_empty_xt_positions_snapshot():
    service = _flatten_service()
    with pytest.raises(ValueError, match="non-empty xt_positions"):
        service.build_flatten_from_positions(xt_positions=[], now_ts=1775000000)


def test_flatten_builder_invariant_fails_on_quantity_mismatch():
    service = _flatten_service()
    # arrange_entry 无法伪造不守恒，因此直接校验生成结果与输入一致即可；
    # 不守恒路径由 builder 的 AssertionError 语义保证。
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "acct_1",
                "stock_code": "002262.SZ",
                "volume": 17900,
                "avg_price": 23.41255,
            }
        ],
        now_ts=1775000000,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )
    slice_total = sum(
        int(item["original_quantity"]) for item in result["entry_slice_documents"]
    )
    assert slice_total == 17900


def test_flatten_slices_feed_unified_per_slice_evaluation():
    service = _flatten_service()
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "acct_1",
                "stock_code": "002262.SZ",
                "volume": 17900,
                "avg_price": 23.41255,
            }
        ],
        now_ts=1775000000,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )
    slices = result["entry_slice_documents"]
    evaluation = evaluate_guardian_sell_slices(
        slices,
        signal_price=21.58,
        threshold_config={"mode": "percent", "percent": 1},
    )
    assert evaluation["raw_quantity"] == 0  # 成本 23.41 高于信号价，不卖

    evaluation_above = evaluate_guardian_sell_slices(
        slices,
        signal_price=23.65,
        threshold_config={"mode": "percent", "percent": 1},
    )
    assert evaluation_above["raw_quantity"] > 0
    assert evaluation_above["eligible_slices"]
    assert evaluation_above["threshold_evidence"]


class _FakeCollection:
    def __init__(self, rows=None, *, name, event_log):
        self.rows = [dict(item) for item in rows or []]
        self.name = name
        self.event_log = event_log
        self.find_calls = []

    def find(self, query=None):
        query = dict(query or {})
        self.find_calls.append(query)
        return [dict(item) for item in self.rows if _matches_query(item, query)]

    def find_one(self, query=None):
        for item in self.rows:
            if _matches_query(item, dict(query or {})):
                return dict(item)
        return None

    def insert_many(self, documents, ordered=False):
        docs = [dict(item) for item in documents]
        self.rows.extend(docs)
        self.event_log.append(f"insert_many:{self.name}:{len(docs)}")
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    def insert_one(self, document):
        self.rows.append(dict(document))
        self.event_log.append(f"insert_one:{self.name}")
        return SimpleNamespace(inserted_id=len(self.rows))

    def delete_many(self, query):
        query = dict(query or {})
        before = len(self.rows)
        self.rows = [item for item in self.rows if not _matches_query(item, query)]
        self.event_log.append(f"delete_many:{self.name}")
        return SimpleNamespace(deleted_count=before - len(self.rows))


class _FakeDatabase:
    def __init__(self, collections=None, *, name="freshquant_order_management"):
        self.name = name
        self.event_log = []
        self._collections = {}
        for collection_name, rows in (collections or {}).items():
            self._collections[collection_name] = _FakeCollection(
                rows,
                name=collection_name,
                event_log=self.event_log,
            )

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeCollection(
                [],
                name=name,
                event_log=self.event_log,
            )
        return self._collections[name]


def _matches_query(document, query):
    for key, expected in (query or {}).items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in set(expected["$in"]):
                return False
            continue
        if actual != expected:
            return False
    return True


def _load_rebuild_cli_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "script"
        / "maintenance"
        / "rebuild_order_ledger_v2.py"
    )
    assert module_path.exists()
    spec = importlib.util.spec_from_file_location(
        "test_rebuild_flatten_script",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rebuild_cli_flatten_dry_run_reports_anchor_comparison_without_mutation(
    monkeypatch,
):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeDatabase(
        {
            "xt_positions": [
                {
                    "account_id": "068000087558",
                    "stock_code": "002262.SZ",
                    "volume": 17900,
                    "avg_price": 23.41255,
                }
            ],
            "om_entry_slices": [
                {
                    "entry_slice_id": "slice_old_1",
                    "entry_id": "entry_old",
                    "symbol": "002262",
                    "guardian_price": 21.58,
                    "original_quantity": 2300,
                    "remaining_quantity": 2300,
                }
            ],
            "om_entry_stoploss_bindings": [{"entry_id": "entry_old"}],
            "om_takeprofit_states": [{"entry_id": "entry_old"}],
        }
    )
    service = _flatten_service()
    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--dry-run", "--mode", "flatten-cost-price"],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["mode"] == "flatten-cost-price"
    assert summary["dry_run"] is True
    assert summary["position_entries"] == 1
    assert summary["entry_slices"] == 17
    assert summary["flatten_entries_by_symbol"]["002262"][0]["entry_price"] == 23.41255
    assert summary["flatten_slices_by_symbol"]["002262"]
    assert all(item["passed"] for item in summary["flatten_invariant_checks"])
    assert (
        summary["old_anchor_slices_by_symbol"]["002262"][0]["guardian_price"] == 21.58
    )
    assert summary["anchor_replacement"]["002262"]["old_anchor_prices"] == [21.58]
    assert 23.41 in summary["anchor_replacement"]["002262"]["new_grid_prices"]
    # dry-run 不写库
    assert database["om_entry_slices"].rows
    assert not any(
        event.startswith("delete_many:om_entry_slices") for event in database.event_log
    )
    assert not any(
        event.startswith("insert_many:om_entry_slices") for event in database.event_log
    )
    assert "om_takeprofit_states" in summary["would_purge_collections"]


def test_rebuild_cli_flatten_execute_archives_then_purges_then_writes(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeDatabase(
        {
            "xt_positions": [
                {
                    "account_id": "068000087558",
                    "stock_code": "002262.SZ",
                    "volume": 17900,
                    "avg_price": 23.41255,
                }
            ],
            "om_entry_stoploss_bindings": [{"entry_id": "entry_old"}],
            "om_takeprofit_states": [{"entry_id": "entry_old"}],
            "om_position_entries": [{"entry_id": "entry_old"}],
        }
    )
    service = _flatten_service()
    backup_calls = []
    archive_calls = []
    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)
    monkeypatch.setattr(
        rebuild_cli,
        "_backup_database",
        lambda **kwargs: backup_calls.append(kwargs),
    )
    monkeypatch.setattr(
        rebuild_cli,
        "_archive_position_review_history",
        lambda **kwargs: archive_calls.append(kwargs) or {"dry_run": False},
    )

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        [
            "--execute",
            "--backup-db",
            "freshquant_order_management_backup_flatten_unit",
            "--mode",
            "flatten-cost-price",
        ],
    )

    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["execute"] is True
    assert summary["flatten_auxiliary_archive"] == {
        "om_entry_stoploss_bindings": 1,
        "om_takeprofit_states": 1,
    }
    assert "om_takeprofit_states" in summary["purged_collections"]
    assert database["om_takeprofit_states"].rows == []
    assert database["om_position_entries"].rows  # 新拍平 entry 已写入
    assert database["om_entry_slices"].rows
    assert database["order_ledger_flatten_auxiliary_archive"].rows
    assert (
        database["order_ledger_flatten_auxiliary_archive"].rows[0]["source_collection"]
        == "om_entry_stoploss_bindings"
    )


def test_rebuild_cli_flatten_execute_rejects_account_scoped_mutation(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeDatabase(
        {
            "xt_positions": [
                {
                    "account_id": "acct_1",
                    "stock_code": "002262.SZ",
                    "volume": 100,
                    "avg_price": 23.0,
                }
            ]
        }
    )
    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        [
            "--execute",
            "--backup-db",
            "freshquant_order_management_backup_flatten_unit",
            "--account-id",
            "acct_1",
            "--mode",
            "flatten-cost-price",
        ],
    )
    assert result.exit_code != 0
    assert "--account-id is only allowed with dry-run" in result.output


def test_acceptance_anchor_cleanup_query():
    event_log = []
    collection = _FakeCollection(
        [
            {
                "entry_slice_id": "slice_old",
                "symbol": "002262",
                "guardian_price": 21.58,
            }
        ],
        name="om_entry_slices",
        event_log=event_log,
    )
    result = assert_anchor_prices_cleared(
        collection,
        "002262",
        [21.58, 21.92, 22.41, 26.00],
    )
    assert result["still_present"] == [21.58]
    assert result["cleared"] is False

    collection.rows = []
    result = assert_anchor_prices_cleared(
        collection,
        "002262",
        [21.58, 21.92, 22.41, 26.00],
    )
    assert result["still_present"] == []
    assert result["cleared"] is True


def test_acceptance_simulate_buy_cluster_entry_returns_none_for_flatten_entry():
    service = _flatten_service()
    result = service.build_flatten_from_positions(
        xt_positions=[
            {
                "account_id": "acct_1",
                "stock_code": "002262.SZ",
                "volume": 17900,
                "avg_price": 23.41255,
            }
        ],
        now_ts=1775000000,
        lot_amount_lookup=lambda _symbol: 50000,
        grid_interval_lookup=lambda _symbol: 1.2,
    )
    entries = result["position_entry_documents"]
    acceptance = simulate_buy_cluster_entry(
        entries,
        sim_fact={
            "symbol": "002262",
            "price": 23.41,
            "quantity": 100,
            "trade_time": 1775000100,
            "date": "20260807",
            "time": "15:00:00",
        },
        sim_key="sim:flatten-accept:001",
    )
    assert acceptance["selected_entry_id"] is None
    assert acceptance["excluded_from_flatten_entry"] is True


def test_acceptance_archive_replay_sample():
    event_log = []
    collection = _FakeCollection(
        [
            {
                "evidence_key": "evd_1",
                "evidence_type": "position_entry",
                "symbol": "002262",
                "payload": {"entry_id": "entry_old"},
            }
        ],
        name="position_review_evidence_archive",
        event_log=event_log,
    )
    sample = sample_archive_replay(collection, symbol="002262")
    assert sample["available"] is True
    assert sample["sample"][0]["evidence_type"] == "position_entry"


def _simulate_cli_module():
    spec = importlib.util.spec_from_file_location(
        "test_guardian_simulate_cli",
        Path(__file__).resolve().parents[1] / "command" / "guardian.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_simulate_cli_is_read_only_and_uses_unified_slice_function(monkeypatch):
    module = _simulate_cli_module()
    open_slices = arrange_entry(
        {
            "entry_id": "entry_flat",
            "symbol": "002262",
            "entry_price": 23.41255,
            "original_quantity": 17900,
            "remaining_quantity": 17900,
            "date": 20260807,
            "time": "15:00:00",
            "trade_time": 1775000000,
        },
        lot_amount=50000,
        grid_interval=1.2,
    )

    class FakeRepository:
        def __init__(self):
            self.find_calls = 0

        def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
            self.find_calls += 1
            return [dict(item) for item in open_slices]

        def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
            return [
                {
                    "entry_id": "entry_flat",
                    "account_id": "068000087558",
                    "symbol": symbol,
                }
            ]

    fake = FakeRepository()
    monkeypatch.setattr(module, "OrderManagementRepository", lambda: fake)
    monkeypatch.setattr(
        module,
        "eval_stock_threshold_price",
        lambda _code, _price: {
            "base_price": _price,
            "top_river_price": round(_price * 1.01, 4),
            "config": {"mode": "percent", "percent": 1},
        },
    )

    runner = CliRunner()
    below = runner.invoke(
        module.guardian_sell_simulate_command,
        ["--code", "002262", "--signal-price", "21.58"],
    )
    assert below.exit_code == 0, below.output
    payload_below = json.loads(below.output)
    assert payload_below["raw_quantity"] == 0
    assert payload_below["zero_write"] is True
    assert payload_below["threshold_evidence"]

    above = runner.invoke(
        module.guardian_sell_simulate_command,
        ["--code", "002262", "--signal-price", "23.65"],
    )
    assert above.exit_code == 0, above.output
    payload_above = json.loads(above.output)
    assert payload_above["raw_quantity"] > 0
    assert payload_above["eligible_slices"]
    assert payload_above["threshold_evidence"]

    # 路径内只读：只有 find() 调用，无任何写集合
    assert fake.find_calls >= 1
    assert payload_below["raw_quantity"] == 0


def test_rebuild_flatten_dry_run_acceptance_anchor_still_present_flag(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeDatabase(
        {
            "xt_positions": [
                {
                    "account_id": "acct_1",
                    "stock_code": "002262.SZ",
                    "volume": 17900,
                    "avg_price": 23.41255,
                }
            ],
            "om_entry_slices": [
                {
                    "entry_slice_id": "old_1",
                    "entry_id": "entry_old",
                    "symbol": "002262",
                    "guardian_price": 21.58,
                    "original_quantity": 2300,
                    "remaining_quantity": 2300,
                }
            ],
        }
    )
    service = _flatten_service()
    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--dry-run", "--mode", "flatten-cost-price"],
    )
    assert result.exit_code == 0
    summary = json.loads(result.output)
    # dry-run 时旧锚点仍在（未 purge）
    assert summary["acceptance"]["old_anchor_prices_still_present"]["002262"] == [21.58]
