from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import click

from freshquant.order_management.db import (
    ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS,
    get_order_management_db,
    get_projection_db,
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
    # flatten-cost-price 模式对账补单：为每个持仓生成重建买入请求与订单。
    ("om_order_requests", "order_request_documents"),
    ("om_orders", "order_documents"),
)
_SUMMARY_COUNT_KEYS = (
    "broker_orders",
    "execution_fills",
    "position_entries",
    "entry_slices",
    "clustered_entries",
    "mergeable_entry_gap",
    "non_default_lot_slices",
    "exit_allocations",
    "reconciliation_gaps",
    "reconciliation_resolutions",
    "auto_open_entries",
    "auto_close_allocations",
    "ingest_rejections",
    "rebuilt_open_order_requests",
)

# flatten-cost-price 模式额外清理的集合（随账本重建 purge）。
_FLATTEN_EXTRA_PURGE_COLLECTIONS = ("om_takeprofit_states",)
# flatten-cost-price 模式额外归档的辅助状态集合。
_FLATTEN_AUXILIARY_ARCHIVE_COLLECTION = "order_ledger_flatten_auxiliary_archive"
_FLATTEN_AUXILIARY_SOURCE_COLLECTIONS = ("om_takeprofit_states",)


def _get_order_management_db():
    return get_order_management_db()


def _get_broker_truth_db():
    return get_projection_db()


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


def _load_xt_positions(*, database, account_id=None):
    query = {}
    if account_id not in {None, ""}:
        query["account_id"] = str(account_id).strip()
    return list(database["xt_positions"].find(query))


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
    history_archiver=None,
    mode="replay",
):
    if dry_run and execute:
        raise click.UsageError("--dry-run and --execute cannot be used together")

    normalized_account_id = _normalize_optional_text(account_id)
    normalized_backup_db = _normalize_optional_text(backup_db)
    normalized_mode = str(mode or "replay").strip().lower()
    should_execute = bool(execute)

    if should_execute and normalized_account_id is not None:
        raise click.UsageError("--account-id is only allowed with dry-run")
    if should_execute and normalized_backup_db is None:
        raise click.UsageError("--execute requires --backup-db")

    provided_database = database is not None
    database = database if provided_database else _get_order_management_db()
    broker_truth_database = database if provided_database else _get_broker_truth_db()
    if should_execute and normalized_backup_db == _normalize_optional_text(
        getattr(database, "name", None)
    ):
        raise click.UsageError("--backup-db must differ from source database name")

    rebuild_service = (
        rebuild_service if rebuild_service is not None else _get_rebuild_service()
    )
    history_archiver = (
        history_archiver
        if history_archiver is not None
        else _archive_position_review_history
    )

    if normalized_mode == "flatten-cost-price":
        return _run_flatten_rebuild(
            dry_run=not should_execute,
            execute=should_execute,
            backup_db=normalized_backup_db,
            account_id=normalized_account_id,
            database=database,
            broker_truth_database=broker_truth_database,
            rebuild_service=rebuild_service,
            history_archiver=history_archiver,
        )

    truth_snapshots = _load_broker_truth(
        database=broker_truth_database,
        account_id=normalized_account_id,
    )
    rebuild_result = rebuild_service.build_from_truth(**truth_snapshots)
    purge_collections = list(ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS)
    backup_performed = False
    history_archive = None

    if should_execute:
        history_archive = history_archiver(
            business_database=broker_truth_database,
            order_database=database,
            include_business=True,
            include_order=True,
            reason="order_ledger_rebuild_before_purge",
        )
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
        "mode": "replay",
        "account_id": normalized_account_id,
        "dry_run": not should_execute,
        "execute": should_execute,
        "backup_db": normalized_backup_db,
        "backup_performed": backup_performed,
        "position_review_history_archive": history_archive,
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


def _run_flatten_rebuild(
    *,
    dry_run,
    execute,
    backup_db,
    account_id,
    database,
    broker_truth_database,
    rebuild_service,
    history_archiver,
):
    positions = _load_xt_positions(
        database=broker_truth_database,
        account_id=account_id,
    )
    rebuild_result = rebuild_service.build_flatten_from_positions(
        xt_positions=positions,
    )
    flatten_state = rebuild_result.get("flatten") or {}
    slices_by_symbol = flatten_state.get("slices_by_symbol") or {}
    purge_collections = list(ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS) + list(
        _FLATTEN_EXTRA_PURGE_COLLECTIONS
    )
    old_anchor_slices = _collect_old_slice_anchors(database)
    backup_performed = False
    history_archive = None
    auxiliary_archive = None

    if execute:
        history_archive = history_archiver(
            business_database=broker_truth_database,
            order_database=database,
            include_business=True,
            include_order=True,
            reason="order_ledger_flatten_rebuild_before_purge",
        )
        auxiliary_archive = _archive_flatten_auxiliary_state(
            database=database,
            reason="order_ledger_flatten_rebuild_before_purge",
        )
        _backup_database(
            database=database,
            backup_db_name=backup_db,
            collection_names=purge_collections,
        )
        backup_performed = True

    if execute:
        _purge_collections(database=database, collection_names=purge_collections)
        _write_rebuild_result(database=database, rebuild_result=rebuild_result)

    summary = {
        "mode": "flatten-cost-price",
        "account_id": account_id,
        "dry_run": dry_run,
        "execute": execute,
        "backup_db": backup_db,
        "backup_performed": backup_performed,
        "position_review_history_archive": history_archive,
        "flatten_auxiliary_archive": auxiliary_archive,
        "source_counts": {"xt_positions": len(positions)},
        "would_purge_collections": purge_collections,
        "purged_collections": purge_collections if execute else [],
        "flatten_entries_by_symbol": {
            symbol: [_flatten_entry_summary(item) for item in entries]
            for symbol, entries in sorted(
                (flatten_state.get("entries_by_symbol") or {}).items()
            )
        },
        "flatten_slices_by_symbol": {
            symbol: [_flatten_slice_summary(item) for item in slices]
            for symbol, slices in sorted(slices_by_symbol.items())
        },
        "flatten_invariant_checks": list(flatten_state.get("invariant_checks") or []),
        "old_anchor_slices_by_symbol": {
            symbol: [
                {
                    "entry_slice_id": item.get("entry_slice_id"),
                    "entry_id": item.get("entry_id"),
                    "guardian_price": item.get("guardian_price"),
                    "original_quantity": item.get("original_quantity"),
                    "remaining_quantity": item.get("remaining_quantity"),
                }
                for item in items
            ]
            for symbol, items in sorted(old_anchor_slices.items())
        },
        "anchor_replacement": _build_anchor_replacement(
            old_anchor_slices,
            slices_by_symbol,
        ),
        "acceptance": {
            "old_anchor_prices_still_present": _find_anchor_prices_present(
                database,
                old_anchor_slices,
            )
        },
    }
    for key in _SUMMARY_COUNT_KEYS:
        summary[key] = int(rebuild_result.get(key) or 0)
    return summary


def _flatten_entry_summary(entry):
    return {
        "entry_id": entry.get("entry_id"),
        "source_ref_type": entry.get("source_ref_type"),
        "symbol": entry.get("symbol"),
        "account_id": entry.get("account_id"),
        "entry_price": entry.get("entry_price"),
        "original_quantity": entry.get("original_quantity"),
        "remaining_quantity": entry.get("remaining_quantity"),
        "status": entry.get("status"),
    }


def _flatten_slice_summary(slice_document):
    return {
        "entry_slice_id": slice_document.get("entry_slice_id"),
        "entry_id": slice_document.get("entry_id"),
        "guardian_price": slice_document.get("guardian_price"),
        "original_quantity": slice_document.get("original_quantity"),
        "remaining_quantity": slice_document.get("remaining_quantity"),
        "status": slice_document.get("status"),
    }


def _collect_old_slice_anchors(database):
    """读取当前 om_entry_slices 作为“旧锚点”对照输入。"""

    try:
        rows = list(database["om_entry_slices"].find({}))
    except (KeyError, TypeError, AttributeError):
        return {}
    anchors: dict[str, list] = {}
    for item in rows:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            continue
        anchors.setdefault(symbol, []).append(dict(item))
    return anchors


def _build_anchor_replacement(old_anchor_slices, slices_by_symbol):
    replacement = {}
    for symbol, old_items in sorted(old_anchor_slices.items()):
        old_prices = sorted(
            {float(item.get("guardian_price") or 0.0) for item in old_items}
        )
        new_prices = sorted(
            {
                float(item.get("guardian_price") or 0.0)
                for item in slices_by_symbol.get(symbol, [])
            }
        )
        replacement[symbol] = {
            "old_anchor_prices": old_prices,
            "new_grid_prices": new_prices,
        }
    for symbol, new_items in sorted(slices_by_symbol.items()):
        if symbol in replacement:
            continue
        replacement[symbol] = {
            "old_anchor_prices": [],
            "new_grid_prices": sorted(
                {float(item.get("guardian_price") or 0.0) for item in new_items}
            ),
        }
    return replacement


def _find_anchor_prices_present(database, old_anchor_slices):
    """查询旧锚点价格当前是否仍存在于 om_entry_slices。"""

    present = {}
    try:
        collection = database["om_entry_slices"]
        for symbol, items in old_anchor_slices.items():
            anchor_prices = sorted(
                {float(item.get("guardian_price") or 0.0) for item in items}
            )
            found = []
            for price in anchor_prices:
                match = collection.find_one(
                    {
                        "symbol": symbol,
                        "guardian_price": price,
                    }
                )
                if match is not None:
                    found.append(price)
            present[symbol] = found
    except (KeyError, TypeError, AttributeError):
        return present
    return present


def _archive_flatten_auxiliary_state(*, database, reason):
    """rebuild 前把辅助状态集合快照进不可变归档，失败即中止。"""

    try:
        archive_collection = database[_FLATTEN_AUXILIARY_ARCHIVE_COLLECTION]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"flatten auxiliary archive unavailable: {exc}") from exc
    archived_at = datetime.now(timezone.utc).isoformat()
    archived = {}
    for collection_name in _FLATTEN_AUXILIARY_SOURCE_COLLECTIONS:
        try:
            documents = list(database[collection_name].find({}))
        except (KeyError, TypeError, AttributeError) as exc:
            raise RuntimeError(
                f"flatten auxiliary archive read failed for {collection_name}: {exc}"
            ) from exc
        archive_rows = []
        for document in documents:
            payload = _without_id(document)
            archive_key = _build_auxiliary_archive_key(
                collection_name,
                payload,
            )
            archive_rows.append(
                {
                    "archive_key": archive_key,
                    "source_collection": collection_name,
                    "archived_at": archived_at,
                    "archive_reason": reason,
                    "payload": payload,
                }
            )
        if archive_rows:
            archive_collection.insert_many(archive_rows, ordered=False)
        archived[collection_name] = len(archive_rows)
    return archived


def _build_auxiliary_archive_key(collection_name, payload):
    serialized = json.dumps(
        [collection_name, payload],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return f"fltaux_{hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:32]}"


def _without_id(document):
    return {key: value for key, value in dict(document or {}).items() if key != "_id"}


def _archive_position_review_history(**kwargs):
    from freshquant.order_management.position_review_archive import (
        backfill_position_review_history,
    )

    return backfill_position_review_history(dry_run=False, **kwargs)


@click.command(name="rebuild-order-ledger-v2")
@click.option("--dry-run", is_flag=True, help="Only print rebuild summary.")
@click.option(
    "--execute",
    is_flag=True,
    help="Enable destructive backup/purge/write flow.",
)
@click.option("--backup-db", default=None, help="Backup database name before purge.")
@click.option("--account-id", default=None, help="Optional broker account filter.")
@click.option(
    "--mode",
    type=click.Choice(["replay", "flatten-cost-price"]),
    default="replay",
    show_default=True,
    help="replay: 逐笔重建；flatten-cost-price: 成本价拍平重建。",
)
@click.option(
    "--verify",
    is_flag=True,
    help="重建后运行 allocation_integrity 只读校验，非零错误时退出码非 0。",
)
def rebuild_order_ledger_v2_command(
    dry_run, execute, backup_db, account_id, mode, verify
):
    summary = run_rebuild(
        dry_run=dry_run,
        execute=execute,
        backup_db=backup_db,
        account_id=account_id,
        mode=mode,
    )
    if verify:
        summary["integrity_verify"] = _run_integrity_verify()
    click.echo(json.dumps(summary, ensure_ascii=False))
    if verify and not (summary.get("integrity_verify") or {}).get("ok"):
        raise click.ClickException(
            "allocation integrity verify failed: "
            + json.dumps(summary.get("integrity_verify") or {}, ensure_ascii=False)
        )


def _run_integrity_verify(*, database=None):
    from freshquant.order_management.allocation_integrity import (
        find_exit_allocation_integrity_errors,
        summarize_integrity_errors,
    )
    from freshquant.order_management.repository import OrderManagementRepository

    database = database if database is not None else _get_order_management_db()
    repository = OrderManagementRepository(database=database)
    errors = find_exit_allocation_integrity_errors(
        position_entries=repository.list_position_entries(),
        entry_slices=repository.list_all_entry_slices(),
        exit_allocations=repository.list_exit_allocations(),
    )
    return summarize_integrity_errors(errors)


def main():
    rebuild_order_ledger_v2_command()


def _normalize_optional_text(value):
    normalized = str(value or "").strip()
    return normalized or None


if __name__ == "__main__":
    main()
