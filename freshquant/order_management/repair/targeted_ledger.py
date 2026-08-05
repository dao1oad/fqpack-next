# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, cast

from bson import json_util
from pymongo.errors import DuplicateKeyError

TARGETED_REPAIR_SCHEMA_VERSION = 1
TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION = 1
TARGETED_REPAIR_JOURNAL_COLLECTION = "om_targeted_repair_runs"

_SUPPORTED_STORES = {"business", "order"}
_PROTECTED_COLLECTIONS = {
    "om_execution_history_archive",
    "position_review_evidence_archive",
    TARGETED_REPAIR_JOURNAL_COLLECTION,
}
_SAFE_QUERY_OPERATORS = {"$and", "$or", "$eq", "$in"}
_REPAIR_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_REPAIR_ATTEMPT_LEASE_SECONDS = 300
_RESTORABLE_RECEIPT_STATUSES = {
    "applied",
    "restoring",
    "restore_failed",
    "restored",
}

_SCOPE_FIELDS: dict[str, tuple[str, ...]] = {
    "account_id": ("account_id",),
    "symbols": ("symbol", "stock_code"),
    "broker_order_ids": ("broker_order_id", "order_id"),
    "order_sysids": ("order_sysid", "order_sys_id"),
    "broker_trade_ids": ("broker_trade_id", "traded_id"),
    "trading_days": ("trading_day", "date"),
    "request_ids": ("request_id",),
    "internal_order_ids": ("internal_order_id",),
    "execution_fill_ids": ("execution_fill_id",),
    "trade_fact_ids": ("trade_fact_id", "exit_trade_fact_id"),
    "entry_ids": ("entry_id",),
    "entry_slice_ids": ("entry_slice_id",),
    "allocation_ids": ("allocation_id",),
    "gap_ids": ("gap_id",),
    "resolution_ids": ("resolution_id",),
    "rejection_ids": ("rejection_id",),
    "document_ids": ("_id",),
}


class TargetedRepairError(RuntimeError):
    pass


class InvalidRepairPlan(TargetedRepairError):
    pass


class AllowedDiffMismatch(TargetedRepairError):
    pass


class PreimageHashMismatch(TargetedRepairError):
    pass


class RepairIdConflict(TargetedRepairError):
    pass


class RestoreStateMismatch(TargetedRepairError):
    pass


def stage_targeted_repair(
    *,
    plan: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an immutable repair manifest without mutating any database."""

    normalized_plan = _normalize_plan(plan)
    _validate_databases(normalized_plan, databases)
    staged_changes: list[dict[str, Any]] = []

    for change in normalized_plan["changes"]:
        collection = databases[change["store"]][change["collection"]]
        preimage_documents = _sorted_documents(
            list(collection.find(deepcopy(change["selector"]))),
            identity_fields=change["identity_fields"],
        )
        _assert_documents_within_scope(
            preimage_documents,
            scope=normalized_plan["scope"],
            label=f"{change['store']}.{change['collection']} preimage",
        )
        postimage_documents = (
            deepcopy(preimage_documents)
            if change["mode"] == "snapshot"
            else _sorted_documents(
                change["desired_documents"],
                identity_fields=change["identity_fields"],
            )
        )
        _assert_documents_within_scope(
            postimage_documents,
            scope=normalized_plan["scope"],
            label=f"{change['store']}.{change['collection']} postimage",
        )
        if change["mode"] == "replace" and (
            len(preimage_documents) > 1 or len(postimage_documents) > 1
        ):
            raise InvalidRepairPlan(
                f"replace change for {change['store']}.{change['collection']} "
                "must target at most one preimage and one postimage document"
            )
        diff = _build_document_diff(
            preimage_documents,
            postimage_documents,
            identity_fields=change["identity_fields"],
        )
        _assert_allowed_diff(
            actual=diff,
            expected=change["allowed_diff"],
            identity_fields=change["identity_fields"],
            store=change["store"],
            collection=change["collection"],
        )
        if change["mode"] == "replace" and _diff_count(diff) > 1:
            raise InvalidRepairPlan(
                f"replace change for {change['store']}.{change['collection']} "
                "must express one atomic insert, update or delete; split identity moves"
            )
        staged_change = {
            "mode": change["mode"],
            "store": change["store"],
            "collection": change["collection"],
            "selector": deepcopy(change["selector"]),
            "identity_fields": list(change["identity_fields"]),
            "preimage_documents": preimage_documents,
            "postimage_documents": postimage_documents,
            "diff": diff,
        }
        _require_fixed_id_for_insert(staged_change)
        staged_changes.append(staged_change)

    _assert_staged_changes_do_not_overlap(staged_changes)
    if not any(_diff_count(item["diff"]) for item in staged_changes):
        raise InvalidRepairPlan("repair plan does not change any scoped document")

    plan_hash = build_repair_plan_hash(normalized_plan)
    preimage_hash = _snapshot_hash(staged_changes, "preimage_documents")
    postimage_hash = _snapshot_hash(staged_changes, "postimage_documents")
    manifest = {
        "schema_version": TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION,
        "repair_id": normalized_plan["repair_id"],
        "reason": normalized_plan["reason"],
        "scope": deepcopy(normalized_plan["scope"]),
        "plan_hash": plan_hash,
        "preimage_hash": preimage_hash,
        "postimage_hash": postimage_hash,
        "created_at": _utc_now(),
        "changes": staged_changes,
    }
    manifest["manifest_hash"] = _manifest_hash(manifest)
    return manifest


def execute_targeted_repair(
    *,
    plan: Mapping[str, Any],
    databases: Mapping[str, Any],
    expected_preimage_hash: str,
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Apply one explicitly scoped repair after all safety gates pass."""

    normalized_plan = _normalize_plan(plan)
    _validate_databases(normalized_plan, databases)
    repair_id = normalized_plan["repair_id"]
    plan_hash = build_repair_plan_hash(normalized_plan)
    journal = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION]
    _ensure_journal_index(journal)

    existing = journal.find_one({"repair_id": repair_id})
    if existing is not None:
        return _resume_or_report_existing_repair(
            existing=existing,
            plan_hash=plan_hash,
            expected_preimage_hash=expected_preimage_hash,
            databases=databases,
            journal=journal,
        )

    manifest = stage_targeted_repair(plan=normalized_plan, databases=databases)
    _assert_expected_hash(
        expected=expected_preimage_hash,
        actual=manifest["preimage_hash"],
        label="preimage",
    )
    persisted_manifest_path = _persist_manifest(manifest, manifest_path)
    apply_attempt_id = _new_attempt_id("apply", repair_id)
    apply_lease_expires_at = _new_attempt_lease_expiry()
    receipt = {
        "repair_id": repair_id,
        "schema_version": TARGETED_REPAIR_SCHEMA_VERSION,
        "receipt_version": 1,
        "status": "applying",
        "apply_attempt_id": apply_attempt_id,
        "apply_lease_expires_at": apply_lease_expires_at,
        "reason": normalized_plan["reason"],
        "scope": deepcopy(normalized_plan["scope"]),
        "plan_hash": manifest["plan_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "manifest_path": str(persisted_manifest_path),
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "started_at": _utc_now(),
    }
    try:
        journal.insert_one(deepcopy(receipt))
    except DuplicateKeyError:
        existing = journal.find_one({"repair_id": repair_id})
        if existing is None:
            raise
        return _resume_or_report_existing_repair(
            existing=existing,
            plan_hash=plan_hash,
            expected_preimage_hash=expected_preimage_hash,
            databases=databases,
            journal=journal,
        )

    return _apply_manifest(
        manifest=manifest,
        databases=databases,
        journal=journal,
        resumed=False,
        attempt_id=apply_attempt_id,
        receipt_version=1,
    )


def preview_targeted_restore(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_manifest = _validate_manifest(manifest)
    _validate_manifest_databases(normalized_manifest, databases)
    receipt = _require_restore_receipt(
        manifest=normalized_manifest,
        databases=databases,
    )
    current_hash = _current_snapshot_hash(normalized_manifest, databases)
    change_states = _manifest_change_states(normalized_manifest, databases)
    receipt_status = str(receipt.get("status") or "")
    return {
        "repair_id": normalized_manifest["repair_id"],
        "receipt_status": receipt_status,
        "execute": False,
        "current_hash": current_hash,
        "expected_postimage_hash": normalized_manifest["postimage_hash"],
        "target_preimage_hash": normalized_manifest["preimage_hash"],
        "restorable": _restore_state_is_executable(
            receipt_status=receipt_status,
            change_states=change_states,
        ),
        "change_states": change_states,
        "changes": [
            {
                "mode": item["mode"],
                "store": item["store"],
                "collection": item["collection"],
                "restore_document_count": len(item["preimage_documents"]),
                "remove_document_count": len(item["postimage_documents"]),
            }
            for item in normalized_manifest["changes"]
        ],
    }


def restore_targeted_repair(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
    expected_current_hash: str,
    restore_id: str | None = None,
) -> dict[str, Any]:
    """Restore an applied repair only while its exact postimage is current."""

    normalized_manifest = _validate_manifest(manifest)
    _validate_manifest_databases(normalized_manifest, databases)
    repair_id = normalized_manifest["repair_id"]
    normalized_restore_id = str(restore_id or f"restore:{repair_id}").strip()
    if not normalized_restore_id:
        raise InvalidRepairPlan("restore_id must not be empty")
    journal = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION]
    _ensure_journal_index(journal)
    receipt = _require_restore_receipt(
        manifest=normalized_manifest,
        databases=databases,
    )
    receipt_status = str(receipt.get("status") or "")
    prior_restore_id = str(receipt.get("restore_id") or "").strip()
    if receipt_status in {"restoring", "restore_failed", "restored"} and (
        prior_restore_id and prior_restore_id != normalized_restore_id
    ):
        raise RepairIdConflict(
            f"repair_id {repair_id!r} is already bound to restore_id "
            f"{prior_restore_id!r}"
        )

    current_hash = _current_snapshot_hash(normalized_manifest, databases)
    change_states = _manifest_change_states(normalized_manifest, databases)
    if receipt_status == "restored":
        if not _all_changes_at(change_states, "preimage"):
            raise RestoreStateMismatch(
                "restored receipt exists but current scoped state no longer matches preimage"
            )
        return _repair_summary(
            normalized_manifest,
            execute=True,
            status="already_restored",
            idempotent=True,
        )

    _assert_expected_hash(
        expected=expected_current_hash,
        actual=current_hash,
        label="restore current state",
    )
    if any(item["state"] == "diverged" for item in change_states):
        raise RestoreStateMismatch(
            "restore is blocked because one or more changes match neither preimage nor postimage"
        )
    if not _all_changes_at(change_states, "postimage") and receipt_status not in {
        "restoring",
        "restore_failed",
    }:
        raise RestoreStateMismatch(
            "partial restore state is resumable only from a restoring receipt"
        )

    attempt_id, receipt_version = _claim_attempt(
        journal,
        receipt=receipt,
        operation="restore",
        allowed_statuses={"applied", "restoring", "restore_failed"},
        restore_id=normalized_restore_id,
    )

    try:
        _renew_owned_attempt_lease(
            journal,
            repair_id=repair_id,
            operation="restore",
            attempt_id=attempt_id,
            receipt_version=receipt_version,
        )
        current_hash = _current_snapshot_hash(normalized_manifest, databases)
        _assert_expected_hash(
            expected=expected_current_hash,
            actual=current_hash,
            label="restore current state",
        )
        change_states = _manifest_change_states(normalized_manifest, databases)
        if any(item["state"] == "diverged" for item in change_states):
            raise RestoreStateMismatch(
                "restore is blocked because one or more changes match neither "
                "preimage nor postimage"
            )
        for index in range(len(normalized_manifest["changes"]) - 1, -1, -1):
            if change_states[index]["state"] != "postimage":
                continue
            _renew_owned_attempt_lease(
                journal,
                repair_id=repair_id,
                operation="restore",
                attempt_id=attempt_id,
                receipt_version=receipt_version,
            )
            _write_change_documents(
                normalized_manifest["changes"][index],
                databases=databases,
                document_field="preimage_documents",
            )
        restored_hash = _current_snapshot_hash(normalized_manifest, databases)
        if restored_hash != normalized_manifest["preimage_hash"]:
            raise RestoreStateMismatch(
                "restore write completed but scoped state does not match preimage hash"
            )
    except RepairIdConflict:
        raise
    except Exception as exc:
        try:
            _finish_owned_attempt(
                journal,
                repair_id=repair_id,
                operation="restore",
                attempt_id=attempt_id,
                receipt_version=receipt_version,
                status="restore_failed",
                values={
                    "restore_id": normalized_restore_id,
                    "restore_failed_at": _utc_now(),
                    "restore_error": f"{type(exc).__name__}: {exc}",
                },
            )
        except RepairIdConflict as receipt_exc:
            raise receipt_exc from exc
        raise

    _finish_owned_attempt(
        journal,
        repair_id=repair_id,
        operation="restore",
        attempt_id=attempt_id,
        receipt_version=receipt_version,
        status="restored",
        values={
            "restore_id": normalized_restore_id,
            "restored_at": _utc_now(),
            "restored_hash": normalized_manifest["preimage_hash"],
        },
    )
    return _repair_summary(
        normalized_manifest,
        execute=True,
        status="restored",
        idempotent=False,
    )


def load_repair_document(path: str | Path) -> dict[str, Any]:
    return json_util.loads(Path(path).read_text(encoding="utf-8"))


def build_repair_plan_hash(plan: Mapping[str, Any]) -> str:
    normalized_plan = _normalize_plan(plan)
    return _hash_value(normalized_plan)


def _apply_manifest(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
    journal,
    resumed: bool,
    attempt_id: str,
    receipt_version: int,
) -> dict[str, Any]:
    repair_id = str(manifest["repair_id"])
    already_applied = False
    observed_postimage_hash = ""

    try:
        _renew_owned_attempt_lease(
            journal,
            repair_id=repair_id,
            operation="apply",
            attempt_id=attempt_id,
            receipt_version=receipt_version,
        )
        change_states = _manifest_change_states(manifest, databases)
        if any(item["state"] == "diverged" for item in change_states):
            raise PreimageHashMismatch(
                "one or more scoped changes match neither preimage nor postimage"
            )
        if _all_changes_at(change_states, "postimage"):
            observed_postimage_hash = _current_snapshot_hash(manifest, databases)
            already_applied = observed_postimage_hash == manifest["postimage_hash"]
        if not already_applied:
            for index, change in enumerate(manifest["changes"]):
                if change_states[index]["state"] != "preimage":
                    continue
                _renew_owned_attempt_lease(
                    journal,
                    repair_id=repair_id,
                    operation="apply",
                    attempt_id=attempt_id,
                    receipt_version=receipt_version,
                )
                _write_change_documents(
                    change,
                    databases=databases,
                    document_field="postimage_documents",
                )
            observed_postimage_hash = _current_snapshot_hash(manifest, databases)
            if observed_postimage_hash != manifest["postimage_hash"]:
                raise TargetedRepairError(
                    "repair write completed but scoped state does not match postimage hash"
                )
    except RepairIdConflict:
        # Ownership has already moved to another attempt. Never rollback data that
        # the new owner may currently be reconciling.
        raise
    except Exception as exc:
        rollback_succeeded = False
        rollback_error = None
        try:
            _rollback_manifest_postimages(
                manifest,
                databases=databases,
                before_write=lambda: _renew_owned_attempt_lease(
                    journal,
                    repair_id=repair_id,
                    operation="apply",
                    attempt_id=attempt_id,
                    receipt_version=receipt_version,
                ),
            )
            rollback_succeeded = _all_changes_at(
                _manifest_change_states(manifest, databases),
                "preimage",
            )
        except Exception as rollback_exc:  # pragma: no cover - runtime safeguard
            rollback_error = f"{type(rollback_exc).__name__}: {rollback_exc}"
        try:
            _finish_owned_attempt(
                journal,
                repair_id=repair_id,
                operation="apply",
                attempt_id=attempt_id,
                receipt_version=receipt_version,
                status="failed",
                values={
                    "failed_at": _utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                    "rollback_succeeded": rollback_succeeded,
                    "rollback_error": rollback_error,
                },
            )
        except RepairIdConflict as receipt_exc:
            raise receipt_exc from exc
        raise

    _finish_owned_attempt(
        journal,
        repair_id=repair_id,
        operation="apply",
        attempt_id=attempt_id,
        receipt_version=receipt_version,
        status="applied",
        values={
            "applied_at": _utc_now(),
            "observed_postimage_hash": observed_postimage_hash,
            "resumed": bool(resumed),
        },
    )
    return _repair_summary(
        manifest,
        execute=True,
        status="already_applied" if already_applied else "applied",
        idempotent=already_applied,
    )


def _resume_or_report_existing_repair(
    *,
    existing: Mapping[str, Any],
    plan_hash: str,
    expected_preimage_hash: str,
    databases: Mapping[str, Any],
    journal,
) -> dict[str, Any]:
    repair_id = str(existing.get("repair_id") or "")
    if str(existing.get("plan_hash") or "") != plan_hash:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} is already bound to a different plan"
        )
    manifest_path = str(existing.get("manifest_path") or "").strip()
    if not manifest_path:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} has no recoverable manifest_path"
        )
    manifest = _validate_manifest(load_repair_document(manifest_path))
    _assert_receipt_matches_manifest(existing, manifest)
    _assert_expected_hash(
        expected=expected_preimage_hash,
        actual=manifest["preimage_hash"],
        label="preimage",
    )
    status = str(existing.get("status") or "")
    if status in {"restoring", "restore_failed", "restored"}:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} is in restore lifecycle state {status!r} "
            "and cannot be applied"
        )
    if status == "applied":
        current_hash = _current_snapshot_hash(manifest, databases)
        if current_hash != manifest["postimage_hash"]:
            raise RepairIdConflict(
                f"repair_id {repair_id!r} is marked applied but its postimage drifted"
            )
        return _repair_summary(
            manifest,
            execute=True,
            status="already_applied",
            idempotent=True,
        )
    if status not in {"applying", "failed"}:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} has unsupported apply state {status!r}"
        )
    attempt_id, receipt_version = _claim_attempt(
        journal,
        receipt=existing,
        operation="apply",
        allowed_statuses={"applying", "failed"},
    )
    return _apply_manifest(
        manifest=manifest,
        databases=databases,
        journal=journal,
        resumed=True,
        attempt_id=attempt_id,
        receipt_version=receipt_version,
    )


def _rollback_manifest_postimages(
    manifest: Mapping[str, Any],
    *,
    databases: Mapping[str, Any],
    before_write: Callable[[], None] | None = None,
) -> None:
    changes = list(manifest["changes"])
    for index in range(len(changes) - 1, -1, -1):
        current_state = _manifest_change_states(manifest, databases)[index]["state"]
        if current_state != "postimage":
            continue
        if before_write is not None:
            before_write()
        _write_change_documents(
            changes[index],
            databases=databases,
            document_field="preimage_documents",
        )


def _write_change_documents(
    change: Mapping[str, Any],
    *,
    databases: Mapping[str, Any],
    document_field: str,
) -> None:
    if change.get("mode", "replace") != "replace":
        return
    collection = databases[change["store"]][change["collection"]]
    target_documents = deepcopy(list(change[document_field]))
    expected_field = (
        "preimage_documents"
        if document_field == "postimage_documents"
        else "postimage_documents"
    )
    expected_documents = deepcopy(list(change[expected_field]))
    if len(target_documents) > 1 or len(expected_documents) > 1:
        raise InvalidRepairPlan("atomic replace change contains multiple documents")

    selector = deepcopy(change["selector"])
    current_documents = list(collection.find(selector))
    current_sorted = _sorted_documents(
        current_documents,
        identity_fields=change["identity_fields"],
    )
    expected_sorted = _sorted_documents(
        expected_documents,
        identity_fields=change["identity_fields"],
    )
    if _single_change_hash(change, current_sorted) != _single_change_hash(
        change,
        expected_sorted,
    ):
        raise TargetedRepairError(
            "repair compare-and-swap failed because current documents no longer "
            f"match {expected_field} for {change['store']}.{change['collection']}"
        )

    if target_documents and not expected_documents:
        target_id = _require_fixed_id_for_insert(change)
        try:
            collection.insert_one(target_documents[0])
        except DuplicateKeyError as exc:
            current_by_id = _sorted_documents(
                list(collection.find({"_id": deepcopy(target_id)})),
                identity_fields=change["identity_fields"],
            )
            if _single_change_hash(change, current_by_id) == _single_change_hash(
                change,
                target_documents,
            ):
                return
            raise TargetedRepairError(
                "repair compare-and-swap insert failed because the fixed _id "
                f"already contains a different document for "
                f"{change['store']}.{change['collection']}"
            ) from exc
        return

    if not expected_documents:
        return

    exact_selector = _exact_document_cas_selector(
        selector,
        current_document=current_documents[0],
    )
    if target_documents:
        result = collection.replace_one(
            exact_selector,
            target_documents[0],
            upsert=False,
        )
        matched_count = int(getattr(result, "matched_count", 0) or 0)
        if matched_count != 1:
            raise TargetedRepairError(
                "repair compare-and-swap replace failed because the source document "
                f"changed concurrently for {change['store']}.{change['collection']}"
            )
        return

    result = collection.delete_one(exact_selector)
    deleted_count = int(getattr(result, "deleted_count", 0) or 0)
    if deleted_count != 1:
        raise TargetedRepairError(
            "repair compare-and-swap delete failed because the source document "
            f"changed concurrently for {change['store']}.{change['collection']}"
        )


def _exact_document_cas_selector(
    selector: Mapping[str, Any],
    *,
    current_document: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "$and": [
            deepcopy(dict(selector)),
            {
                "$expr": {
                    "$eq": [
                        "$$ROOT",
                        {"$literal": deepcopy(dict(current_document))},
                    ]
                }
            },
        ]
    }


def _require_fixed_id_for_insert(change: Mapping[str, Any]) -> Any | None:
    if change.get("mode", "replace") != "replace":
        return None
    preimage_documents = list(change.get("preimage_documents") or [])
    postimage_documents = list(change.get("postimage_documents") or [])
    if preimage_documents or not postimage_documents:
        return None
    if len(postimage_documents) != 1:
        raise InvalidRepairPlan("atomic insert must contain exactly one postimage")
    target_document = postimage_documents[0]
    if "_id" not in target_document or target_document.get("_id") in (None, ""):
        raise InvalidRepairPlan("repair manifest insert requires a fixed non-empty _id")
    target_id = deepcopy(target_document["_id"])
    branches = _selector_branches(cast(Mapping[str, Any], change["selector"]))
    if not branches or any(
        len(branch.get("_id") or []) != 1
        or not _values_equal(branch["_id"][0], target_id)
        for branch in branches
    ):
        raise InvalidRepairPlan(
            "repair manifest insert selector must require the same fixed _id"
        )
    return target_id


def _current_snapshot_hash(
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> str:
    changes = []
    for change in manifest["changes"]:
        documents = list(
            databases[change["store"]][change["collection"]].find(
                deepcopy(change["selector"])
            )
        )
        changes.append(
            {
                "mode": change.get("mode", "replace"),
                "store": change["store"],
                "collection": change["collection"],
                "identity_fields": list(change["identity_fields"]),
                "current_documents": _sorted_documents(
                    documents,
                    identity_fields=change["identity_fields"],
                ),
            }
        )
    return _snapshot_hash(changes, "current_documents")


def _manifest_change_states(
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> list[dict[str, Any]]:
    states = []
    for index, change in enumerate(manifest["changes"]):
        current_documents = _sorted_documents(
            list(
                databases[change["store"]][change["collection"]].find(
                    deepcopy(change["selector"])
                )
            ),
            identity_fields=change["identity_fields"],
        )
        current_hash = _single_change_hash(change, current_documents)
        preimage_hash = _single_change_hash(change, change["preimage_documents"])
        postimage_hash = _single_change_hash(change, change["postimage_documents"])
        if current_hash == preimage_hash == postimage_hash:
            state = "unchanged"
        elif current_hash == preimage_hash:
            state = "preimage"
        elif current_hash == postimage_hash:
            state = "postimage"
        else:
            state = "diverged"
        states.append(
            {
                "index": index,
                "store": change["store"],
                "collection": change["collection"],
                "state": state,
            }
        )
    return states


def _all_changes_at(states, target):
    accepted = {target, "unchanged"}
    return all(item["state"] in accepted for item in states)


def _restore_state_is_executable(*, receipt_status, change_states):
    if any(item["state"] == "diverged" for item in change_states):
        return False
    if receipt_status == "applied":
        return _all_changes_at(change_states, "postimage")
    if receipt_status in {"restoring", "restore_failed"}:
        return all(
            item["state"] in {"preimage", "postimage", "unchanged"}
            for item in change_states
        )
    if receipt_status == "restored":
        return _all_changes_at(change_states, "preimage")
    return False


def _single_change_hash(change, documents):
    return _snapshot_hash(
        [
            {
                "mode": change.get("mode", "replace"),
                "store": change["store"],
                "collection": change["collection"],
                "identity_fields": change["identity_fields"],
                "documents": documents,
            }
        ],
        "documents",
    )


def _normalize_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise InvalidRepairPlan("repair plan must be an object")
    schema_version = int(plan.get("schema_version") or 0)
    if schema_version != TARGETED_REPAIR_SCHEMA_VERSION:
        raise InvalidRepairPlan(
            f"unsupported repair plan schema_version: {schema_version}"
        )
    repair_id = str(plan.get("repair_id") or "").strip()
    if not _REPAIR_ID_PATTERN.fullmatch(repair_id):
        raise InvalidRepairPlan(
            "repair_id must be 8-128 characters using letters, digits, '.', '_', ':' or '-'"
        )
    reason = str(plan.get("reason") or "").strip()
    if not reason:
        raise InvalidRepairPlan("reason must not be empty")
    scope = _normalize_scope(plan.get("scope"))
    raw_changes = plan.get("changes")
    if not isinstance(raw_changes, Sequence) or isinstance(raw_changes, (str, bytes)):
        raise InvalidRepairPlan("changes must be a non-empty array")
    changes = [_normalize_change(item, scope=scope) for item in list(raw_changes or [])]
    if not changes:
        raise InvalidRepairPlan("changes must be a non-empty array")
    return {
        "schema_version": schema_version,
        "repair_id": repair_id,
        "reason": reason,
        "scope": scope,
        "changes": changes,
    }


def _normalize_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan("scope must be an object")
    account_id = str(value.get("account_id") or "").strip()
    symbols = _normalize_scope_list(value.get("symbols"))
    # Broker truth can persist these identifiers as strings or BSON numerics.
    # Preserve the declared scalar types so alternate representations stay explicit.
    broker_order_ids = _normalize_scope_list(
        value.get("broker_order_ids"),
        stringify=False,
    )
    order_sysids = _normalize_scope_list(
        value.get("order_sysids"),
        stringify=False,
    )
    if not account_id:
        raise InvalidRepairPlan("scope.account_id must not be empty")
    if not symbols:
        raise InvalidRepairPlan("scope.symbols must not be empty")
    if not broker_order_ids and not order_sysids:
        raise InvalidRepairPlan("scope must include broker_order_ids or order_sysids")
    normalized: dict[str, Any] = {
        "account_id": account_id,
        "symbols": symbols,
        "broker_order_ids": broker_order_ids,
        "order_sysids": order_sysids,
    }
    for key in _SCOPE_FIELDS:
        if key in normalized or key == "account_id":
            continue
        values = _normalize_scope_list(value.get(key), stringify=False)
        if values:
            normalized[key] = values
    return normalized


def _normalize_change(value: Any, *, scope: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan("each change must be an object")
    store = str(value.get("store") or "").strip()
    collection = str(value.get("collection") or "").strip()
    mode = str(value.get("mode") or "replace").strip().lower()
    if store not in _SUPPORTED_STORES:
        raise InvalidRepairPlan(f"unsupported repair store: {store!r}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", collection):
        raise InvalidRepairPlan(f"invalid collection name: {collection!r}")
    if collection in _PROTECTED_COLLECTIONS:
        raise InvalidRepairPlan(
            f"append-only/audit collection cannot be mutated: {collection}"
        )
    if mode not in {"replace", "snapshot"}:
        raise InvalidRepairPlan(
            f"unsupported change mode for {store}.{collection}: {mode!r}"
        )
    selector_value = deepcopy(value.get("selector"))
    _validate_selector(selector_value)
    selector = cast(Mapping[str, Any], selector_value)
    _validate_selector_scope(selector, scope=scope, label=f"{store}.{collection}")
    identity_fields = [
        str(item or "").strip() for item in list(value.get("identity_fields") or [])
    ]
    if not identity_fields or any(not item for item in identity_fields):
        raise InvalidRepairPlan(
            f"identity_fields for {store}.{collection} must be non-empty"
        )
    if len(identity_fields) != len(set(identity_fields)):
        raise InvalidRepairPlan(
            f"identity_fields for {store}.{collection} contain duplicates"
        )
    desired_documents_value = deepcopy(value.get("desired_documents"))
    if mode == "snapshot" and desired_documents_value in (None, []):
        desired_documents_value = []
    if not isinstance(desired_documents_value, list) or any(
        not isinstance(item, Mapping) for item in desired_documents_value
    ):
        raise InvalidRepairPlan(
            f"desired_documents for {store}.{collection} must be an array of objects"
        )
    desired_documents = [
        dict(cast(Mapping[str, Any], item)) for item in desired_documents_value
    ]
    if mode == "snapshot" and desired_documents:
        raise InvalidRepairPlan(
            f"snapshot change for {store}.{collection} must not declare desired_documents"
        )
    if mode == "replace" and len(desired_documents) > 1:
        raise InvalidRepairPlan(
            f"replace change for {store}.{collection} may declare at most one desired document"
        )
    for document in desired_documents:
        if not _document_matches(document, selector):
            raise InvalidRepairPlan(
                f"desired document for {store}.{collection} escapes its stable selector"
            )
    _assert_documents_within_scope(
        desired_documents,
        scope=scope,
        label=f"{store}.{collection} desired_documents",
    )
    allowed_diff = _normalize_allowed_diff(
        value.get("allowed_diff"),
        identity_fields=identity_fields,
        store=store,
        collection=collection,
    )
    if mode == "snapshot" and _diff_count(allowed_diff):
        raise InvalidRepairPlan(
            f"snapshot change for {store}.{collection} must have an empty allowed_diff"
        )
    _ensure_unique_document_identities(
        desired_documents,
        identity_fields=identity_fields,
        label=f"{store}.{collection} desired_documents",
    )
    return {
        "mode": mode,
        "store": store,
        "collection": collection,
        "selector": selector,
        "identity_fields": identity_fields,
        "desired_documents": [dict(item) for item in desired_documents],
        "allowed_diff": allowed_diff,
    }


def _normalize_allowed_diff(
    value: Any,
    *,
    identity_fields: Sequence[str],
    store: str,
    collection: str,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        raise InvalidRepairPlan(
            f"allowed_diff for {store}.{collection} must be an object"
        )
    extra_keys = set(value) - {"inserted", "updated", "deleted"}
    if extra_keys:
        raise InvalidRepairPlan(
            f"allowed_diff for {store}.{collection} has unsupported keys: {sorted(extra_keys)}"
        )
    normalized: dict[str, list[dict[str, Any]]] = {}
    for action in ("inserted", "updated", "deleted"):
        identities = value.get(action, [])
        if not isinstance(identities, list):
            raise InvalidRepairPlan(
                f"allowed_diff.{action} for {store}.{collection} must be an array"
            )
        normalized[action] = _sorted_identities(
            identities,
            identity_fields=identity_fields,
            label=f"{store}.{collection} allowed_diff.{action}",
        )
    return normalized


def _normalize_scope_list(value: Any, *, stringify: bool = True) -> list[Any]:
    if value in (None, ""):
        return []
    values: list[Any] = (
        list(value) if isinstance(value, (list, tuple, set)) else [value]
    )
    normalized: list[Any] = []
    for item in values:
        if stringify:
            current = str(item).strip()
        elif isinstance(item, str):
            current = item.strip()
        else:
            current = deepcopy(item)
        if current in (None, ""):
            continue
        if not any(_values_equal(current, existing) for existing in normalized):
            normalized.append(current)
    return sorted(normalized, key=_scope_value_sort_key)


def _scope_value_sort_key(value: Any) -> tuple[int, str]:
    if isinstance(value, bool):
        rank = 2
    elif isinstance(value, (int, float)):
        rank = 0
    elif isinstance(value, str):
        rank = 1
    else:
        rank = 3
    return rank, _canonical_json(value)


def _validate_selector(selector: Any) -> None:
    if not isinstance(selector, Mapping) or not selector:
        raise InvalidRepairPlan("every change requires a non-empty selector")

    def visit(value: Any, *, in_field=False) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key = str(key)
                if key.startswith("$") and key not in _SAFE_QUERY_OPERATORS:
                    raise InvalidRepairPlan(f"unsafe selector operator: {key}")
                if key in {"$and", "$or"}:
                    if not isinstance(child, list) or not child:
                        raise InvalidRepairPlan(
                            f"selector {key} requires a non-empty array"
                        )
                    for item in child:
                        visit(item, in_field=False)
                elif key in {"$eq", "$in"}:
                    if not in_field:
                        raise InvalidRepairPlan(f"selector {key} must follow a field")
                    if key == "$in" and not isinstance(child, list):
                        raise InvalidRepairPlan("selector $in requires an array")
                else:
                    visit(child, in_field=True)
        elif isinstance(value, list) and not in_field:
            for item in value:
                visit(item, in_field=False)

    visit(selector)


def _validate_selector_scope(
    selector: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    label: str,
) -> None:
    scoped_values_by_field = _scoped_values_by_field(scope)
    stable_fields = {
        field
        for scope_key, fields in _SCOPE_FIELDS.items()
        if scope_key not in {"account_id", "symbols", "trading_days"}
        for field in fields
    }
    branches = _selector_branches(selector)
    if not branches:
        raise InvalidRepairPlan(f"selector for {label} has no logical branch")

    for branch in branches:
        for field, candidates in branch.items():
            if field not in scoped_values_by_field:
                continue
            allowed = scoped_values_by_field[field]
            if not allowed or any(
                not any(_values_equal(candidate, scoped) for scoped in allowed)
                for candidate in candidates
            ):
                raise InvalidRepairPlan(
                    f"selector branch for {label} escapes declared scope field {field}"
                )

        account_candidates = branch.get("account_id", [])
        document_id_candidates = branch.get("_id", [])
        account_anchored = bool(account_candidates) and all(
            _values_equal(item, scope["account_id"]) for item in account_candidates
        )
        document_anchored = bool(document_id_candidates) and _values_are_scoped(
            document_id_candidates,
            scope.get("document_ids") or [],
        )
        if not account_anchored and not document_anchored:
            raise InvalidRepairPlan(
                f"every selector branch for {label} requires account_id or an exact scoped _id"
            )

        stable_anchors = [
            field
            for field in stable_fields
            if branch.get(field)
            and _values_are_scoped(
                branch[field],
                scoped_values_by_field.get(field) or [],
            )
        ]
        if not stable_anchors:
            raise InvalidRepairPlan(
                f"every selector branch for {label} requires a stable order/execution/document closure key"
            )


def _selector_branches(selector: Mapping[str, Any]) -> list[dict[str, list[Any]]]:
    base: dict[str, list[Any]] = {}
    and_groups = []
    or_groups = []
    for key, value in selector.items():
        if key == "$and":
            and_groups.extend(value)
        elif key == "$or":
            or_groups.append(value)
        else:
            base[str(key)] = _selector_values(value)

    branches = [base]
    for child in and_groups:
        branches = _combine_selector_branches(branches, _selector_branches(child))
    for alternatives in or_groups:
        option_branches = [
            branch for option in alternatives for branch in _selector_branches(option)
        ]
        branches = _combine_selector_branches(branches, option_branches)
    return branches


def _combine_selector_branches(left, right):
    combined = []
    for left_branch in left:
        for right_branch in right:
            branch = deepcopy(left_branch)
            compatible = True
            for field, candidates in right_branch.items():
                if field in branch and not any(
                    _values_equal(left_value, right_value)
                    for left_value in branch[field]
                    for right_value in candidates
                ):
                    compatible = False
                    break
                branch.setdefault(field, [])
                for candidate in candidates:
                    if not any(
                        _values_equal(candidate, existing) for existing in branch[field]
                    ):
                        branch[field].append(candidate)
            if compatible:
                combined.append(branch)
    return combined


def _scoped_values_by_field(scope: Mapping[str, Any]) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {}
    for scope_key, fields in _SCOPE_FIELDS.items():
        raw_values = (
            [scope.get(scope_key)]
            if scope_key == "account_id"
            else scope.get(scope_key)
        )
        values = list(raw_values or [])
        for field in fields:
            result.setdefault(field, []).extend(values)
    return result


def _values_are_scoped(candidates, allowed):
    return (
        bool(candidates)
        and bool(allowed)
        and all(
            any(_values_equal(candidate, scoped) for scoped in allowed)
            for candidate in candidates
        )
    )


def _assert_documents_within_scope(
    documents: Sequence[Mapping[str, Any]],
    *,
    scope: Mapping[str, Any],
    label: str,
) -> None:
    scoped_values_by_field = _scoped_values_by_field(scope)
    for document in documents:
        for field, allowed in scoped_values_by_field.items():
            value = _get_path(document, field)
            if value in (None, "") or not allowed:
                continue
            if not any(_values_equal(value, scoped) for scoped in allowed):
                raise InvalidRepairPlan(
                    f"{label} document escapes declared scope field {field}"
                )


def _assert_staged_changes_do_not_overlap(changes: Sequence[Mapping[str, Any]]) -> None:
    for index, left in enumerate(changes):
        for right in changes[index + 1 :]:
            if (left["store"], left["collection"]) != (
                right["store"],
                right["collection"],
            ):
                continue
            left_documents = [
                *left["preimage_documents"],
                *left["postimage_documents"],
            ]
            right_documents = [
                *right["preimage_documents"],
                *right["postimage_documents"],
            ]
            if any(
                _document_matches(document, right["selector"])
                for document in left_documents
            ) or any(
                _document_matches(document, left["selector"])
                for document in right_documents
            ):
                raise InvalidRepairPlan(
                    f"overlapping selectors for {left['store']}.{left['collection']}"
                )


def _selector_values(value: Any) -> list[Any]:
    if isinstance(value, Mapping):
        if "$eq" in value:
            return [value["$eq"]]
        if "$in" in value:
            return list(value["$in"])
        return []
    return [value]


def _document_matches(document: Mapping[str, Any], selector: Mapping[str, Any]) -> bool:
    for key, expected in selector.items():
        if key == "$and":
            if not all(_document_matches(document, item) for item in expected):
                return False
            continue
        if key == "$or":
            if not any(_document_matches(document, item) for item in expected):
                return False
            continue
        actual = _get_path(document, key)
        if isinstance(expected, Mapping):
            if "$eq" in expected and not _values_equal(actual, expected["$eq"]):
                return False
            if "$in" in expected and not any(
                _values_equal(actual, item) for item in expected["$in"]
            ):
                return False
            continue
        if not _values_equal(actual, expected):
            return False
    return True


def _build_document_diff(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    before_by_id = _documents_by_identity(
        before,
        identity_fields=identity_fields,
        label="preimage",
    )
    after_by_id = _documents_by_identity(
        after,
        identity_fields=identity_fields,
        label="postimage",
    )
    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    inserted = after_ids - before_ids
    deleted = before_ids - after_ids
    updated = {
        identity
        for identity in before_ids & after_ids
        if _hash_value(_logical_document(before_by_id[identity], identity_fields))
        != _hash_value(_logical_document(after_by_id[identity], identity_fields))
    }
    identity_values = {
        **{
            key: _identity_document(value, identity_fields)
            for key, value in before_by_id.items()
        },
        **{
            key: _identity_document(value, identity_fields)
            for key, value in after_by_id.items()
        },
    }
    return {
        "inserted": [identity_values[key] for key in sorted(inserted)],
        "updated": [identity_values[key] for key in sorted(updated)],
        "deleted": [identity_values[key] for key in sorted(deleted)],
    }


def _assert_allowed_diff(
    *,
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    identity_fields: Sequence[str],
    store: str,
    collection: str,
) -> None:
    normalized_actual = {
        action: _sorted_identities(
            actual.get(action, []),
            identity_fields=identity_fields,
            label=f"actual {action}",
        )
        for action in ("inserted", "updated", "deleted")
    }
    if _canonical_json(normalized_actual) != _canonical_json(expected):
        raise AllowedDiffMismatch(
            f"allowed diff mismatch for {store}.{collection}: "
            f"expected={_canonical_json(expected)} actual={_canonical_json(normalized_actual)}"
        )


def _sorted_documents(
    documents: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
) -> list[dict[str, Any]]:
    cloned = [deepcopy(dict(item)) for item in documents]
    _ensure_unique_document_identities(
        cloned,
        identity_fields=identity_fields,
        label="documents",
    )
    return sorted(
        cloned,
        key=lambda item: _identity_token(item, identity_fields),
    )


def _sorted_identities(
    identities: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
    label: str,
) -> list[dict[str, Any]]:
    normalized = []
    for item in identities:
        if not isinstance(item, Mapping):
            raise InvalidRepairPlan(f"{label} contains a non-object identity")
        if set(item) != set(identity_fields):
            raise InvalidRepairPlan(
                f"{label} identity keys must exactly equal {list(identity_fields)}"
            )
        normalized.append({field: deepcopy(item[field]) for field in identity_fields})
    tokens = [_canonical_json(item) for item in normalized]
    if len(tokens) != len(set(tokens)):
        raise InvalidRepairPlan(f"{label} contains duplicate identities")
    return sorted(normalized, key=_canonical_json)


def _ensure_unique_document_identities(
    documents: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
    label: str,
) -> None:
    seen = set()
    for document in documents:
        identity = _identity_token(document, identity_fields)
        if identity in seen:
            raise InvalidRepairPlan(f"{label} contains duplicate identity {identity}")
        seen.add(identity)


def _documents_by_identity(
    documents: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    result = {}
    for document in documents:
        identity = _identity_token(document, identity_fields)
        if identity in result:
            raise InvalidRepairPlan(f"{label} contains duplicate identity {identity}")
        result[identity] = deepcopy(dict(document))
    return result


def _identity_token(document: Mapping[str, Any], fields: Sequence[str]) -> str:
    identity = _identity_document(document, fields)
    if any(value in (None, "") for value in identity.values()):
        raise InvalidRepairPlan(
            f"document identity has empty field: {_canonical_json(identity)}"
        )
    return _canonical_json(identity)


def _identity_document(
    document: Mapping[str, Any],
    fields: Sequence[str],
) -> dict[str, Any]:
    return {field: deepcopy(_get_path(document, field)) for field in fields}


def _snapshot_hash(changes: Sequence[Mapping[str, Any]], document_field: str) -> str:
    payload = [
        {
            "mode": item.get("mode", "replace"),
            "store": item["store"],
            "collection": item["collection"],
            "identity_fields": list(item["identity_fields"]),
            "documents": [
                _logical_document(document, item["identity_fields"])
                for document in item[document_field]
            ],
        }
        for item in changes
    ]
    return _hash_value(payload)


def _logical_document(
    document: Mapping[str, Any], identity_fields: Sequence[str]
) -> dict[str, Any]:
    normalized = deepcopy(dict(document))
    if "_id" not in set(identity_fields):
        normalized.pop("_id", None)
    return normalized


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "manifest_hash"}
    }
    return _hash_value(payload)


def _validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        raise InvalidRepairPlan("repair manifest must be an object")
    normalized = deepcopy(dict(manifest))
    if (
        int(normalized.get("schema_version") or 0)
        != TARGETED_REPAIR_MANIFEST_SCHEMA_VERSION
    ):
        raise InvalidRepairPlan("unsupported repair manifest schema_version")
    required = {
        "repair_id",
        "reason",
        "scope",
        "plan_hash",
        "preimage_hash",
        "postimage_hash",
        "manifest_hash",
        "changes",
    }
    missing = sorted(required - set(normalized))
    if missing:
        raise InvalidRepairPlan(f"repair manifest is missing fields: {missing}")
    if _manifest_hash(normalized) != str(normalized["manifest_hash"]):
        raise InvalidRepairPlan("repair manifest hash verification failed")

    repair_id = str(normalized.get("repair_id") or "").strip()
    if not _REPAIR_ID_PATTERN.fullmatch(repair_id):
        raise InvalidRepairPlan("repair manifest contains an invalid repair_id")
    reason = str(normalized.get("reason") or "").strip()
    if not reason:
        raise InvalidRepairPlan("repair manifest reason must not be empty")
    scope = _normalize_scope(normalized.get("scope"))
    raw_changes = normalized.get("changes")
    if not isinstance(raw_changes, Sequence) or isinstance(raw_changes, (str, bytes)):
        raise InvalidRepairPlan("repair manifest changes must be a non-empty array")
    if not raw_changes:
        raise InvalidRepairPlan("repair manifest changes must be a non-empty array")

    normalized_changes = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, Mapping):
            raise InvalidRepairPlan("repair manifest contains a non-object change")
        change = deepcopy(dict(raw_change))
        mode = str(change.get("mode") or "replace").strip().lower()
        if mode not in {"replace", "snapshot"}:
            raise InvalidRepairPlan(
                "repair manifest contains an unsupported change mode"
            )
        change["mode"] = mode
        store = str(change.get("store") or "").strip()
        collection = str(change.get("collection") or "").strip()
        if store not in _SUPPORTED_STORES:
            raise InvalidRepairPlan("repair manifest contains an unsupported store")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,127}", collection):
            raise InvalidRepairPlan("repair manifest contains an invalid collection")
        if collection in _PROTECTED_COLLECTIONS:
            raise InvalidRepairPlan("repair manifest targets a protected collection")
        change["store"] = store
        change["collection"] = collection

        selector_value = deepcopy(change.get("selector"))
        _validate_selector(selector_value)
        selector = cast(Mapping[str, Any], selector_value)
        _validate_selector_scope(
            selector,
            scope=scope,
            label=f"{store}.{collection}",
        )
        change["selector"] = selector

        identity_fields = [
            str(item or "").strip()
            for item in list(change.get("identity_fields") or [])
        ]
        if not identity_fields or any(not item for item in identity_fields):
            raise InvalidRepairPlan("repair manifest change has no identity_fields")
        if len(identity_fields) != len(set(identity_fields)):
            raise InvalidRepairPlan(
                "repair manifest change contains duplicate identity_fields"
            )
        change["identity_fields"] = identity_fields

        for field in ("preimage_documents", "postimage_documents"):
            documents_value = change.get(field)
            if not isinstance(documents_value, list) or any(
                not isinstance(item, Mapping) for item in documents_value
            ):
                raise InvalidRepairPlan(
                    f"repair manifest {field} must be an array of objects"
                )
            documents = _sorted_documents(
                [dict(cast(Mapping[str, Any], item)) for item in documents_value],
                identity_fields=identity_fields,
            )
            if mode == "replace" and len(documents) > 1:
                raise InvalidRepairPlan(
                    "repair manifest atomic replace contains multiple documents"
                )
            for document in documents:
                if not _document_matches(document, selector):
                    raise InvalidRepairPlan(
                        f"repair manifest {field} for {store}.{collection} "
                        "escapes its stable selector"
                    )
            _assert_documents_within_scope(
                documents,
                scope=scope,
                label=f"{store}.{collection} {field}",
            )
            change[field] = documents

        if mode == "snapshot" and _single_change_hash(
            change,
            change["preimage_documents"],
        ) != _single_change_hash(change, change["postimage_documents"]):
            raise InvalidRepairPlan(
                "repair manifest snapshot change must preserve its preimage"
            )
        _require_fixed_id_for_insert(change)
        if (
            mode == "replace"
            and _diff_count(
                _build_document_diff(
                    change["preimage_documents"],
                    change["postimage_documents"],
                    identity_fields=identity_fields,
                )
            )
            > 1
        ):
            raise InvalidRepairPlan(
                "repair manifest replace change is not one atomic mutation"
            )
        normalized_changes.append(change)

    normalized["repair_id"] = repair_id
    normalized["reason"] = reason
    normalized["scope"] = scope
    normalized["changes"] = normalized_changes
    _assert_staged_changes_do_not_overlap(normalized_changes)
    if _snapshot_hash(normalized["changes"], "preimage_documents") != str(
        normalized["preimage_hash"]
    ):
        raise InvalidRepairPlan("repair manifest preimage hash verification failed")
    if _snapshot_hash(normalized["changes"], "postimage_documents") != str(
        normalized["postimage_hash"]
    ):
        raise InvalidRepairPlan("repair manifest postimage hash verification failed")
    return normalized


def _persist_manifest(manifest: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json_util.dumps(
        manifest,
        json_options=json_util.RELAXED_JSON_OPTIONS,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
        return target
    except FileExistsError:
        existing = _validate_manifest(load_repair_document(target))
        for key in (
            "repair_id",
            "plan_hash",
            "preimage_hash",
            "postimage_hash",
            "manifest_hash",
        ):
            if str(existing.get(key) or "") != str(manifest.get(key) or ""):
                raise RepairIdConflict(
                    f"manifest path already contains different repair evidence: {target}"
                )
        return target


def _new_attempt_id(operation: str, repair_id: str) -> str:
    return f"{operation}:{repair_id}:{uuid.uuid4().hex}"


def _new_attempt_lease_expiry() -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=_REPAIR_ATTEMPT_LEASE_SECONDS)
    ).isoformat()


def _lease_is_active(value: Any) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        # A malformed non-empty lease must fail closed rather than authorizing a
        # competing repair attempt.
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) > datetime.now(timezone.utc)


def _receipt_version(receipt: Mapping[str, Any]) -> int:
    try:
        return int(receipt.get("receipt_version") or 0)
    except (TypeError, ValueError) as exc:
        raise RepairIdConflict("repair receipt has an invalid receipt_version") from exc


def _add_existing_receipt_field(
    selector: dict[str, Any],
    receipt: Mapping[str, Any],
    field: str,
) -> None:
    if field in receipt:
        selector[field] = deepcopy(receipt.get(field))
    else:
        selector[field] = {"$exists": False}


def _claim_attempt(
    journal,
    *,
    receipt: Mapping[str, Any],
    operation: str,
    allowed_statuses: set[str],
    restore_id: str | None = None,
) -> tuple[str, int]:
    repair_id = str(receipt.get("repair_id") or "")
    status = str(receipt.get("status") or "")
    if operation not in {"apply", "restore"}:
        raise ValueError(f"unsupported repair operation: {operation}")
    if status not in allowed_statuses:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} cannot start {operation} from status {status!r}"
        )

    active_status = "applying" if operation == "apply" else "restoring"
    attempt_field = f"{operation}_attempt_id"
    lease_field = f"{operation}_lease_expires_at"
    if status == active_status and _lease_is_active(receipt.get(lease_field)):
        raise RepairIdConflict(
            f"repair_id {repair_id!r} already has an active {operation} attempt"
        )

    normalized_restore_id = None
    if operation == "restore":
        normalized_restore_id = str(restore_id or "").strip()
        if not normalized_restore_id:
            raise InvalidRepairPlan("restore_id must not be empty")
        prior_restore_id = str(receipt.get("restore_id") or "").strip()
        if status in {"restoring", "restore_failed"} and (
            prior_restore_id and prior_restore_id != normalized_restore_id
        ):
            raise RepairIdConflict(
                f"repair_id {repair_id!r} is already bound to restore_id "
                f"{prior_restore_id!r}"
            )

    previous_version = _receipt_version(receipt)
    next_version = previous_version + 1
    attempt_id = _new_attempt_id(operation, repair_id)
    selector: dict[str, Any] = {
        "repair_id": repair_id,
        "status": status,
    }
    _add_existing_receipt_field(selector, receipt, "receipt_version")
    _add_existing_receipt_field(selector, receipt, attempt_field)
    _add_existing_receipt_field(selector, receipt, lease_field)
    if operation == "restore":
        _add_existing_receipt_field(selector, receipt, "restore_id")

    now = _utc_now()
    values: dict[str, Any] = {
        "status": active_status,
        "receipt_version": next_version,
        attempt_field: attempt_id,
        lease_field: _new_attempt_lease_expiry(),
        f"{operation}_last_attempt_at": now,
    }
    if operation == "apply":
        values["last_attempt_at"] = now
    else:
        values["restore_id"] = normalized_restore_id
        values["restore_started_at"] = now

    _checked_receipt_update(
        journal,
        selector=selector,
        update={"$set": values},
        message=(
            f"repair_id {repair_id!r} {operation} receipt changed while claiming "
            "attempt ownership"
        ),
    )
    return attempt_id, next_version


def _renew_owned_attempt_lease(
    journal,
    *,
    repair_id: str,
    operation: str,
    attempt_id: str,
    receipt_version: int,
) -> None:
    status = "applying" if operation == "apply" else "restoring"
    attempt_field = f"{operation}_attempt_id"
    lease_field = f"{operation}_lease_expires_at"
    _checked_receipt_update(
        journal,
        selector={
            "repair_id": repair_id,
            "status": status,
            "receipt_version": int(receipt_version),
            attempt_field: attempt_id,
        },
        update={
            "$set": {
                lease_field: _new_attempt_lease_expiry(),
                f"{operation}_last_attempt_at": _utc_now(),
            }
        },
        message=(
            f"repair_id {repair_id!r} lost {operation} attempt ownership while "
            "renewing its lease"
        ),
    )


def _finish_owned_attempt(
    journal,
    *,
    repair_id: str,
    operation: str,
    attempt_id: str,
    receipt_version: int,
    status: str,
    values: Mapping[str, Any],
) -> None:
    active_status = "applying" if operation == "apply" else "restoring"
    allowed_terminal_statuses = (
        {"applied", "failed"}
        if operation == "apply"
        else {"restored", "restore_failed"}
    )
    if status not in allowed_terminal_statuses:
        raise ValueError(
            f"unsupported terminal status {status!r} for repair operation {operation!r}"
        )
    attempt_field = f"{operation}_attempt_id"
    lease_field = f"{operation}_lease_expires_at"
    update_values = deepcopy(dict(values))
    update_values.update(
        {
            "status": status,
            "receipt_version": int(receipt_version) + 1,
            lease_field: None,
        }
    )
    _checked_receipt_update(
        journal,
        selector={
            "repair_id": repair_id,
            "status": active_status,
            "receipt_version": int(receipt_version),
            attempt_field: attempt_id,
        },
        update={"$set": update_values},
        message=(
            f"repair_id {repair_id!r} lost {operation} attempt ownership before "
            f"transitioning to {status!r}"
        ),
    )


def _checked_receipt_update(
    journal,
    *,
    selector: Mapping[str, Any],
    update: Mapping[str, Any],
    message: str,
) -> None:
    result = journal.update_one(
        deepcopy(dict(selector)),
        deepcopy(dict(update)),
        upsert=False,
    )
    if int(getattr(result, "matched_count", 0) or 0) != 1:
        raise RepairIdConflict(message)


def _assert_receipt_matches_manifest(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    for key in (
        "repair_id",
        "plan_hash",
        "preimage_hash",
        "postimage_hash",
        "manifest_hash",
    ):
        if str(receipt.get(key) or "") != str(manifest.get(key) or ""):
            raise RepairIdConflict(f"repair journal and manifest disagree on {key}")


def _require_restore_receipt(
    *,
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> dict[str, Any]:
    repair_id = str(manifest.get("repair_id") or "")
    journal = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION]
    receipt = journal.find_one({"repair_id": repair_id})
    if receipt is None:
        raise RepairIdConflict(
            f"repair_id {repair_id!r} has no matching applied repair receipt"
        )
    _assert_receipt_matches_manifest(receipt, manifest)
    status = str(receipt.get("status") or "")
    if status not in _RESTORABLE_RECEIPT_STATUSES:
        raise RestoreStateMismatch(
            f"repair_id {repair_id!r} receipt status {status!r} is not restorable"
        )
    return dict(receipt)


def _assert_expected_hash(*, expected: str, actual: str, label: str) -> None:
    normalized_expected = str(expected or "").strip().lower()
    if not normalized_expected:
        raise PreimageHashMismatch(f"expected {label} hash is required")
    if normalized_expected != str(actual or "").strip().lower():
        raise PreimageHashMismatch(
            f"{label} hash mismatch: expected={normalized_expected} actual={actual}"
        )


def _validate_databases(
    plan: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> None:
    required = {"order", *(item["store"] for item in plan["changes"])}
    missing = sorted(item for item in required if item not in databases)
    if missing:
        raise InvalidRepairPlan(f"database mapping is missing stores: {missing}")


def _validate_manifest_databases(
    manifest: Mapping[str, Any],
    databases: Mapping[str, Any],
) -> None:
    required = {"order", *(item["store"] for item in manifest["changes"])}
    missing = sorted(item for item in required if item not in databases)
    if missing:
        raise InvalidRepairPlan(f"database mapping is missing stores: {missing}")


def _ensure_journal_index(collection) -> None:
    if hasattr(collection, "create_index"):
        collection.create_index(
            [("repair_id", 1)],
            unique=True,
            name="uq_targeted_repair_id",
        )


def _repair_summary(
    manifest: Mapping[str, Any],
    *,
    execute: bool,
    status: str,
    idempotent: bool,
) -> dict[str, Any]:
    change_summaries = [
        {
            "index": index,
            "mode": item["mode"],
            "store": item["store"],
            "collection": item["collection"],
            "selector": deepcopy(item["selector"]),
            "identity_fields": list(item["identity_fields"]),
            "diff": deepcopy(item["diff"]),
            "diff_counts": {
                action: len(item["diff"][action])
                for action in ("inserted", "updated", "deleted")
            },
        }
        for index, item in enumerate(manifest["changes"])
    ]
    diff_counts: dict[str, dict[str, int]] = {}
    for item in change_summaries:
        key = f"{item['store']}.{item['collection']}"
        collection_counts = diff_counts.setdefault(
            key,
            {"inserted": 0, "updated": 0, "deleted": 0},
        )
        for action in ("inserted", "updated", "deleted"):
            collection_counts[action] += item["diff_counts"][action]
    return {
        "repair_id": manifest["repair_id"],
        "execute": bool(execute),
        "status": status,
        "idempotent": bool(idempotent),
        "plan_hash": manifest["plan_hash"],
        "preimage_hash": manifest["preimage_hash"],
        "postimage_hash": manifest["postimage_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "changes": change_summaries,
        "changed_collections": [
            f"{item['store']}.{item['collection']}"
            for item in manifest["changes"]
            if _diff_count(item["diff"])
        ],
        "diff_counts": diff_counts,
    }


def _diff_count(diff: Mapping[str, Any]) -> int:
    return sum(
        len(diff.get(action, [])) for action in ("inserted", "updated", "deleted")
    )


def _get_path(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    for part in str(path).split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _values_equal(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _canonical_json(value: Any) -> str:
    return json_util.dumps(
        value,
        json_options=json_util.CANONICAL_JSON_OPTIONS,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "AllowedDiffMismatch",
    "InvalidRepairPlan",
    "PreimageHashMismatch",
    "RepairIdConflict",
    "RestoreStateMismatch",
    "TARGETED_REPAIR_JOURNAL_COLLECTION",
    "build_repair_plan_hash",
    "execute_targeted_repair",
    "load_repair_document",
    "preview_targeted_restore",
    "restore_targeted_repair",
    "stage_targeted_repair",
]
