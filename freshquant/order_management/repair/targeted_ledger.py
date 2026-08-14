from __future__ import annotations

import hashlib
import os
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from bson import json_util
from pymongo.errors import DuplicateKeyError

TARGETED_REPAIR_PLAN_SCHEMA_VERSION = 1
TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION = 1

_FIX_504_ACCOUNT_ID = "068000087558"
_FIX_504_SYMBOLS = ("600917", "688772")
_FIX_504_TRADING_DAYS = (20260528, 20260804, 20260805)
_FIX_504_600917_OWNER = "ord_5a9cf34c627e43abbf4f0297b6b876e7"
_FIX_504_600917_KEY = "account:068000087558:day:20260528:sysid:579"
_FIX_504_688772_BUY_OWNER = "ord_broker_1a67aaff23c42ba4622397fb"
_FIX_504_688772_BUY_KEY = "account:068000087558:day:20260804:sysid:557"
_FIX_504_688772_SELL_OWNER = "ord_edc5fbce00c7475c822dd2cbbe9cdb1d"
_FIX_504_688772_SELL_BROKER_ORDER_ID = "1477443586"
_FIX_504_688772_SELL_SYSID = "362"
_FIX_504_688772_SELL_KEY = "account:068000087558:day:20260805:sysid:362"

_MUTABLE_ORDER_COLLECTIONS = {
    "om_orders",
    "om_broker_orders",
    "om_execution_fills",
    "om_trade_facts",
    "om_position_entries",
    "om_entry_slices",
    "om_exit_allocations",
    "om_reconciliation_gaps",
    "om_reconciliation_resolutions",
    "om_ingest_rejections",
    "om_external_candidates",
}
_READ_ONLY_ORDER_COLLECTIONS = {
    "om_order_requests",
    "om_order_events",
    "om_execution_history_archive",
    "position_review_evidence_archive",
}
_READ_ONLY_BUSINESS_COLLECTIONS = {
    "xt_orders",
    "xt_trades",
    "xt_positions",
    "stock_orders",
}


class TargetedRepairError(RuntimeError):
    pass


class InvalidRepairPlan(TargetedRepairError):
    pass


class PlanFileHashMismatch(TargetedRepairError):
    pass


class ManifestHashMismatch(TargetedRepairError):
    pass


class PreimageHashMismatch(TargetedRepairError):
    pass


class RepairLockConflict(TargetedRepairError):
    pass


class DeploymentShaMismatch(TargetedRepairError):
    pass


class RepairMixedState(TargetedRepairError):
    pass


class RepairRollbackIncomplete(TargetedRepairError):
    pass


def stage_targeted_repair(
    *,
    plan: Mapping[str, Any],
    databases: Mapping[str, Any],
    plan_file_sha256: str,
) -> dict[str, Any]:
    normalized_plan = _normalize_plan(plan)
    _validate_databases(databases)
    normalized_plan_file_sha256 = _normalize_sha256(
        plan_file_sha256,
        label="plan file sha256",
    )

    staged_changes = []
    for change in normalized_plan["changes"]:
        current_document = _load_current_document(change, databases)
        if not _values_equal(current_document, change["before_document"]):
            raise PreimageHashMismatch(
                "current document does not match the plan before_document for "
                f"{change['store']}.{change['collection']} "
                f"change_id={change['change_id']}"
            )

        staged_change = deepcopy(change)
        staged_change["before_document"] = deepcopy(current_document)
        if not _is_mutation(change):
            staged_change["after_document"] = deepcopy(current_document)
        staged_changes.append(staged_change)

    manifest = {
        "schema_version": TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION,
        "repair_id": normalized_plan["repair_id"],
        "target_main_sha": normalized_plan["target_main_sha"],
        "reason": normalized_plan["reason"],
        "scope": deepcopy(normalized_plan["scope"]),
        "plan_file_sha256": normalized_plan_file_sha256,
        "plan_hash": build_repair_plan_hash(normalized_plan),
        "preimage_hash": _snapshot_hash(staged_changes, "before_document"),
        "postimage_hash": _snapshot_hash(staged_changes, "after_document"),
        "changes": staged_changes,
        "generated_at": _utc_now(),
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    return manifest


def execute_targeted_repair(
    *,
    plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
    expected_plan_file_sha256: str,
    expected_plan_hash: str,
    expected_preimage_hash: str,
    expected_manifest_hash: str,
    deployed_main_sha: str,
    backup_dir: str | Path,
) -> dict[str, Any]:
    normalized_plan = _normalize_plan(plan)
    normalized_manifest = _validate_manifest(manifest)
    _validate_databases(databases)
    _assert_manifest_matches_plan(normalized_manifest, normalized_plan)
    _assert_expected_hash(
        expected_plan_file_sha256,
        normalized_manifest["plan_file_sha256"],
        PlanFileHashMismatch,
        "plan file sha256",
    )
    _assert_expected_hash(
        expected_plan_hash,
        normalized_manifest["plan_hash"],
        ManifestHashMismatch,
        "plan hash",
    )
    _assert_expected_hash(
        expected_preimage_hash,
        normalized_manifest["preimage_hash"],
        PreimageHashMismatch,
        "preimage hash",
    )
    _assert_expected_hash(
        expected_manifest_hash,
        normalized_manifest["manifest_hash"],
        ManifestHashMismatch,
        "manifest hash",
    )
    normalized_deployed_main_sha = _normalize_git_sha(
        deployed_main_sha,
        label="deployed main sha",
    )
    if normalized_deployed_main_sha != normalized_manifest["target_main_sha"]:
        raise DeploymentShaMismatch(
            "deployed main sha does not match the approved repair target_main_sha"
        )

    backup_root = Path(backup_dir)
    with _exclusive_lock(backup_root / ".apply.lock"):
        states = _require_known_change_states(normalized_manifest, databases)
        mutation_states = _mutation_state_rows(normalized_manifest, states)
        if mutation_states and all(
            item["state"] == "postimage" for item in mutation_states
        ):
            _validate_backup_bundle(normalized_manifest, backup_root)
            return _summary(normalized_manifest, status="already_applied")

        if any(item["state"] == "postimage" for item in mutation_states):
            raise RepairMixedState(
                "first apply requires every mutation to match the approved preimage; "
                "mixed preimage/postimage state must be handled by explicit restore"
            )

        _persist_backup_bundle(normalized_manifest, backup_root)
        _validate_backup_bundle(normalized_manifest, backup_root)

        # Re-read the whole closure after the durable backup and immediately before
        # the first write. Any drift blocks the repair without touching Mongo.
        rechecked_states = _require_known_change_states(normalized_manifest, databases)
        if any(
            item["state"] != "preimage"
            for item in _mutation_state_rows(normalized_manifest, rechecked_states)
        ):
            raise RepairMixedState(
                "repair state changed after backup creation and before the first write"
            )

        applied_changes = []
        try:
            for change in normalized_manifest["changes"]:
                if not _is_mutation(change):
                    continue
                _write_change(
                    change,
                    databases=databases,
                    expected_field="before_document",
                    target_field="after_document",
                )
                applied_changes.append(change)
            if (
                _current_snapshot_hash(normalized_manifest, databases)
                != normalized_manifest["postimage_hash"]
            ):
                raise TargetedRepairError(
                    "repair writes completed but current scoped state does not match "
                    "the approved postimage hash"
                )
        except Exception as exc:
            rollback_failures = _rollback_applied_changes(
                applied_changes,
                databases=databases,
            )
            if rollback_failures:
                raise RepairRollbackIncomplete(
                    "repair apply failed and compensation could not restore every "
                    "document; keep all write surfaces stopped; failures="
                    + ",".join(rollback_failures)
                ) from exc
            raise TargetedRepairError(
                "repair apply failed; every document written by this invocation was "
                "restored to its approved preimage"
            ) from exc
    return _summary(normalized_manifest, status="applied")


def preview_targeted_restore(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
    backup_dir: str | Path,
) -> dict[str, Any]:
    normalized_manifest = _validate_manifest(manifest)
    _validate_databases(databases)
    _validate_backup_bundle(normalized_manifest, Path(backup_dir))
    states = _change_states(normalized_manifest, databases)
    unknown = [item for item in states if item["state"] == "unknown"]
    return {
        **_summary(normalized_manifest, status="restore_preview"),
        "current_hash": _current_snapshot_hash(normalized_manifest, databases),
        "restorable": not unknown,
        "change_states": states,
    }


def restore_targeted_repair(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
    expected_manifest_hash: str,
    expected_current_hash: str,
    backup_dir: str | Path,
) -> dict[str, Any]:
    normalized_manifest = _validate_manifest(manifest)
    _validate_databases(databases)
    _assert_expected_hash(
        expected_manifest_hash,
        normalized_manifest["manifest_hash"],
        ManifestHashMismatch,
        "manifest hash",
    )
    lock_root = Path(backup_dir)
    _validate_backup_bundle(normalized_manifest, lock_root)
    with _exclusive_lock(lock_root / ".restore.lock"):
        states = _require_known_change_states(normalized_manifest, databases)
        current_hash = _current_snapshot_hash(normalized_manifest, databases)
        _assert_expected_hash(
            expected_current_hash,
            current_hash,
            PreimageHashMismatch,
            "restore current hash",
        )
        if all(item["state"] == "preimage" for item in states):
            return _summary(normalized_manifest, status="already_restored")
        for change, state in reversed(
            list(zip(normalized_manifest["changes"], states, strict=True))
        ):
            if state["state"] == "preimage":
                continue
            _write_change(
                change,
                databases=databases,
                expected_field="after_document",
                target_field="before_document",
            )
        if (
            _current_snapshot_hash(normalized_manifest, databases)
            != normalized_manifest["preimage_hash"]
        ):
            raise TargetedRepairError(
                "restore writes completed but current scoped state does not match "
                "the approved preimage hash"
            )
    return _summary(normalized_manifest, status="restored")


def verify_targeted_repair(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_manifest = _validate_manifest(manifest)
    _validate_databases(databases)
    rows = [
        {
            "change": change,
            "document": _load_current_document(change, databases),
        }
        for change in normalized_manifest["changes"]
    ]
    checks: list[dict[str, Any]] = []

    postimage_mismatches = [
        row["change"]["change_id"]
        for row in rows
        if not _values_equal(row["document"], row["change"]["after_document"])
    ]
    _add_verification_check(
        checks,
        "manifest_postimage",
        not postimage_mismatches,
        checked_documents=len(rows),
        mismatched_change_ids=postimage_mismatches,
    )

    live_orders = [
        *_fixed_order_scope_documents(
            databases,
            collection="om_orders",
            symbol="600917",
            trading_days=(20260528,),
        ),
        *_fixed_order_scope_documents(
            databases,
            collection="om_orders",
            symbol="688772",
            trading_days=(20260804, 20260805),
        ),
    ]
    expected_order_ids = {
        _hash_value(row["change"]["document_id"])
        for row in rows
        if row["change"]["store"] == "order"
        and row["change"]["collection"] == "om_orders"
        and row["change"]["after_document"] is not None
    }
    live_order_ids = {_hash_value(document.get("_id")) for document in live_orders}
    _add_verification_check(
        checks,
        "orders_fixed_live_scope",
        live_order_ids == expected_order_ids,
        expected_document_count=len(expected_order_ids),
        live_document_count=len(live_order_ids),
        unexpected_document_ids=sorted(live_order_ids - expected_order_ids),
        missing_document_ids=sorted(expected_order_ids - live_order_ids),
    )

    broker_600917 = _fixed_order_scope_documents(
        databases,
        collection="om_broker_orders",
        symbol="600917",
        trading_days=(20260528,),
    )
    order_600917 = broker_600917[0] if len(broker_600917) == 1 else None
    _add_verification_check(
        checks,
        "broker_order_600917",
        order_600917 is not None
        and _document_side(order_600917) == "buy"
        and order_600917.get("internal_order_id") == _FIX_504_600917_OWNER
        and order_600917.get("broker_order_key") == _FIX_504_600917_KEY
        and _integer_value(order_600917.get("filled_quantity")) == 38_700
        and _integer_value(order_600917.get("fill_count")) == 15
        and _decimal_value(order_600917.get("avg_filled_price")) == Decimal("5.16"),
        matched_documents=len(broker_600917),
        filled_quantity=(
            _integer_value(order_600917.get("filled_quantity"))
            if order_600917
            else None
        ),
        fill_count=(
            _integer_value(order_600917.get("fill_count")) if order_600917 else None
        ),
        avg_filled_price=(
            _decimal_text(order_600917.get("avg_filled_price"))
            if order_600917
            else None
        ),
    )

    fills_600917 = _fixed_order_scope_documents(
        databases,
        collection="om_execution_fills",
        symbol="600917",
        trading_days=(20260528,),
    )
    facts_600917 = _fixed_order_scope_documents(
        databases,
        collection="om_trade_facts",
        symbol="600917",
        trading_days=(20260528,),
    )
    fill_ids_600917 = _nonempty_text_values(fills_600917, "execution_identity")
    fact_ids_600917 = _nonempty_text_values(facts_600917, "execution_identity")
    fill_quantities_600917 = [
        _integer_value(item.get("quantity")) for item in fills_600917
    ]
    fact_quantities_600917 = [
        _integer_value(item.get("quantity")) for item in facts_600917
    ]
    _add_verification_check(
        checks,
        "executions_600917",
        len(fills_600917) == 15
        and len(facts_600917) == 15
        and len(fill_ids_600917) == 15
        and len(set(fill_ids_600917)) == 15
        and len(fact_ids_600917) == 15
        and len(set(fact_ids_600917)) == 15
        and set(fill_ids_600917) == set(fact_ids_600917)
        and all(item is not None for item in fill_quantities_600917)
        and all(item is not None for item in fact_quantities_600917)
        and sum(item for item in fill_quantities_600917 if item is not None) == 38_700
        and sum(item for item in fact_quantities_600917 if item is not None) == 38_700
        and all(
            _decimal_value(item.get("price")) == Decimal("5.16")
            for item in [*fills_600917, *facts_600917]
        ),
        fill_count=len(fills_600917),
        fact_count=len(facts_600917),
        filled_quantity=sum(
            item for item in fill_quantities_600917 if item is not None
        ),
    )

    broker_orders_688772 = _fixed_order_scope_documents(
        databases,
        collection="om_broker_orders",
        symbol="688772",
        trading_days=(20260804, 20260805),
    )
    buy_orders_688772 = [
        item for item in broker_orders_688772 if _document_side(item) == "buy"
    ]
    sell_orders_688772 = [
        item for item in broker_orders_688772 if _document_side(item) == "sell"
    ]
    buy_order = buy_orders_688772[0] if len(buy_orders_688772) == 1 else None
    _add_verification_check(
        checks,
        "broker_order_688772_buy",
        buy_order is not None
        and len(broker_orders_688772)
        == len(buy_orders_688772) + len(sell_orders_688772)
        and buy_order.get("internal_order_id") == _FIX_504_688772_BUY_OWNER
        and buy_order.get("broker_order_key") == _FIX_504_688772_BUY_KEY
        and buy_order.get("request_id") is None
        and buy_order.get("broker_correlation_token") is None
        and _integer_value(buy_order.get("filled_quantity")) == 10_000
        and _integer_value(buy_order.get("fill_count")) == 1
        and _decimal_value(buy_order.get("avg_filled_price")) == Decimal("14.70"),
        matched_documents=len(buy_orders_688772),
        internal_order_id=(buy_order.get("internal_order_id") if buy_order else None),
        broker_order_key=(buy_order.get("broker_order_key") if buy_order else None),
        filled_quantity=(
            _integer_value(buy_order.get("filled_quantity")) if buy_order else None
        ),
        avg_filled_price=(
            _decimal_text(buy_order.get("avg_filled_price")) if buy_order else None
        ),
    )

    sell_order = sell_orders_688772[0] if len(sell_orders_688772) == 1 else None
    _add_verification_check(
        checks,
        "broker_order_688772_sell",
        sell_order is not None
        and sell_order.get("internal_order_id") == _FIX_504_688772_SELL_OWNER
        and str(sell_order.get("broker_order_id") or "").strip()
        == _FIX_504_688772_SELL_BROKER_ORDER_ID
        and str(sell_order.get("order_sysid") or "").strip()
        == _FIX_504_688772_SELL_SYSID
        and sell_order.get("broker_order_key") == _FIX_504_688772_SELL_KEY
        and _integer_value(sell_order.get("filled_quantity")) == 10_000
        and _integer_value(sell_order.get("fill_count")) == 9
        and _decimal_value(sell_order.get("avg_filled_price")) == Decimal("14.80"),
        matched_documents=len(sell_orders_688772),
        internal_order_id=(sell_order.get("internal_order_id") if sell_order else None),
        broker_order_id=(sell_order.get("broker_order_id") if sell_order else None),
        order_sysid=(sell_order.get("order_sysid") if sell_order else None),
        broker_order_key=(sell_order.get("broker_order_key") if sell_order else None),
        filled_quantity=(
            _integer_value(sell_order.get("filled_quantity")) if sell_order else None
        ),
        fill_count=(
            _integer_value(sell_order.get("fill_count")) if sell_order else None
        ),
        avg_filled_price=(
            _decimal_text(sell_order.get("avg_filled_price")) if sell_order else None
        ),
    )

    fills_688772 = _fixed_order_scope_documents(
        databases,
        collection="om_execution_fills",
        symbol="688772",
        trading_days=(20260804, 20260805),
    )
    facts_688772 = _fixed_order_scope_documents(
        databases,
        collection="om_trade_facts",
        symbol="688772",
        trading_days=(20260804, 20260805),
    )
    fill_execution_ids = _nonempty_text_values(fills_688772, "execution_identity")
    fact_execution_ids = _nonempty_text_values(facts_688772, "execution_identity")
    buy_fills = [item for item in fills_688772 if _document_side(item) == "buy"]
    buy_facts = [item for item in facts_688772 if _document_side(item) == "buy"]
    sell_fills = [item for item in fills_688772 if _document_side(item) == "sell"]
    sell_facts = [item for item in facts_688772 if _document_side(item) == "sell"]
    sell_fact_ids = set(_nonempty_text_values(sell_facts, "trade_fact_id"))
    sell_fill_quantities = [_integer_value(item.get("quantity")) for item in sell_fills]
    sell_quantities = [_integer_value(item.get("quantity")) for item in sell_facts]
    buy_fill = buy_fills[0] if len(buy_fills) == 1 else None
    buy_fact = buy_facts[0] if len(buy_facts) == 1 else None
    _add_verification_check(
        checks,
        "executions_688772",
        len(fills_688772) == 10
        and len(facts_688772) == 10
        and len(fill_execution_ids) == 10
        and len(set(fill_execution_ids)) == 10
        and len(fact_execution_ids) == 10
        and len(set(fact_execution_ids)) == 10
        and set(fill_execution_ids) == set(fact_execution_ids)
        and buy_fill is not None
        and buy_fact is not None
        and _integer_value(buy_fill.get("quantity")) == 10_000
        and _integer_value(buy_fact.get("quantity")) == 10_000
        and _decimal_value(buy_fill.get("price")) == Decimal("14.70")
        and _decimal_value(buy_fact.get("price")) == Decimal("14.70")
        and len(sell_fills) == 9
        and len(sell_facts) == 9
        and len(sell_fact_ids) == 9
        and all(item is not None for item in sell_fill_quantities)
        and all(item is not None for item in sell_quantities)
        and sum(item for item in sell_fill_quantities if item is not None) == 10_000
        and sum(item for item in sell_quantities if item is not None) == 10_000,
        fill_count=len(fills_688772),
        fact_count=len(facts_688772),
        unique_fill_execution_identities=len(set(fill_execution_ids)),
        unique_fact_execution_identities=len(set(fact_execution_ids)),
        buy_fill_count=len(buy_fills),
        buy_fact_count=len(buy_facts),
        sell_fill_count=len(sell_fills),
        sell_fact_count=len(sell_facts),
    )

    entries_688772 = list(
        databases["order"]["om_position_entries"].find({"symbol": "688772"})
    )
    entry = entries_688772[0] if len(entries_688772) == 1 else None
    _add_verification_check(
        checks,
        "position_entry_688772",
        entry is not None
        and _integer_value(entry.get("original_quantity")) == 10_000
        and _decimal_value(entry.get("entry_price")) == Decimal("14.70")
        and _integer_value(entry.get("remaining_quantity")) == 0,
        matched_documents=len(entries_688772),
        original_quantity=(
            _integer_value(entry.get("original_quantity")) if entry else None
        ),
        entry_price=(_decimal_text(entry.get("entry_price")) if entry else None),
        remaining_quantity=(
            _integer_value(entry.get("remaining_quantity")) if entry else None
        ),
    )

    slices_688772 = list(
        databases["order"]["om_entry_slices"].find({"symbol": "688772"})
    )
    actual_slices = Counter(
        (
            _integer_value(item.get("original_quantity")),
            _decimal_value(item.get("guardian_price")),
        )
        for item in slices_688772
    )
    expected_slices = Counter(
        {
            (3_400, Decimal("14.70")): 1,
            (3_300, Decimal("15.14")): 1,
            (3_200, Decimal("15.59")): 1,
            (100, Decimal("16.06")): 1,
        }
    )
    _add_verification_check(
        checks,
        "entry_slices_688772",
        len(slices_688772) == 4
        and actual_slices == expected_slices
        and all(
            _integer_value(item.get("remaining_quantity")) == 0
            for item in slices_688772
        ),
        matched_documents=len(slices_688772),
        slices=sorted(
            f"{quantity}@{price}" for quantity, price in actual_slices.elements()
        ),
    )

    entry_id = str(entry.get("entry_id") or "").strip() if entry else ""
    v2_allocations = (
        list(databases["order"]["om_exit_allocations"].find({"entry_id": entry_id}))
        if entry_id
        else []
    )
    v2_passed, v2_details = _allocation_verification(
        v2_allocations,
        trade_fact_field="exit_trade_fact_id",
        sell_trade_fact_ids=sell_fact_ids,
    )
    _add_verification_check(
        checks,
        "v2_allocations_688772",
        v2_passed,
        **v2_details,
    )
    live_gaps = list(
        databases["order"]["om_reconciliation_gaps"].find({"symbol": "688772"})
    )
    gap_passed, gap_details = _deleted_collection_verification(
        rows,
        collection="om_reconciliation_gaps",
        expected_count=3,
        live_documents=live_gaps,
    )
    _add_verification_check(
        checks,
        "reconciliation_gaps_removed",
        gap_passed,
        **gap_details,
    )
    planned_gap_ids = sorted(
        {
            str(row["change"]["before_document"].get("gap_id") or "").strip()
            for row in rows
            if row["change"]["collection"] == "om_reconciliation_gaps"
            and row["change"]["before_document"] is not None
            and str(row["change"]["before_document"].get("gap_id") or "").strip()
        }
    )
    live_resolutions = (
        list(
            databases["order"]["om_reconciliation_resolutions"].find(
                {"gap_id": {"$in": planned_gap_ids}}
            )
        )
        if planned_gap_ids
        else []
    )
    resolution_passed, resolution_details = _deleted_collection_verification(
        rows,
        collection="om_reconciliation_resolutions",
        expected_count=3,
        live_documents=live_resolutions,
    )
    _add_verification_check(
        checks,
        "reconciliation_resolutions_removed",
        resolution_passed,
        **resolution_details,
    )
    live_rejections = list(
        databases["order"]["om_ingest_rejections"].find(
            {
                "symbol": "688772",
                "reason_code": "non_board_lot_quantity",
            }
        )
    )
    rejection_passed, rejection_details = _deleted_collection_verification(
        rows,
        collection="om_ingest_rejections",
        expected_count=6,
        live_documents=live_rejections,
        before_predicate=lambda document: (
            document.get("reason_code") == "non_board_lot_quantity"
        ),
    )
    _add_verification_check(
        checks,
        "odd_lot_rejections_removed",
        rejection_passed,
        **rejection_details,
    )

    immutable_rows = [
        row
        for row in rows
        if row["change"]["store"] == "business"
        or row["change"]["collection"] in _READ_ONLY_ORDER_COLLECTIONS
    ]
    immutable_mismatches = [
        row["change"]["change_id"]
        for row in immutable_rows
        if not _values_equal(
            row["change"]["before_document"],
            row["change"]["after_document"],
        )
        or not _values_equal(row["document"], row["change"]["before_document"])
    ]
    _add_verification_check(
        checks,
        "immutable_evidence_unchanged",
        not immutable_mismatches,
        checked_documents=len(immutable_rows),
        checked_collections=sorted(
            {
                f"{row['change']['store']}.{row['change']['collection']}"
                for row in immutable_rows
            }
        ),
        mismatched_change_ids=immutable_mismatches,
    )

    result = {
        "repair_id": normalized_manifest["repair_id"],
        "status": "verified",
        "pass": all(item["pass"] for item in checks),
        "manifest_hash": normalized_manifest["manifest_hash"],
        "checked_document_count": len(rows),
        "checks": checks,
    }
    if not result["pass"]:
        failed = [item["name"] for item in checks if not item["pass"]]
        raise TargetedRepairError(
            "targeted repair verification failed: " + ", ".join(failed)
        )
    return result


def build_repair_plan_hash(plan: Mapping[str, Any]) -> str:
    return _hash_value(_normalize_plan(plan))


def load_repair_document(path: str | Path) -> dict[str, Any]:
    return json_util.loads(Path(path).read_text(encoding="utf-8"))


def persist_repair_document(document: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _pretty_extended_json(document)
    _write_fsync(target, payload)
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise InvalidRepairPlan("repair plan must be an object")
    if int(plan.get("schema_version") or 0) != TARGETED_REPAIR_PLAN_SCHEMA_VERSION:
        raise InvalidRepairPlan("unsupported repair plan schema_version")
    repair_id = str(plan.get("repair_id") or "").strip()
    if not repair_id:
        raise InvalidRepairPlan("repair_id must not be empty")
    target_main_sha = _normalize_git_sha(
        plan.get("target_main_sha"),
        label="target_main_sha",
    )
    reason = str(plan.get("reason") or "").strip()
    if not reason:
        raise InvalidRepairPlan("repair reason must not be empty")
    raw_changes = list(plan.get("changes") or [])
    if not raw_changes:
        raise InvalidRepairPlan("repair plan must contain at least one change")
    changes = [_normalize_change(item) for item in raw_changes]
    change_ids = [item["change_id"] for item in changes]
    if len(change_ids) != len(set(change_ids)):
        raise InvalidRepairPlan("change_id values must be unique")
    identities = [
        _hash_value(
            {
                "store": item["store"],
                "collection": item["collection"],
                "document_id": item["document_id"],
            }
        )
        for item in changes
    ]
    if len(identities) != len(set(identities)):
        raise InvalidRepairPlan("each store/collection/document_id may appear once")
    scope = _normalize_fix_504_scope(plan.get("scope"), changes)
    return {
        "schema_version": TARGETED_REPAIR_PLAN_SCHEMA_VERSION,
        "repair_id": repair_id,
        "target_main_sha": target_main_sha,
        "reason": reason,
        "scope": scope,
        "changes": changes,
    }


def _normalize_change(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan("each repair change must be an object")
    change_id = str(value.get("change_id") or "").strip()
    store = str(value.get("store") or "").strip()
    collection = str(value.get("collection") or "").strip()
    if not change_id:
        raise InvalidRepairPlan("change_id must not be empty")
    if store not in {"order", "business"}:
        raise InvalidRepairPlan("change store must be order or business")
    if "document_id" not in value:
        raise InvalidRepairPlan("every change requires document_id")
    document_id = deepcopy(value.get("document_id"))
    if document_id in (None, ""):
        raise InvalidRepairPlan("document_id must not be empty")
    before_document = _normalize_optional_document(
        value.get("before_document"),
        document_id=document_id,
        label="before_document",
    )
    after_document = _normalize_optional_document(
        value.get("after_document"),
        document_id=document_id,
        label="after_document",
    )
    _assert_collection_policy(
        store=store,
        collection=collection,
        before_document=before_document,
        after_document=after_document,
    )
    return {
        "change_id": change_id,
        "store": store,
        "collection": collection,
        "document_id": document_id,
        "before_document": before_document,
        "after_document": after_document,
    }


def _normalize_fix_504_scope(value: Any, changes) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan("scope must be an object")
    account_id = str(value.get("account_id") or "").strip()
    symbols = tuple(sorted(str(item).strip() for item in value.get("symbols") or []))
    try:
        trading_days = tuple(
            sorted(int(item) for item in value.get("trading_days") or [])
        )
    except (TypeError, ValueError) as exc:
        raise InvalidRepairPlan(
            "scope.trading_days must contain integer dates"
        ) from exc
    if account_id != _FIX_504_ACCOUNT_ID:
        raise InvalidRepairPlan("scope.account_id is outside FIX-504")
    if symbols != _FIX_504_SYMBOLS:
        raise InvalidRepairPlan("scope.symbols must be exactly 600917 and 688772")
    if trading_days != _FIX_504_TRADING_DAYS:
        raise InvalidRepairPlan(
            "scope.trading_days must be exactly 20260528, 20260804 and 20260805"
        )

    raw_document_ids = value.get("document_ids")
    raw_approved_ids = value.get("approved_ids")
    if raw_document_ids is None and isinstance(raw_approved_ids, Mapping):
        # Unit/scratch plans may use the compact approved_ids form. Expand it
        # deterministically to the production manifest shape; the approved
        # document identity list is still checked exactly below.
        raw_document_ids = {}
        for change in changes:
            raw_document_ids.setdefault(change["store"], {}).setdefault(
                change["collection"], []
            ).append(deepcopy(change["document_id"]))
    if not isinstance(raw_document_ids, Mapping):
        raise InvalidRepairPlan("scope.document_ids must be an object")
    normalized_document_ids = {}
    approved_identity_hashes: set[str] = set()
    for store, raw_collections in raw_document_ids.items():
        store_name = str(store).strip()
        if store_name not in {"order", "business"} or not isinstance(
            raw_collections, Mapping
        ):
            raise InvalidRepairPlan("scope.document_ids has an invalid store")
        normalized_collections = {}
        for collection, raw_ids in raw_collections.items():
            collection_name = str(collection).strip()
            ids = [deepcopy(item) for item in list(raw_ids or [])]
            if not collection_name or not ids:
                raise InvalidRepairPlan(
                    "scope.document_ids collections must contain at least one _id"
                )
            identity_hashes = [_hash_value(item) for item in ids]
            if len(identity_hashes) != len(set(identity_hashes)):
                raise InvalidRepairPlan(
                    "scope.document_ids contains duplicate _id values"
                )
            ids = [
                item
                for _, item in sorted(
                    zip(identity_hashes, ids, strict=True), key=lambda pair: pair[0]
                )
            ]
            normalized_collections[collection_name] = ids
            approved_identity_hashes.update(
                _hash_value(
                    {
                        "store": store_name,
                        "collection": collection_name,
                        "document_id": item,
                    }
                )
                for item in ids
            )
        normalized_document_ids[store_name] = normalized_collections

    change_identity_hashes = {
        _hash_value(
            {
                "store": change["store"],
                "collection": change["collection"],
                "document_id": change["document_id"],
            }
        )
        for change in changes
    }
    if approved_identity_hashes != change_identity_hashes:
        raise InvalidRepairPlan(
            "scope.document_ids must exactly match every planned document"
        )

    approved_ids = {
        "order_sysids": _normalize_approved_scalar_list(
            (raw_approved_ids or {}).get("order_sysids")
            if isinstance(raw_approved_ids, Mapping)
            else value.get("order_sysids")
        ),
        "broker_order_ids": _normalize_approved_scalar_list(
            (raw_approved_ids or {}).get("broker_order_ids")
            if isinstance(raw_approved_ids, Mapping)
            else value.get("broker_order_ids")
        ),
        "broker_trade_ids": _normalize_approved_scalar_list(
            (raw_approved_ids or {}).get("broker_trade_ids")
            if isinstance(raw_approved_ids, Mapping)
            else value.get("broker_trade_ids")
        ),
        "internal_order_ids": _normalize_approved_scalar_list(
            (raw_approved_ids or {}).get("internal_order_ids")
            if isinstance(raw_approved_ids, Mapping)
            else value.get("internal_order_ids")
        ),
    }
    if isinstance(raw_approved_ids, Mapping) and "document_ids" in raw_approved_ids:
        approved_document_hashes = {
            _hash_value(item)
            for item in list(raw_approved_ids.get("document_ids") or [])
        }
        if approved_document_hashes != {
            _hash_value(item)
            for collections in normalized_document_ids.values()
            for ids in collections.values()
            for item in ids
        }:
            raise InvalidRepairPlan("scope.approved_ids.document_ids is not exact")

    for change in changes:
        _assert_document_within_fix_504_scope(change, approved_ids=approved_ids)

    return {
        "account_id": account_id,
        "symbols": list(symbols),
        "trading_days": list(trading_days),
        "document_ids": normalized_document_ids,
        "approved_ids": {
            "document_ids": [deepcopy(change["document_id"]) for change in changes],
            **approved_ids,
        },
    }


def _normalize_approved_scalar_list(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple, set)):
        raise InvalidRepairPlan("scope approved id lists must be arrays")
    normalized = [str(item).strip() for item in value if str(item).strip()]
    if len(normalized) != len(set(normalized)):
        raise InvalidRepairPlan("scope approved id lists must be unique")
    return sorted(normalized)


def _assert_document_within_fix_504_scope(change, *, approved_ids):
    for document in (change["before_document"], change["after_document"]):
        if document is None:
            continue
        account_id = document.get("account_id")
        if account_id not in (None, "", _FIX_504_ACCOUNT_ID):
            raise InvalidRepairPlan(
                f"change {change['change_id']} contains an out-of-scope account_id"
            )
        symbol = document.get("symbol")
        if symbol in (None, ""):
            symbol = document.get("stock_code")
        if symbol not in (None, ""):
            normalized_symbol = str(symbol).strip().split(".", 1)[0]
            if normalized_symbol not in _FIX_504_SYMBOLS:
                raise InvalidRepairPlan(
                    f"change {change['change_id']} contains an out-of-scope symbol"
                )
        trading_day = document.get("trading_day")
        if trading_day not in (None, ""):
            try:
                normalized_day = int(str(trading_day).replace("-", ""))
            except ValueError as exc:
                raise InvalidRepairPlan(
                    f"change {change['change_id']} has an invalid trading_day"
                ) from exc
            if normalized_day not in _FIX_504_TRADING_DAYS:
                raise InvalidRepairPlan(
                    f"change {change['change_id']} contains an out-of-scope trading_day"
                )
        for field, approved_key in (
            ("order_sysid", "order_sysids"),
            ("broker_order_id", "broker_order_ids"),
            ("broker_trade_id", "broker_trade_ids"),
            ("internal_order_id", "internal_order_ids"),
        ):
            field_value = document.get(field)
            if field_value in (None, ""):
                continue
            if not approved_ids[approved_key]:
                raise InvalidRepairPlan(
                    f"change {change['change_id']} requires a non-empty approved "
                    f"{field} list"
                )
            if str(field_value).strip() not in set(approved_ids[approved_key]):
                raise InvalidRepairPlan(
                    f"change {change['change_id']} contains an unapproved {field}"
                )


def _normalize_optional_document(value, *, document_id, label):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan(f"{label} must be an object or null")
    document = deepcopy(dict(value))
    if "_id" not in document or not _values_equal(document["_id"], document_id):
        raise InvalidRepairPlan(f"{label}._id must equal document_id")
    return document


def _assert_collection_policy(*, store, collection, before_document, after_document):
    if store == "business":
        if collection not in _READ_ONLY_BUSINESS_COLLECTIONS:
            raise InvalidRepairPlan(
                f"business collection {collection!r} is outside repair evidence scope"
            )
        if not _values_equal(before_document, after_document):
            raise TargetedRepairError(
                f"business collection {collection!r} is read-only evidence"
            )
        return
    if collection in _READ_ONLY_ORDER_COLLECTIONS:
        if not _values_equal(before_document, after_document):
            raise TargetedRepairError(
                f"order collection {collection!r} is read-only evidence"
            )
        return
    if collection not in _MUTABLE_ORDER_COLLECTIONS:
        raise InvalidRepairPlan(
            f"order collection {collection!r} is outside targeted repair scope"
        )


def _validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise InvalidRepairPlan("repair manifest must be an object")
    if (
        int(manifest.get("schema_version") or 0)
        != TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION
    ):
        raise InvalidRepairPlan("unsupported repair manifest schema_version")
    normalized_plan = _normalize_plan(
        {
            "schema_version": TARGETED_REPAIR_PLAN_SCHEMA_VERSION,
            "repair_id": manifest.get("repair_id"),
            "target_main_sha": manifest.get("target_main_sha"),
            "reason": manifest.get("reason"),
            "scope": manifest.get("scope"),
            "changes": manifest.get("changes"),
        }
    )
    normalized = {
        "schema_version": TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION,
        "repair_id": normalized_plan["repair_id"],
        "target_main_sha": normalized_plan["target_main_sha"],
        "reason": normalized_plan["reason"],
        "scope": normalized_plan["scope"],
        "plan_file_sha256": _normalize_sha256(
            manifest.get("plan_file_sha256"),
            label="plan file sha256",
        ),
        "plan_hash": _normalize_sha256(manifest.get("plan_hash"), label="plan hash"),
        "preimage_hash": _normalize_sha256(
            manifest.get("preimage_hash"), label="preimage hash"
        ),
        "postimage_hash": _normalize_sha256(
            manifest.get("postimage_hash"), label="postimage hash"
        ),
        "changes": normalized_plan["changes"],
        "generated_at": manifest.get("generated_at"),
        "manifest_hash": _normalize_sha256(
            manifest.get("manifest_hash"), label="manifest hash"
        ),
    }
    if normalized["plan_hash"] != build_repair_plan_hash(normalized_plan):
        raise ManifestHashMismatch("manifest plan_hash is invalid")
    if normalized["preimage_hash"] != _snapshot_hash(
        normalized["changes"], "before_document"
    ):
        raise ManifestHashMismatch("manifest preimage_hash is invalid")
    if normalized["postimage_hash"] != _snapshot_hash(
        normalized["changes"], "after_document"
    ):
        raise ManifestHashMismatch("manifest postimage_hash is invalid")
    if normalized["manifest_hash"] != _manifest_hash(normalized):
        raise ManifestHashMismatch("manifest_hash is invalid")
    return normalized


def _assert_manifest_matches_plan(manifest, plan):
    if manifest["repair_id"] != plan["repair_id"]:
        raise ManifestHashMismatch("manifest repair_id does not match plan")
    if manifest["target_main_sha"] != plan["target_main_sha"]:
        raise ManifestHashMismatch("manifest target_main_sha does not match plan")
    if manifest["plan_hash"] != build_repair_plan_hash(plan):
        raise ManifestHashMismatch("manifest plan_hash does not match plan")


def _validate_databases(databases):
    if not isinstance(databases, Mapping) or not {"order", "business"}.issubset(
        databases
    ):
        raise TargetedRepairError("databases must provide order and business stores")


def _fixed_order_scope_documents(
    databases,
    *,
    collection,
    symbol,
    trading_days,
):
    documents = []
    for trading_day in trading_days:
        documents.extend(
            databases["order"][collection].find(
                {
                    "account_id": _FIX_504_ACCOUNT_ID,
                    "symbol": symbol,
                    "trading_day": trading_day,
                }
            )
        )
    return list(documents)


def _document_symbol(document):
    value = document.get("symbol")
    if value in (None, ""):
        value = document.get("stock_code")
    return str(value or "").strip().split(".", 1)[0]


def _document_side(document):
    return str(document.get("side") or "").strip().lower()


def _nonempty_text_values(documents, field):
    return [
        str(document.get(field) or "").strip()
        for document in documents
        if str(document.get(field) or "").strip()
    ]


def _decimal_value(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        converter = getattr(value, "to_decimal", None)
        normalized = converter() if callable(converter) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return normalized if normalized.is_finite() else None


def _decimal_text(value):
    normalized = _decimal_value(value)
    return format(normalized, "f") if normalized is not None else None


def _integer_value(value):
    normalized = _decimal_value(value)
    if normalized is None or normalized != normalized.to_integral_value():
        return None
    return int(normalized)


def _add_verification_check(checks, name, passed, **details):
    checks.append(
        {
            "name": name,
            "pass": bool(passed),
            "details": details,
        }
    )


def _allocation_verification(
    documents,
    *,
    trade_fact_field,
    sell_trade_fact_ids,
):
    quantities = [_integer_value(item.get("allocated_quantity")) for item in documents]
    references = [str(item.get(trade_fact_field) or "").strip() for item in documents]
    total = sum(item for item in quantities if item is not None)
    passed = (
        len(documents) == 12
        and all(item is not None for item in quantities)
        and total == 10_000
        and len(references) == 12
        and all(item and item in sell_trade_fact_ids for item in references)
    )
    return passed, {
        "allocation_count": len(documents),
        "allocated_quantity": total,
        "referenced_sell_trade_fact_count": len(set(references)),
    }


def _deleted_collection_verification(
    rows,
    *,
    collection,
    expected_count,
    live_documents,
    before_predicate=None,
):
    scoped = [
        row
        for row in rows
        if row["change"]["store"] == "order"
        and row["change"]["collection"] == collection
    ]
    predicate = before_predicate or (lambda _document: True)
    passed = (
        len(scoped) == expected_count
        and len(live_documents) == 0
        and all(row["document"] is None for row in scoped)
        and all(row["change"]["after_document"] is None for row in scoped)
        and all(row["change"]["before_document"] is not None for row in scoped)
        and all(predicate(row["change"]["before_document"]) for row in scoped)
    )
    return passed, {
        "planned_deletions": len(scoped),
        "remaining_documents": len(live_documents),
    }


def _is_mutation(change: Mapping[str, Any]) -> bool:
    return not _values_equal(change["before_document"], change["after_document"])


def _mutation_state_rows(manifest, states):
    mutation_ids = {
        change["change_id"] for change in manifest["changes"] if _is_mutation(change)
    }
    return [item for item in states if item["change_id"] in mutation_ids]


def _rollback_applied_changes(applied_changes, *, databases):
    failures = []
    for change in reversed(list(applied_changes)):
        try:
            _write_change(
                change,
                databases=databases,
                expected_field="after_document",
                target_field="before_document",
            )
        except Exception:
            failures.append(change["change_id"])
    return failures


def _load_current_document(change, databases):
    return databases[change["store"]][change["collection"]].find_one(
        {"_id": deepcopy(change["document_id"])}
    )


def _write_change(change, *, databases, expected_field, target_field):
    collection = databases[change["store"]][change["collection"]]
    expected = deepcopy(change[expected_field])
    target = deepcopy(change[target_field])
    current = collection.find_one({"_id": deepcopy(change["document_id"])})
    if not _values_equal(current, expected):
        raise TargetedRepairError(
            "repair compare-and-swap failed because current document changed for "
            f"{change['store']}.{change['collection']} "
            f"change_id={change['change_id']}"
        )
    if _values_equal(expected, target):
        return
    if expected is None:
        try:
            collection.insert_one(target)
        except DuplicateKeyError as exc:
            raise TargetedRepairError(
                "repair compare-and-swap insert failed because document_id exists for "
                f"change_id={change['change_id']}"
            ) from exc
        return
    exact_selector = {
        "$and": [
            {"_id": deepcopy(change["document_id"])},
            {"$expr": {"$eq": ["$$ROOT", {"$literal": deepcopy(expected)}]}},
        ]
    }
    if target is None:
        result = collection.delete_one(exact_selector)
        if int(getattr(result, "deleted_count", 0) or 0) != 1:
            raise TargetedRepairError(
                "repair compare-and-swap delete failed for "
                f"change_id={change['change_id']}"
            )
        return
    result = collection.replace_one(exact_selector, target, upsert=False)
    if int(getattr(result, "matched_count", 0) or 0) != 1:
        raise TargetedRepairError(
            "repair compare-and-swap replace failed for "
            f"change_id={change['change_id']}"
        )


def _require_known_change_states(manifest, databases):
    states = _change_states(manifest, databases)
    unknown = [item["change_id"] for item in states if item["state"] == "unknown"]
    if unknown:
        raise TargetedRepairError(
            "repair is blocked because documents match neither preimage nor postimage: "
            + ", ".join(unknown)
        )
    return states


def _change_states(manifest, databases):
    return [
        {"change_id": change["change_id"], "state": _change_state(change, databases)}
        for change in manifest["changes"]
    ]


def _change_state(change, databases):
    current = _load_current_document(change, databases)
    if _values_equal(current, change["before_document"]):
        return "preimage"
    if _values_equal(current, change["after_document"]):
        return "postimage"
    return "unknown"


def _snapshot_hash(changes: Sequence[Mapping[str, Any]], document_field: str) -> str:
    return _hash_value(
        [
            {
                "change_id": change["change_id"],
                "store": change["store"],
                "collection": change["collection"],
                "document_id": change["document_id"],
                "document": change[document_field],
            }
            for change in changes
        ]
    )


def _current_snapshot_hash(manifest, databases):
    return _hash_value(
        [
            {
                "change_id": change["change_id"],
                "store": change["store"],
                "collection": change["collection"],
                "document_id": change["document_id"],
                "document": _load_current_document(change, databases),
            }
            for change in manifest["changes"]
        ]
    )


def _manifest_hash(manifest):
    payload = {
        key: deepcopy(value)
        for key, value in dict(manifest).items()
        if key not in {"manifest_hash", "generated_at"}
    }
    return _hash_value(payload)


def _persist_backup_bundle(manifest, backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "manifest.json": manifest,
        "preimage.json": {
            "repair_id": manifest["repair_id"],
            "preimage_hash": manifest["preimage_hash"],
            "documents": [
                {
                    "change_id": change["change_id"],
                    "store": change["store"],
                    "collection": change["collection"],
                    "document_id": change["document_id"],
                    "document": change["before_document"],
                }
                for change in manifest["changes"]
            ],
        },
        "postimage.json": {
            "repair_id": manifest["repair_id"],
            "postimage_hash": manifest["postimage_hash"],
            "documents": [
                {
                    "change_id": change["change_id"],
                    "store": change["store"],
                    "collection": change["collection"],
                    "document_id": change["document_id"],
                    "document": change["after_document"],
                }
                for change in manifest["changes"]
            ],
        },
    }
    for filename, document in files.items():
        _persist_identical_or_new(document, backup_dir / filename)
    receipt = {
        "repair_id": manifest["repair_id"],
        "plan_file_sha256": manifest["plan_file_sha256"],
        "plan_hash": manifest["plan_hash"],
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "files": {filename: sha256_file(backup_dir / filename) for filename in files},
    }
    _persist_identical_or_new(receipt, backup_dir / "backup-receipt.json")
    loaded_receipt = load_repair_document(backup_dir / "backup-receipt.json")
    if not _values_equal(loaded_receipt, receipt):
        raise TargetedRepairError("backup receipt read-back verification failed")
    for filename, expected_hash in receipt["files"].items():
        if sha256_file(backup_dir / filename) != expected_hash:
            raise TargetedRepairError(
                f"backup file hash verification failed: {filename}"
            )


def _validate_backup_bundle(manifest, backup_dir: Path):
    required = {
        "manifest.json",
        "preimage.json",
        "postimage.json",
        "backup-receipt.json",
    }
    if not backup_dir.is_dir() or not required.issubset(
        {item.name for item in backup_dir.iterdir()}
    ):
        raise TargetedRepairError(
            f"verified backup bundle is missing under {backup_dir}"
        )

    receipt = load_repair_document(backup_dir / "backup-receipt.json")
    expected_files = {
        filename: sha256_file(backup_dir / filename)
        for filename in required - {"backup-receipt.json"}
    }
    expected_receipt = {
        "repair_id": manifest["repair_id"],
        "plan_file_sha256": manifest["plan_file_sha256"],
        "plan_hash": manifest["plan_hash"],
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "files": expected_files,
    }
    if not _values_equal(receipt, expected_receipt):
        raise TargetedRepairError("backup receipt does not match the approved manifest")
    loaded_manifest = load_repair_document(backup_dir / "manifest.json")
    _validate_manifest(loaded_manifest)
    if loaded_manifest["manifest_hash"] != manifest["manifest_hash"]:
        raise TargetedRepairError(
            "backup manifest hash does not match the approved manifest"
        )
    loaded_preimage = load_repair_document(backup_dir / "preimage.json")
    loaded_postimage = load_repair_document(backup_dir / "postimage.json")
    if loaded_preimage.get("preimage_hash") != manifest["preimage_hash"]:
        raise TargetedRepairError(
            "backup preimage hash does not match the approved manifest"
        )
    if loaded_postimage.get("postimage_hash") != manifest["postimage_hash"]:
        raise TargetedRepairError(
            "backup postimage hash does not match the approved manifest"
        )
    if (
        _snapshot_hash(loaded_preimage.get("documents") or [], "document")
        != manifest["preimage_hash"]
    ):
        raise TargetedRepairError("backup preimage documents failed hash verification")
    if (
        _snapshot_hash(loaded_postimage.get("documents") or [], "document")
        != manifest["postimage_hash"]
    ):
        raise TargetedRepairError("backup postimage documents failed hash verification")
    return receipt


def _persist_identical_or_new(document, path: Path):
    payload = _pretty_extended_json(document)
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise TargetedRepairError(f"backup artifact already differs: {path}")
        return
    _write_fsync(path, payload, exclusive=True)


def _write_fsync(path: Path, payload: str, *, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RepairLockConflict(f"repair lock already exists: {path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _assert_expected_hash(expected, actual, error_type, label):
    normalized_expected = _normalize_sha256(expected, label=label)
    if normalized_expected != actual:
        raise error_type(f"{label} mismatch")


def _normalize_sha256(value, *, label):
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise InvalidRepairPlan(f"{label} must be a 64-character sha256")
    return normalized


def _normalize_git_sha(value, *, label):
    normalized = str(value or "").strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise InvalidRepairPlan(f"{label} must be a 40-character git sha")
    return normalized


def _summary(manifest, *, status):
    return {
        "repair_id": manifest["repair_id"],
        "status": status,
        "target_main_sha": manifest["target_main_sha"],
        "plan_file_sha256": manifest["plan_file_sha256"],
        "plan_hash": manifest["plan_hash"],
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "change_count": len(manifest["changes"]),
    }


def _values_equal(left, right):
    return _canonical_json(left) == _canonical_json(right)


def _hash_value(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value):
    return json_util.dumps(
        value,
        json_options=json_util.CANONICAL_JSON_OPTIONS,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _pretty_extended_json(value):
    return (
        json_util.dumps(
            value,
            json_options=json_util.CANONICAL_JSON_OPTIONS,
            ensure_ascii=False,
            indent=2,
            # Preserve BSON field order in complete preimages. Hashes are
            # canonicalized separately by _canonical_json; sorting here would
            # make a reloaded manifest unusable for an exact Mongo CAS.
            sort_keys=False,
        )
        + "\n"
    )


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DeploymentShaMismatch",
    "InvalidRepairPlan",
    "ManifestHashMismatch",
    "PlanFileHashMismatch",
    "PreimageHashMismatch",
    "RepairLockConflict",
    "RepairMixedState",
    "RepairRollbackIncomplete",
    "TargetedRepairError",
    "build_repair_plan_hash",
    "execute_targeted_repair",
    "load_repair_document",
    "persist_repair_document",
    "preview_targeted_restore",
    "restore_targeted_repair",
    "sha256_file",
    "stage_targeted_repair",
    "verify_targeted_repair",
]
