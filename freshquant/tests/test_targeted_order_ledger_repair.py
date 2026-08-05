from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from bson import ObjectId

from freshquant.order_management.repair.targeted_ledger import (
    TARGETED_REPAIR_JOURNAL_COLLECTION,
    AllowedDiffMismatch,
    InvalidRepairPlan,
    PreimageHashMismatch,
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


class MemoryCollection:
    def __init__(self, documents=None):
        self.documents = [_with_mongo_id(item) for item in list(documents or [])]

    def create_index(self, *_args, **_kwargs):
        return None

    def find(self, query=None):
        query = query or {}
        return [deepcopy(item) for item in self.documents if _matches(item, query)]

    def find_one(self, query=None):
        rows = self.find(query)
        return rows[0] if rows else None

    def insert_one(self, document):
        if self.find_one({"repair_id": document.get("repair_id")}) is not None:
            raise AssertionError("duplicate repair_id")
        document = _with_mongo_id(document)
        self.documents.append(document)
        return SimpleNamespace(inserted_id=document.get("repair_id"))

    def insert_many(self, documents, ordered=False):
        del ordered
        rows = [_with_mongo_id(item) for item in documents]
        self.documents.extend(rows)
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
            self.documents[index] = replacement
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if not upsert:
            return SimpleNamespace(matched_count=0, upserted_id=None)
        replacement = _with_mongo_id(document)
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
        self.documents.append(document)
        return SimpleNamespace(matched_count=0, upserted_id=document.get("repair_id"))


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
    assert "_id" not in preview["changes"][1]["postimage_documents"][0]
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
                    "account_id": "acct-A",
                    "internal_order_id": "order-688772",
                },
                "identity_fields": ["internal_order_id"],
                "desired_documents": [
                    {
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
        actual = document.get(key)
        if isinstance(expected, dict):
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
