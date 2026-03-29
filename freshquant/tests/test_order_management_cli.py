import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from freshquant.command.om_order import om_order_command_group


def test_om_order_submit_command_calls_submit_service(monkeypatch):
    captured = {}

    class FakeService:
        def submit_order(self, payload):
            captured.update(payload)
            return {"request_id": "req_cli_1", "internal_order_id": "ord_cli_1"}

    monkeypatch.setattr(
        "freshquant.command.om_order._get_order_submit_service",
        lambda: FakeService(),
    )

    runner = CliRunner()
    result = runner.invoke(
        om_order_command_group,
        [
            "submit",
            "--action",
            "buy",
            "--symbol",
            "600000.SH",
            "--price",
            "9.98",
            "--quantity",
            "300",
            "--source",
            "cli",
        ],
    )

    assert result.exit_code == 0
    assert captured["symbol"] == "600000"
    assert captured["action"] == "buy"
    assert "ord_cli_1" in result.output


def test_om_order_cancel_command_calls_cancel_service(monkeypatch):
    captured = {}

    class FakeService:
        def cancel_order(self, payload):
            captured.update(payload)
            return {
                "request_id": "req_cli_cancel_1",
                "internal_order_id": payload["internal_order_id"],
            }

    monkeypatch.setattr(
        "freshquant.command.om_order._get_order_submit_service",
        lambda: FakeService(),
    )

    runner = CliRunner()
    result = runner.invoke(
        om_order_command_group,
        [
            "cancel",
            "--internal-order-id",
            "ord_cancel_cli_1",
            "--source",
            "cli",
        ],
    )

    assert result.exit_code == 0
    assert captured["internal_order_id"] == "ord_cancel_cli_1"
    assert "req_cli_cancel_1" in result.output


class _FakeMaintenanceCollection:
    def __init__(self, rows=None, *, name, event_log):
        self.rows = [dict(item) for item in rows or []]
        self.name = name
        self.event_log = event_log
        self.delete_many_calls = []
        self.insert_many_calls = []

    def find(self, query=None):
        query = dict(query or {})
        return [dict(item) for item in self.rows if _matches_query(item, query)]

    def delete_many(self, query):
        query = dict(query or {})
        self.delete_many_calls.append(query)
        self.rows = [item for item in self.rows if not _matches_query(item, query)]
        self.event_log.append(f"delete_many:{self.name}")
        return SimpleNamespace(deleted_count=0)

    def insert_many(self, documents, ordered=False):
        docs = [dict(item) for item in documents]
        self.insert_many_calls.append(docs)
        self.rows.extend(docs)
        self.event_log.append(f"insert_many:{self.name}")
        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    def insert_one(self, document):
        doc = dict(document)
        self.rows.append(doc)
        self.event_log.append(f"insert_one:{self.name}")
        return SimpleNamespace(inserted_id=len(self.rows))


class _FakeMaintenanceDatabase:
    def __init__(self, collections=None, *, name="freshquant_order_management"):
        self.name = name
        self.event_log = []
        self._collections = {}
        for collection_name, rows in (collections or {}).items():
            self._collections[collection_name] = _FakeMaintenanceCollection(
                rows,
                name=collection_name,
                event_log=self.event_log,
            )

    def __getitem__(self, name):
        if name not in self._collections:
            self._collections[name] = _FakeMaintenanceCollection(
                [],
                name=name,
                event_log=self.event_log,
            )
        return self._collections[name]


class _FakeRebuildService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def build_from_truth(self, **kwargs):
        self.calls.append(kwargs)
        return {
            key: [dict(item) for item in value] if isinstance(value, list) else value
            for key, value in self.result.items()
        }


def _matches_query(document, query):
    for key, expected in (query or {}).items():
        if document.get(key) != expected:
            return False
    return True


def _load_rebuild_cli_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "script"
        / "maintenance"
        / "rebuild_order_ledger_v2.py"
    )
    assert (
        module_path.exists()
    ), "script/maintenance/rebuild_order_ledger_v2.py must exist"
    spec = importlib.util.spec_from_file_location(
        "test_order_management_cli_rebuild_script",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_rebuild_cli_without_execute_does_not_run_backup_purge_or_write(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
            "om_broker_orders": [{"broker_order_key": "legacy-1"}],
        }
    )
    service = _FakeRebuildService(
        {
            "broker_orders": 1,
            "execution_fills": 1,
            "position_entries": 0,
            "entry_slices": 0,
            "exit_allocations": 0,
            "reconciliation_gaps": 0,
            "reconciliation_resolutions": 0,
            "ingest_rejections": 0,
            "broker_order_documents": [{"broker_order_key": "70001"}],
            "execution_fill_documents": [{"execution_fill_id": "fill-1"}],
            "position_entry_documents": [],
            "entry_slice_documents": [],
            "exit_allocation_documents": [],
            "reconciliation_gap_documents": [],
            "reconciliation_resolution_documents": [],
            "ingest_rejection_documents": [],
            "unmatched_sell_trade_facts": [],
            "replay_warnings": [],
        }
    )
    backup_calls = []

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli, "_get_broker_truth_db", lambda: database, raising=False
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)
    monkeypatch.setattr(
        rebuild_cli,
        "_backup_database",
        lambda **kwargs: backup_calls.append(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--backup-db", "preview_backup_only", "--account-id", "acct-1"],
    )

    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["dry_run"] is True
    assert summary["execute"] is False
    assert summary["backup_db"] == "preview_backup_only"
    assert summary["backup_performed"] is False
    assert backup_calls == []
    assert database.event_log == []
    assert database["om_broker_orders"].rows == [{"broker_order_key": "legacy-1"}]


def test_rebuild_cli_execute_requires_backup_db(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1}],
            "xt_trades": [{"traded_id": "trade-1"}],
            "xt_positions": [{"stock_code": "600000.SH"}],
        }
    )
    service = _FakeRebuildService(
        {
            "broker_orders": 1,
            "execution_fills": 1,
            "position_entries": 0,
            "entry_slices": 0,
            "exit_allocations": 0,
            "reconciliation_gaps": 0,
            "reconciliation_resolutions": 0,
            "ingest_rejections": 0,
            "broker_order_documents": [],
            "execution_fill_documents": [],
            "position_entry_documents": [],
            "entry_slice_documents": [],
            "exit_allocation_documents": [],
            "reconciliation_gap_documents": [],
            "reconciliation_resolution_documents": [],
            "ingest_rejection_documents": [],
            "unmatched_sell_trade_facts": [],
            "replay_warnings": [],
        }
    )
    backup_calls = []

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli, "_get_broker_truth_db", lambda: database, raising=False
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)
    monkeypatch.setattr(
        rebuild_cli,
        "_backup_database",
        lambda **kwargs: backup_calls.append(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--execute"],
    )

    assert result.exit_code != 0
    assert "--execute requires --backup-db" in result.output
    assert backup_calls == []
    assert database.event_log == []


def test_rebuild_cli_execute_rejects_same_backup_db_name(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1}],
            "xt_trades": [{"traded_id": "trade-1"}],
            "xt_positions": [{"stock_code": "600000.SH"}],
        }
    )
    service = _FakeRebuildService(
        {
            "broker_orders": 1,
            "execution_fills": 1,
            "position_entries": 0,
            "entry_slices": 0,
            "exit_allocations": 0,
            "reconciliation_gaps": 0,
            "reconciliation_resolutions": 0,
            "ingest_rejections": 0,
            "broker_order_documents": [],
            "execution_fill_documents": [],
            "position_entry_documents": [],
            "entry_slice_documents": [],
            "exit_allocation_documents": [],
            "reconciliation_gap_documents": [],
            "reconciliation_resolution_documents": [],
            "ingest_rejection_documents": [],
            "unmatched_sell_trade_facts": [],
            "replay_warnings": [],
        }
    )
    backup_calls = []

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: database)
    monkeypatch.setattr(
        rebuild_cli, "_get_broker_truth_db", lambda: database, raising=False
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)
    monkeypatch.setattr(
        rebuild_cli,
        "_backup_database",
        lambda **kwargs: backup_calls.append(kwargs),
    )

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--execute", "--backup-db", "freshquant_order_management"],
    )

    assert result.exit_code != 0
    assert "--backup-db must differ from source database name" in result.output
    assert backup_calls == []
    assert database.event_log == []


def test_rebuild_cli_reads_broker_truth_from_projection_db(monkeypatch):
    rebuild_cli = _load_rebuild_cli_module()
    order_database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [],
            "xt_trades": [],
            "xt_positions": [],
            "om_broker_orders": [{"broker_order_key": "legacy-1"}],
        }
    )
    projection_database = _FakeMaintenanceDatabase(
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
        },
        name="freshquant",
    )
    service = _FakeRebuildService(
        {
            "broker_orders": 1,
            "execution_fills": 1,
            "position_entries": 0,
            "entry_slices": 0,
            "exit_allocations": 0,
            "reconciliation_gaps": 0,
            "reconciliation_resolutions": 0,
            "ingest_rejections": 0,
            "broker_order_documents": [{"broker_order_key": "70001"}],
            "execution_fill_documents": [{"execution_fill_id": "fill-1"}],
            "position_entry_documents": [],
            "entry_slice_documents": [],
            "exit_allocation_documents": [],
            "reconciliation_gap_documents": [],
            "reconciliation_resolution_documents": [],
            "ingest_rejection_documents": [],
            "unmatched_sell_trade_facts": [],
            "replay_warnings": [],
        }
    )

    monkeypatch.setattr(rebuild_cli, "_get_order_management_db", lambda: order_database)
    monkeypatch.setattr(
        rebuild_cli,
        "_get_broker_truth_db",
        lambda: projection_database,
        raising=False,
    )
    monkeypatch.setattr(rebuild_cli, "_get_rebuild_service", lambda: service)

    runner = CliRunner()
    result = runner.invoke(
        rebuild_cli.rebuild_order_ledger_v2_command,
        ["--dry-run", "--account-id", "acct-1"],
    )

    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["source_counts"] == {
        "xt_orders": 1,
        "xt_trades": 1,
        "xt_positions": 1,
    }
    assert order_database["om_broker_orders"].rows == [{"broker_order_key": "legacy-1"}]
    assert service.calls == [
        {
            "xt_orders": [{"order_id": 1, "account_id": "acct-1"}],
            "xt_trades": [{"traded_id": "trade-1", "account_id": "acct-1"}],
            "xt_positions": [{"stock_code": "600000.SH", "account_id": "acct-1"}],
        }
    ]
