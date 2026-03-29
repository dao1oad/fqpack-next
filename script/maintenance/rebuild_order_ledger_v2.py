from __future__ import annotations

import json

import click

from freshquant.order_management.db import (
    ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS,
    get_order_management_db,
)
from freshquant.order_management.rebuild import OrderLedgerV2RebuildService

_BROKER_TRUTH_COLLECTIONS = ("xt_orders", "xt_trades", "xt_positions")
_REBUILD_RESULT_COLLECTIONS = (
    ("om_broker_orders", "broker_order_documents"),
    ("om_execution_fills", "execution_fill_documents"),
    ("om_position_entries", "position_entry_documents"),
    ("om_entry_slices", "entry_slice_documents"),
    ("om_exit_allocations", "exit_allocation_documents"),
    ("om_reconciliation_gaps", "reconciliation_gap_documents"),
    ("om_reconciliation_resolutions", "reconciliation_resolution_documents"),
    ("om_ingest_rejections", "ingest_rejection_documents"),
)
_SUMMARY_COUNT_KEYS = (
    "broker_orders",
    "execution_fills",
    "position_entries",
    "entry_slices",
    "exit_allocations",
    "reconciliation_gaps",
    "reconciliation_resolutions",
    "auto_open_entries",
    "auto_close_allocations",
    "ingest_rejections",
)


def _get_order_management_db():
    return get_order_management_db()


def _get_rebuild_service():
    return OrderLedgerV2RebuildService()


def _load_broker_truth(*, database, account_id=None):
    query = {}
    if account_id not in {None, ""}:
        query["account_id"] = str(account_id).strip()

    snapshots = {}
    for collection_name in _BROKER_TRUTH_COLLECTIONS:
        snapshots[collection_name] = list(database[collection_name].find(query))
    return snapshots


def _backup_database(*, database, backup_db_name, collection_names):
    if backup_db_name in {None, ""}:
        return
    if not hasattr(database, "client"):
        raise ValueError("database does not expose client for backup")

    target_database = database.client[str(backup_db_name).strip()]
    for collection_name in collection_names:
        documents = list(database[collection_name].find({}))
        target_database[collection_name].delete_many({})
        if documents:
            target_database[collection_name].insert_many(documents, ordered=False)


def _purge_collections(*, database, collection_names):
    for collection_name in collection_names:
        database[collection_name].delete_many({})


def _write_rebuild_result(*, database, rebuild_result):
    for collection_name, document_key in _REBUILD_RESULT_COLLECTIONS:
        documents = list(rebuild_result.get(document_key) or [])
        if documents:
            database[collection_name].insert_many(documents, ordered=False)


def run_rebuild(
    *,
    dry_run=False,
    execute=False,
    backup_db=None,
    account_id=None,
    database=None,
    rebuild_service=None,
):
    if dry_run and execute:
        raise click.UsageError("--dry-run and --execute cannot be used together")

    normalized_account_id = _normalize_optional_text(account_id)
    normalized_backup_db = _normalize_optional_text(backup_db)
    should_execute = bool(execute)

    if should_execute and normalized_account_id is not None:
        raise click.UsageError("--account-id is only allowed with dry-run")
    if should_execute and normalized_backup_db is None:
        raise click.UsageError("--execute requires --backup-db")

    database = database if database is not None else _get_order_management_db()
    if should_execute and normalized_backup_db == _normalize_optional_text(
        getattr(database, "name", None)
    ):
        raise click.UsageError("--backup-db must differ from source database name")

    rebuild_service = (
        rebuild_service if rebuild_service is not None else _get_rebuild_service()
    )

    truth_snapshots = _load_broker_truth(
        database=database,
        account_id=normalized_account_id,
    )
    rebuild_result = rebuild_service.build_from_truth(**truth_snapshots)
    purge_collections = list(ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS)
    backup_performed = False

    if should_execute:
        _backup_database(
            database=database,
            backup_db_name=normalized_backup_db,
            collection_names=purge_collections,
        )
        backup_performed = True

    if should_execute:
        _purge_collections(database=database, collection_names=purge_collections)
        _write_rebuild_result(database=database, rebuild_result=rebuild_result)

    summary = {
        "account_id": normalized_account_id,
        "dry_run": not should_execute,
        "execute": should_execute,
        "backup_db": normalized_backup_db,
        "backup_performed": backup_performed,
        "source_counts": {
            collection_name: len(truth_snapshots.get(collection_name) or [])
            for collection_name in _BROKER_TRUTH_COLLECTIONS
        },
        "would_purge_collections": purge_collections,
        "purged_collections": purge_collections if should_execute else [],
    }
    for key in _SUMMARY_COUNT_KEYS:
        summary[key] = int(rebuild_result.get(key) or 0)
    return summary


@click.command(name="rebuild-order-ledger-v2")
@click.option("--dry-run", is_flag=True, help="Only print rebuild summary.")
@click.option(
    "--execute",
    is_flag=True,
    help="Enable destructive backup/purge/write flow.",
)
@click.option("--backup-db", default=None, help="Backup database name before purge.")
@click.option("--account-id", default=None, help="Optional broker account filter.")
def rebuild_order_ledger_v2_command(dry_run, execute, backup_db, account_id):
    summary = run_rebuild(
        dry_run=dry_run,
        execute=execute,
        backup_db=backup_db,
        account_id=account_id,
    )
    click.echo(json.dumps(summary, ensure_ascii=False))


def main():
    rebuild_order_ledger_v2_command()


def _normalize_optional_text(value):
    normalized = str(value or "").strip()
    return normalized or None


if __name__ == "__main__":
    main()
