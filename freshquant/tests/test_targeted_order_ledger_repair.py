from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

import freshquant.order_management.repair.targeted_ledger as targeted_ledger_module
from freshquant.order_management.repair.targeted_ledger import (
    TARGETED_REPAIR_JOURNAL_COLLECTION,
    AllowedDiffMismatch,
    InvalidRepairPlan,
    PreimageHashMismatch,
    RepairIdConflict,
    RestoreStateMismatch,
    TargetedRepairError,
    execute_targeted_repair,
    load_repair_document,
    preview_targeted_restore,
    restore_targeted_repair,
    stage_targeted_repair,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script.maintenance.targeted_order_ledger_repair import run_repair_plan

EXISTING_BROKER_ORDER_DOCUMENT_ID = ObjectId("66b0a0000000000000000917")
REPAIRED_BROKER_ORDER_DOCUMENT_ID = ObjectId("66b0a0000000000000000772")
BROKER_TRADE_DOCUMENT_ID = ObjectId("66b0a0000000000000000001")


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = [_with_mongo_id(item) for item in list(documents or [])]
        self.unique_fields = {"_id"}

    def create_index(self, keys, **kwargs):
        if kwargs.get("unique") and len(keys) == 1:
            self.unique_fields.add(keys[0][0])
            for index, document in enumerate(self.documents):
                self._assert_unique(document, excluding_index=index)
        return None

    def find(self, query=None):
        query = query or {}
        return [deepcopy(item) for item in self.documents if _matches(item, query)]

    def find_one(self, query=None):
        rows = self.find(query)
        return rows[0] if rows else None

    def insert_one(self, document):
        document = _with_mongo_id(document)
        self._assert_unique(document)
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document.get("_id"))

    def insert_many(self, documents, ordered=False):
        del ordered
        rows = [_with_mongo_id(item) for item in documents]
        for row in rows:
            self._assert_unique(row)
            self.documents.append(row)
        return SimpleNamespace(inserted_ids=list(range(len(rows))))

    def delete_many(self, query):
        kept = [item for item in self.documents if not _matches(item, query)]
        deleted = len(self.documents) - len(kept)
        self.documents = kept
        return SimpleNamespace(deleted_count=deleted)

    def delete_one(self, query):
        for index, item in enumerate(self.documents):
            if _matches(item, query):
                self.documents.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def replace_one(self, query, document, upsert=False):
        for index, item in enumerate(self.documents):
            if not _matches(item, query):
                continue
            replacement = deepcopy(document)
            replacement.setdefault("_id", item.get("_id"))
            self._assert_unique(replacement, excluding_index=index)
            self.documents[index] = replacement
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        replacement = _with_mongo_id(document)
        self._assert_unique(replacement)
        self.documents.append(replacement)
        return SimpleNamespace(matched_count=0, upserted_id=replacement["_id"])

    def update_one(self, query, update, upsert=False):
        for item in self.documents:
            if not _matches(item, query):
                continue
            item.update(deepcopy(update.get("$set") or {}))
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        document = deepcopy(query)
        document.update(deepcopy(update.get("$setOnInsert") or {}))
        document.update(deepcopy(update.get("$set") or {}))
        document = _with_mongo_id(document)
        self._assert_unique(document)
        self.documents.append(document)
        return SimpleNamespace(matched_count=0, upserted_id=document.get("repair_id"))

    def _assert_unique(self, document, excluding_index=None):
        for field in self.unique_fields:
            if field not in document:
                continue
            value = document.get(field)
            for index, existing in enumerate(self.documents):
                if excluding_index is not None and index == excluding_index:
                    continue
                if existing.get(field) == value:
                    raise DuplicateKeyError(f"duplicate key for {field}")


class MemoryDatabase:
    def __init__(self, collections=None):
        self.collections = {
            name: MemoryCollection(documents)
            for name, documents in dict(collections or {}).items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, MemoryCollection())


def test_dry_run_captures_688772_and_600917_preimage_without_mutating_database():
    databases = _databases()
    plan = _plan()
    original = deepcopy(databases["order"]["om_broker_orders"].documents)

    manifest = stage_targeted_repair(plan=plan, databases=databases)

    assert databases["order"]["om_broker_orders"].documents == original
    assert databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents == []
    assert len(manifest["preimage_hash"]) == 64
    assert len(manifest["postimage_hash"]) == 64
    assert manifest["preimage_hash"] != manifest["postimage_hash"]
    assert manifest["changes"][0]["preimage_documents"] == original
    assert manifest["changes"][0]["diff"] == {
        "inserted": [],
        "updated": [{"internal_order_id": "order-600917"}],
        "deleted": [],
    }
    assert manifest["changes"][1]["diff"] == {
        "inserted": [{"internal_order_id": "order-688772"}],
        "updated": [],
        "deleted": [],
    }
    assert {
        item["symbol"]
        for change in manifest["changes"][:2]
        for item in change["postimage_documents"]
    } == {"600917", "688772"}
    assert manifest["changes"][2]["mode"] == "snapshot"
    assert manifest["changes"][2]["preimage_documents"][0]["stock_code"] == "688772"


def test_cli_dry_run_summary_preserves_each_change_for_a_repeated_collection():
    summary = run_repair_plan(
        plan=_plan(),
        databases=_databases(),
    )

    assert [
        (item["index"], item["store"], item["collection"])
        for item in summary["changes"]
    ] == [
        (0, "order", "om_broker_orders"),
        (1, "order", "om_broker_orders"),
        (2, "business", "xt_trades"),
    ]
    assert summary["changes"][0]["selector"] == {
        "account_id": "acct-A",
        "internal_order_id": "order-600917",
    }
    assert summary["changes"][0]["diff"]["updated"] == [
        {"internal_order_id": "order-600917"}
    ]
    assert summary["changes"][1]["diff"]["inserted"] == [
        {"internal_order_id": "order-688772"}
    ]
    assert summary["diff"]["order.om_broker_orders"] == {
        "inserted": [{"internal_order_id": "order-688772"}],
        "updated": [{"internal_order_id": "order-600917"}],
        "deleted": [],
    }


def test_numeric_broker_order_id_is_preserved_for_broker_truth_snapshot():
    numeric_order_id = 1209008130
    databases = _databases()
    plan = _plan()
    plan["scope"]["broker_order_ids"] = [numeric_order_id]
    for document in databases["order"]["om_broker_orders"].documents:
        document["broker_order_id"] = numeric_order_id
    for document in databases["business"]["xt_trades"].documents:
        document["broker_order_id"] = numeric_order_id
    for change in plan["changes"]:
        for document in change.get("desired_documents", []):
            document["broker_order_id"] = numeric_order_id
    plan["changes"][2]["selector"]["broker_order_id"] = numeric_order_id

    manifest = stage_targeted_repair(plan=plan, databases=databases)

    assert manifest["scope"]["broker_order_ids"] == [numeric_order_id]
    assert type(manifest["scope"]["broker_order_ids"][0]) is int
    assert (
        manifest["changes"][2]["preimage_documents"][0]["broker_order_id"]
        == numeric_order_id
    )


def test_broker_order_id_string_variant_must_be_explicitly_scoped():
    numeric_order_id = 1209008130
    databases = _databases()
    plan = _plan()
    plan["scope"]["broker_order_ids"] = [numeric_order_id]
    for document in databases["order"]["om_broker_orders"].documents:
        document["broker_order_id"] = numeric_order_id
    for change in plan["changes"][:2]:
        for document in change["desired_documents"]:
            document["broker_order_id"] = numeric_order_id

    with pytest.raises(InvalidRepairPlan, match="escapes declared scope"):
        stage_targeted_repair(plan=plan, databases=databases)

    plan["scope"]["broker_order_ids"].append(str(numeric_order_id))
    manifest = stage_targeted_repair(plan=plan, databases=databases)

    assert manifest["scope"]["broker_order_ids"] == [
        numeric_order_id,
        str(numeric_order_id),
    ]


def test_execute_rejects_stale_preimage_hash_before_writing(tmp_path: Path):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    databases["order"]["om_broker_orders"].documents[0]["filled_price"] = 6.2

    with pytest.raises(PreimageHashMismatch, match="preimage hash mismatch"):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    assert databases["order"]["om_broker_orders"].documents[0]["filled_price"] == 6.2
    assert databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents == []
    assert not (tmp_path / "repair.json").exists()


def test_apply_compare_and_swap_preserves_concurrent_document_update(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    collection = databases["order"]["om_broker_orders"]
    original_replace = collection.replace_one
    raced = False

    def replace_with_concurrent_update(query, document, upsert=False):
        nonlocal raced
        if not raced and document.get("internal_order_id") == "order-600917":
            raced = True
            collection.documents[0].update(
                {
                    "filled_quantity": 777,
                    "filled_price": 99.0,
                    "concurrent_marker": "preserve-me",
                }
            )
        return original_replace(query, document, upsert=upsert)

    monkeypatch.setattr(collection, "replace_one", replace_with_concurrent_update)

    with pytest.raises(TargetedRepairError, match="compare-and-swap replace failed"):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    assert collection.documents[0]["filled_quantity"] == 777
    assert collection.documents[0]["filled_price"] == 99.0
    assert collection.documents[0]["concurrent_marker"] == "preserve-me"
    assert all(
        item.get("internal_order_id") != "order-688772" for item in collection.documents
    )


def test_rollback_compare_and_swap_does_not_overwrite_concurrent_update(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    collection = databases["order"]["om_broker_orders"]
    original_insert = collection.insert_one
    original_replace = collection.replace_one
    rollback_raced = False

    def fail_second_change(document):
        if document.get("internal_order_id") == "order-688772":
            raise RuntimeError("force second change failure")
        return original_insert(document)

    def replace_with_rollback_race(query, document, upsert=False):
        nonlocal rollback_raced
        if (
            not rollback_raced
            and document.get("internal_order_id") == "order-600917"
            and document.get("filled_quantity") == 48700
        ):
            rollback_raced = True
            collection.documents[0].update(
                {
                    "filled_quantity": 777,
                    "filled_price": 99.0,
                    "concurrent_marker": "preserve-rollback-race",
                }
            )
        return original_replace(query, document, upsert=upsert)

    monkeypatch.setattr(collection, "insert_one", fail_second_change)
    monkeypatch.setattr(collection, "replace_one", replace_with_rollback_race)

    with pytest.raises(RuntimeError, match="force second change failure"):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    assert collection.documents[0]["filled_quantity"] == 777
    assert collection.documents[0]["filled_price"] == 99.0
    assert collection.documents[0]["concurrent_marker"] == "preserve-rollback-race"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["rollback_succeeded"] is False
    assert "compare-and-swap replace failed" in receipt["rollback_error"]


def test_concurrent_execute_cannot_take_over_active_apply_lease(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    original_write = targeted_ledger_module._write_change_documents
    nested_attempted = False

    def write_with_competing_execute(
        change,
        *,
        databases,
        document_field,
    ):
        nonlocal nested_attempted
        if document_field == "postimage_documents" and not nested_attempted:
            nested_attempted = True
            with pytest.raises(RepairIdConflict, match="active apply attempt"):
                execute_targeted_repair(
                    plan=plan,
                    databases=databases,
                    expected_preimage_hash=preview["preimage_hash"],
                    manifest_path=manifest_path,
                )
        return original_write(
            change,
            databases=databases,
            document_field=document_field,
        )

    monkeypatch.setattr(
        targeted_ledger_module,
        "_write_change_documents",
        write_with_competing_execute,
    )

    result = execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )

    assert nested_attempted is True
    assert result["status"] == "applied"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "applied"
    assert receipt["receipt_version"] == 2
    assert receipt["apply_lease_expires_at"] is None


def test_apply_stops_before_writing_when_receipt_disappears(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    original = deepcopy(databases["order"]["om_broker_orders"].documents)
    preview = stage_targeted_repair(plan=plan, databases=databases)
    journal = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION]
    original_update = journal.update_one
    removed = False

    def update_after_receipt_loss(query, update, upsert=False):
        nonlocal removed
        if not removed and query.get("status") == "applying":
            removed = True
            journal.documents.clear()
            return SimpleNamespace(matched_count=0, upserted_id=None)
        return original_update(query, update, upsert=upsert)

    monkeypatch.setattr(journal, "update_one", update_after_receipt_loss)

    with pytest.raises(RepairIdConflict, match="lost apply attempt ownership"):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    assert removed is True
    assert databases["order"]["om_broker_orders"].documents == original
    assert journal.documents == []


def test_insert_compare_and_swap_preserves_competing_fixed_id_document(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    collection = databases["order"]["om_broker_orders"]
    original_insert = collection.insert_one
    raced = False

    def insert_with_fixed_id_race(document):
        nonlocal raced
        if document.get("_id") == REPAIRED_BROKER_ORDER_DOCUMENT_ID and not raced:
            raced = True
            concurrent = deepcopy(document)
            concurrent["filled_quantity"] = 777
            concurrent["filled_price"] = 99.0
            concurrent["concurrent_marker"] = "preserve-fixed-id-race"
            original_insert(concurrent)
        return original_insert(document)

    monkeypatch.setattr(collection, "insert_one", insert_with_fixed_id_race)

    with pytest.raises(
        TargetedRepairError,
        match="fixed _id already contains a different document",
    ):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    documents_by_id = {item["_id"]: item for item in collection.documents}
    assert (
        documents_by_id[EXISTING_BROKER_ORDER_DOCUMENT_ID]["filled_quantity"] == 48700
    )
    competing = documents_by_id[REPAIRED_BROKER_ORDER_DOCUMENT_ID]
    assert competing["filled_quantity"] == 777
    assert competing["filled_price"] == 99.0
    assert competing["concurrent_marker"] == "preserve-fixed-id-race"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "failed"
    assert receipt["rollback_succeeded"] is False


def test_insert_requires_same_fixed_id_in_document_and_selector():
    databases = _databases()
    plan = _plan()
    insert_change = plan["changes"][1]
    insert_change["selector"] = {
        "account_id": "acct-A",
        "internal_order_id": "order-688772",
    }
    insert_change["desired_documents"][0].pop("_id")

    with pytest.raises(InvalidRepairPlan, match="requires a fixed non-empty _id"):
        stage_targeted_repair(plan=plan, databases=databases)


def test_allowed_diff_blocks_unplanned_delete():
    databases = _databases()
    plan = _plan()
    plan["changes"][0]["allowed_diff"]["updated"] = []

    with pytest.raises(AllowedDiffMismatch, match="allowed diff mismatch"):
        stage_targeted_repair(plan=plan, databases=databases)


def test_symbol_only_selector_is_rejected_before_database_read():
    plan = _plan()
    plan["changes"][0]["selector"] = {"symbol": "600917"}

    with pytest.raises(InvalidRepairPlan, match="requires account_id"):
        stage_targeted_repair(plan=plan, databases=_databases())


def test_repair_id_is_idempotent_after_successful_apply(tmp_path: Path):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"

    first = execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    second = execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )

    assert first["status"] == "applied"
    assert first["idempotent"] is False
    assert second["status"] == "already_applied"
    assert second["idempotent"] is True
    assert [item["index"] for item in first["changes"]] == [0, 1, 2]
    assert first["diff_counts"]["order.om_broker_orders"] == {
        "inserted": 1,
        "updated": 1,
        "deleted": 0,
    }
    assert first["changes"][0]["diff_counts"] == {
        "inserted": 0,
        "updated": 1,
        "deleted": 0,
    }
    repaired_by_symbol = {
        item["symbol"]: item
        for item in databases["order"]["om_broker_orders"].documents
    }
    assert repaired_by_symbol["600917"]["filled_quantity"] == 38700
    assert repaired_by_symbol["600917"]["filled_price"] == 5.16
    assert repaired_by_symbol["688772"]["filled_quantity"] == 10000
    assert repaired_by_symbol["688772"]["filled_price"] == 14.7
    assert all("_id" in item for item in repaired_by_symbol.values())
    assert (
        preview["changes"][1]["postimage_documents"][0]["_id"]
        == REPAIRED_BROKER_ORDER_DOCUMENT_ID
    )
    assert len(databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents) == 1
    persisted = load_repair_document(manifest_path)
    assert persisted["manifest_hash"] == preview["manifest_hash"]


def test_restore_round_trip_requires_exact_postimage_and_is_idempotent(tmp_path: Path):
    databases = _databases()
    plan = _plan()
    original = deepcopy(databases["order"]["om_broker_orders"].documents)
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    manifest = load_repair_document(manifest_path)

    restore_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )
    restored = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=restore_preview["current_hash"],
    )
    restored_again = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=restore_preview["current_hash"],
    )

    assert restore_preview["restorable"] is True
    assert restored["status"] == "restored"
    assert restored_again["status"] == "already_restored"
    assert databases["order"]["om_broker_orders"].documents == original
    assert databases["business"]["xt_trades"].documents[0]["price"] == 14.7
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "restored"
    assert receipt["restore_id"] == "restore:fix-504-688772-v1"

    already_restored_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )
    assert already_restored_preview["receipt_status"] == "restored"
    assert already_restored_preview["restorable"] is True


def test_concurrent_restore_cannot_take_over_active_restore_lease(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    manifest = load_repair_document(manifest_path)
    restore_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )
    original_write = targeted_ledger_module._write_change_documents
    nested_attempted = False

    def write_with_competing_restore(
        change,
        *,
        databases,
        document_field,
    ):
        nonlocal nested_attempted
        if document_field == "preimage_documents" and not nested_attempted:
            nested_attempted = True
            with pytest.raises(RepairIdConflict, match="active restore attempt"):
                restore_targeted_repair(
                    manifest=manifest,
                    databases=databases,
                    expected_current_hash=restore_preview["current_hash"],
                )
        return original_write(
            change,
            databases=databases,
            document_field=document_field,
        )

    monkeypatch.setattr(
        targeted_ledger_module,
        "_write_change_documents",
        write_with_competing_restore,
    )

    result = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=restore_preview["current_hash"],
    )

    assert nested_attempted is True
    assert result["status"] == "restored"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "restored"
    assert receipt["receipt_version"] == 4
    assert receipt["restore_lease_expires_at"] is None


def test_execute_is_rejected_while_restore_lifecycle_is_active(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    manifest = load_repair_document(manifest_path)
    restore_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )
    original_write = targeted_ledger_module._write_change_documents
    nested_attempted = False

    def write_with_competing_execute(
        change,
        *,
        databases,
        document_field,
    ):
        nonlocal nested_attempted
        if document_field == "preimage_documents" and not nested_attempted:
            nested_attempted = True
            with pytest.raises(RepairIdConflict, match="restore lifecycle state"):
                execute_targeted_repair(
                    plan=plan,
                    databases=databases,
                    expected_preimage_hash=preview["preimage_hash"],
                    manifest_path=manifest_path,
                )
        return original_write(
            change,
            databases=databases,
            document_field=document_field,
        )

    monkeypatch.setattr(
        targeted_ledger_module,
        "_write_change_documents",
        write_with_competing_execute,
    )

    result = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=restore_preview["current_hash"],
    )

    assert nested_attempted is True
    assert result["status"] == "restored"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "restored"


def test_restore_preview_rejects_partial_state_without_restoring_receipt(
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    databases["order"]["om_broker_orders"].delete_one(
        {"account_id": "acct-A", "internal_order_id": "order-688772"}
    )
    manifest = load_repair_document(manifest_path)

    restore_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )

    assert restore_preview["receipt_status"] == "applied"
    assert restore_preview["restorable"] is False
    with pytest.raises(
        RestoreStateMismatch,
        match="partial restore state is resumable only from a restoring receipt",
    ):
        restore_targeted_repair(
            manifest=manifest,
            databases=databases,
            expected_current_hash=restore_preview["current_hash"],
        )


def test_restore_requires_existing_matching_repair_receipt():
    databases = _databases()
    manifest = stage_targeted_repair(plan=_plan(), databases=databases)

    with pytest.raises(RepairIdConflict, match="no matching applied repair receipt"):
        restore_targeted_repair(
            manifest=manifest,
            databases=databases,
            expected_current_hash=manifest["preimage_hash"],
        )


@pytest.mark.parametrize("receipt_status", ["applying", "failed"])
def test_restore_rejects_non_restorable_receipt_status(
    receipt_status,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0][
        "status"
    ] = receipt_status

    with pytest.raises(RestoreStateMismatch, match="is not restorable"):
        preview_targeted_restore(
            manifest=load_repair_document(manifest_path),
            databases=databases,
        )


def test_restore_revalidates_manifest_selector_scope():
    databases = _databases()
    manifest = stage_targeted_repair(plan=_plan(), databases=databases)
    manifest["changes"][0]["selector"] = {"symbol": "600917"}
    manifest["manifest_hash"] = targeted_ledger_module._manifest_hash(manifest)

    with pytest.raises(InvalidRepairPlan, match="requires account_id"):
        preview_targeted_restore(manifest=manifest, databases=databases)


def test_restore_revalidates_manifest_document_scope():
    databases = _databases()
    manifest = stage_targeted_repair(plan=_plan(), databases=databases)
    manifest["scope"]["symbols"] = ["600917"]
    manifest["manifest_hash"] = targeted_ledger_module._manifest_hash(manifest)

    with pytest.raises(InvalidRepairPlan, match="escapes declared scope field symbol"):
        preview_targeted_restore(manifest=manifest, databases=databases)


def test_apply_resumes_when_atomic_changes_are_individually_pre_or_post(tmp_path: Path):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    databases["order"]["om_broker_orders"].delete_one(
        {"account_id": "acct-A", "internal_order_id": "order-688772"}
    )
    databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0][
        "status"
    ] = "applying"

    resumed = execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )

    assert resumed["status"] == "applied"
    assert resumed["idempotent"] is False
    assert {
        item["symbol"] for item in databases["order"]["om_broker_orders"].documents
    } == {"600917", "688772"}


def test_failed_apply_rolls_back_only_postimages_and_preserves_diverged_change(
    monkeypatch,
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    preview = stage_targeted_repair(plan=plan, databases=databases)
    original_write = targeted_ledger_module._write_change_documents
    postimage_write_count = 0

    def write_with_concurrent_divergence(
        change,
        *,
        databases,
        document_field,
    ):
        nonlocal postimage_write_count
        if document_field == "postimage_documents":
            postimage_write_count += 1
            if postimage_write_count == 2:
                databases["order"]["om_broker_orders"].replace_one(
                    change["selector"],
                    {
                        "_id": REPAIRED_BROKER_ORDER_DOCUMENT_ID,
                        "internal_order_id": "order-688772",
                        "account_id": "acct-A",
                        "trading_day": 20260804,
                        "symbol": "688772",
                        "broker_order_id": "1209008130",
                        "side": "buy",
                        "filled_quantity": 777,
                        "filled_price": 99.0,
                        "concurrent_marker": "preserve-me",
                    },
                    upsert=True,
                )
                raise RuntimeError("simulated concurrent divergence")
        return original_write(
            change,
            databases=databases,
            document_field=document_field,
        )

    monkeypatch.setattr(
        targeted_ledger_module,
        "_write_change_documents",
        write_with_concurrent_divergence,
    )

    with pytest.raises(RuntimeError, match="simulated concurrent divergence"):
        execute_targeted_repair(
            plan=plan,
            databases=databases,
            expected_preimage_hash=preview["preimage_hash"],
            manifest_path=tmp_path / "repair.json",
        )

    documents_by_order_id = {
        item["internal_order_id"]: item
        for item in databases["order"]["om_broker_orders"].documents
    }
    assert documents_by_order_id["order-600917"]["filled_quantity"] == 48700
    assert documents_by_order_id["order-600917"]["filled_price"] == 7.118932
    assert documents_by_order_id["order-688772"]["filled_quantity"] == 777
    assert documents_by_order_id["order-688772"]["filled_price"] == 99.0
    assert documents_by_order_id["order-688772"]["concurrent_marker"] == "preserve-me"
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    assert receipt["status"] == "failed"
    assert receipt["rollback_succeeded"] is False


def test_restore_resumes_in_reverse_from_individual_pre_or_post_states(
    tmp_path: Path,
):
    databases = _databases()
    plan = _plan()
    original = deepcopy(databases["order"]["om_broker_orders"].documents)
    preview = stage_targeted_repair(plan=plan, databases=databases)
    manifest_path = tmp_path / "repair.json"
    execute_targeted_repair(
        plan=plan,
        databases=databases,
        expected_preimage_hash=preview["preimage_hash"],
        manifest_path=manifest_path,
    )
    databases["order"]["om_broker_orders"].delete_one(
        {"account_id": "acct-A", "internal_order_id": "order-688772"}
    )
    receipt = databases["order"][TARGETED_REPAIR_JOURNAL_COLLECTION].documents[0]
    receipt["status"] = "restoring"
    receipt["restore_id"] = "restore:fix-504-688772-v1"
    manifest = load_repair_document(manifest_path)
    restore_preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
    )

    restored = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_current_hash=restore_preview["current_hash"],
    )

    assert restore_preview["restorable"] is True
    assert restored["status"] == "restored"
    assert databases["order"]["om_broker_orders"].documents == original


def _databases():
    return {
        "order": MemoryDatabase(
            {
                "om_broker_orders": [
                    {
                        "_id": EXISTING_BROKER_ORDER_DOCUMENT_ID,
                        "internal_order_id": "order-600917",
                        "account_id": "acct-A",
                        "trading_day": 20260715,
                        "symbol": "600917",
                        "broker_order_id": "1209008130",
                        "side": "buy",
                        "filled_quantity": 48700,
                        "filled_price": 7.118932,
                    }
                ]
            }
        ),
        "business": MemoryDatabase(
            {
                "xt_trades": [
                    {
                        "_id": BROKER_TRADE_DOCUMENT_ID,
                        "account_id": "acct-A",
                        "stock_code": "688772",
                        "side": "buy",
                        "broker_order_id": "1209008130",
                        "broker_trade_id": "trade-1",
                        "quantity": 10000,
                        "price": 14.7,
                    }
                ]
            }
        ),
    }


def _plan():
    return {
        "schema_version": 1,
        "repair_id": "fix-504-688772-v1",
        "reason": "repair cross-symbol broker identity contamination",
        "scope": {
            "account_id": "acct-A",
            "symbols": ["688772", "600917"],
            "broker_order_ids": ["1209008130"],
            "trading_days": [20260715, 20260804],
            "internal_order_ids": ["order-600917", "order-688772"],
            "document_ids": [
                EXISTING_BROKER_ORDER_DOCUMENT_ID,
                REPAIRED_BROKER_ORDER_DOCUMENT_ID,
                BROKER_TRADE_DOCUMENT_ID,
            ],
        },
        "changes": [
            {
                "store": "order",
                "collection": "om_broker_orders",
                "selector": {
                    "account_id": "acct-A",
                    "internal_order_id": "order-600917",
                },
                "identity_fields": ["internal_order_id"],
                "desired_documents": [
                    {
                        "internal_order_id": "order-600917",
                        "account_id": "acct-A",
                        "trading_day": 20260715,
                        "symbol": "600917",
                        "broker_order_id": "1209008130",
                        "side": "buy",
                        "filled_quantity": 38700,
                        "filled_price": 5.16,
                    }
                ],
                "allowed_diff": {
                    "inserted": [],
                    "updated": [{"internal_order_id": "order-600917"}],
                    "deleted": [],
                },
            },
            {
                "store": "order",
                "collection": "om_broker_orders",
                "selector": {
                    "_id": REPAIRED_BROKER_ORDER_DOCUMENT_ID,
                },
                "identity_fields": ["internal_order_id"],
                "desired_documents": [
                    {
                        "_id": REPAIRED_BROKER_ORDER_DOCUMENT_ID,
                        "internal_order_id": "order-688772",
                        "account_id": "acct-A",
                        "trading_day": 20260804,
                        "symbol": "688772",
                        "broker_order_id": "1209008130",
                        "side": "buy",
                        "filled_quantity": 10000,
                        "filled_price": 14.7,
                    },
                ],
                "allowed_diff": {
                    "inserted": [{"internal_order_id": "order-688772"}],
                    "updated": [],
                    "deleted": [],
                },
            },
            {
                "mode": "snapshot",
                "store": "business",
                "collection": "xt_trades",
                "selector": {
                    "account_id": "acct-A",
                    "broker_order_id": "1209008130",
                },
                "identity_fields": ["broker_trade_id"],
                "allowed_diff": {
                    "inserted": [],
                    "updated": [],
                    "deleted": [],
                },
            },
        ],
    }


def _matches(document, query):
    for key, expected in query.items():
        if key == "$and":
            if not all(_matches(document, item) for item in expected):
                return False
            continue
        if key == "$or":
            if not any(_matches(document, item) for item in expected):
                return False
            continue
        if key == "$expr":
            operands = expected.get("$eq") if isinstance(expected, dict) else None
            if not isinstance(operands, list) or len(operands) != 2:
                return False

            def resolve_operand(value):
                if value == "$$ROOT":
                    return document
                if isinstance(value, dict) and set(value) == {"$literal"}:
                    return value["$literal"]
                return value

            if resolve_operand(operands[0]) != resolve_operand(operands[1]):
                return False
            continue
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected:
                if bool(expected["$exists"]) != (key in document):
                    return False
            if "$eq" in expected and actual != expected["$eq"]:
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _with_mongo_id(document):
    row = deepcopy(document)
    row.setdefault("_id", ObjectId())
    return row
