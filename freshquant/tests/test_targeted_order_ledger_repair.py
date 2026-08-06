from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, json_util
from pymongo.errors import DuplicateKeyError

from freshquant.order_management.repair.targeted_ledger import (
    InvalidRepairPlan,
    ManifestHashMismatch,
    PlanFileHashMismatch,
    PreimageHashMismatch,
    RepairRollbackIncomplete,
    TargetedRepairError,
    execute_targeted_repair,
    load_repair_document,
    preview_targeted_restore,
    restore_targeted_repair,
    sha256_file,
    stage_targeted_repair,
)

TARGET_MAIN_SHA = "2e8754590c1b108637eaf2370ec99f5b1257810f"
ACCOUNT_ID = "068000087558"
SYMBOLS = ["600917", "688772"]
TRADING_DAYS = [20260528, 20260804, 20260805]
REPAIR_ID = "fix-504-688772-v1"


class _WriteResult:
    def __init__(self, *, matched_count=0, deleted_count=0, inserted_id=None):
        self.matched_count = matched_count
        self.deleted_count = deleted_count
        self.inserted_id = inserted_id


class MemoryCollection:
    """Small Mongo-shaped fake with exact-document CAS and mutation tracing."""

    def __init__(self, documents=None, *, name="", store="", database=None):
        self.name = name
        self.store = store
        self.database = database
        self.documents = [deepcopy(item) for item in list(documents or [])]
        self.before_insert = None
        self.before_replace = None
        self.before_delete = None

    @property
    def mutation_log(self):
        return self.database.mutation_log if self.database is not None else []

    def find_one(self, query):
        self.database.access_log.append((self.store, self.name, "find_one"))
        for document in self.documents:
            if _matches(document, query):
                return deepcopy(document)
        return None

    def find(self, query=None):
        self.database.access_log.append((self.store, self.name, "find"))
        return [
            deepcopy(item) for item in self.documents if _matches(item, query or {})
        ]

    def insert_one(self, document):
        if self.before_insert is not None:
            self.before_insert(deepcopy(document))
        if any(item.get("_id") == document.get("_id") for item in self.documents):
            raise DuplicateKeyError("duplicate _id")
        self.documents.append(deepcopy(document))
        self.mutation_log.append(
            {
                "operation": "insert",
                "store": self.store,
                "collection": self.name,
                "document_id": deepcopy(document.get("_id")),
                "document": deepcopy(document),
            }
        )
        return _WriteResult(inserted_id=deepcopy(document.get("_id")))

    def replace_one(self, query, document, upsert=False):
        assert upsert is False
        if self.before_replace is not None:
            self.before_replace(deepcopy(query), deepcopy(document))
        for index, current in enumerate(self.documents):
            if _matches(current, query):
                self.documents[index] = deepcopy(document)
                self.mutation_log.append(
                    {
                        "operation": "replace",
                        "store": self.store,
                        "collection": self.name,
                        "document_id": deepcopy(document.get("_id")),
                        "document": deepcopy(document),
                    }
                )
                return _WriteResult(matched_count=1)
        return _WriteResult()

    def delete_one(self, query):
        if self.before_delete is not None:
            self.before_delete(deepcopy(query))
        for index, current in enumerate(self.documents):
            if _matches(current, query):
                self.documents.pop(index)
                self.mutation_log.append(
                    {
                        "operation": "delete",
                        "store": self.store,
                        "collection": self.name,
                        "document_id": deepcopy(current.get("_id")),
                        "document": deepcopy(current),
                    }
                )
                return _WriteResult(deleted_count=1)
        return _WriteResult()

    def update_one(self, query, update):
        """Compatibility only; using this would violate the exact-CAS contract."""
        for index, current in enumerate(self.documents):
            if not _matches(current, query):
                continue
            updated = deepcopy(current)
            for key, value in (update.get("$set") or {}).items():
                updated[key] = deepcopy(value)
            for key, value in (update.get("$push") or {}).items():
                updated.setdefault(key, []).append(deepcopy(value))
            self.documents[index] = updated
            self.mutation_log.append(
                {
                    "operation": "update",
                    "store": self.store,
                    "collection": self.name,
                    "document_id": deepcopy(updated.get("_id")),
                    "document": deepcopy(updated),
                }
            )
            return _WriteResult(matched_count=1)
        return _WriteResult()

    def create_index(self, *args, **kwargs):
        raise AssertionError("targeted repair must not create indexes")

    def create_indexes(self, *args, **kwargs):
        raise AssertionError("targeted repair must not create indexes")

    def find_one_and_update(self, *args, **kwargs):
        raise AssertionError("targeted repair must not use a database lease")

    def find_one_and_replace(self, *args, **kwargs):
        raise AssertionError("targeted repair must use exact CAS methods")

    def bulk_write(self, *args, **kwargs):
        raise AssertionError("targeted repair must use one exact CAS per approved id")

    def drop(self, *args, **kwargs):
        raise AssertionError("targeted repair must not drop collections")


class MemoryDatabase:
    def __init__(
        self,
        collections=None,
        *,
        strict=False,
        forbidden_names=None,
    ):
        self.strict = strict
        self.forbidden_names = set(forbidden_names or ())
        self.access_log = []
        self.mutation_log = []
        self.collections = {}
        for name, collection in dict(collections or {}).items():
            if not isinstance(collection, MemoryCollection):
                collection = MemoryCollection(collection)
            collection.name = name
            collection.database = self
            self.collections[name] = collection

    def __getitem__(self, name):
        self.access_log.append(("database", name, "get_collection"))
        if name in self.forbidden_names:
            raise AssertionError(f"forbidden repair collection accessed: {name}")
        if name not in self.collections:
            if self.strict:
                raise AssertionError(f"unexpected repair collection accessed: {name}")
            self.collections[name] = MemoryCollection(
                [],
                name=name,
                database=self,
            )
        return self.collections[name]

    def create_collection(self, *args, **kwargs):
        raise AssertionError("targeted repair must not create collections")

    def command(self, *args, **kwargs):
        raise AssertionError("targeted repair must not acquire a database lease")


def test_stage_is_zero_write_and_preserves_complete_bson_pre_and_post():
    document_id = ObjectId("64f000000000000000000001")
    before = _document(document_id, filled_quantity=48_700)
    before["bson_payload"] = {
        "decimal": Decimal128("14.7000"),
        "binary": Binary(b"\\x00\\x01", subtype=0x80),
        "int64": Int64(9_223_372_036_854_775_000),
        "nested_id": ObjectId("64f000000000000000000002"),
        "when": datetime(2026, 8, 4, 9, 31, 2, 123000, tzinfo=timezone.utc),
        "items": [{"qty": Int64(100), "price": Decimal128("15.1400")}],
    }
    after = deepcopy(before)
    after["filled_quantity"] = 38_700
    after["bson_payload"]["items"].append(
        {"qty": Int64(100), "price": Decimal128("16.0600")}
    )
    databases = _databases(order_documents={"om_broker_orders": [before]})

    manifest = stage_targeted_repair(
        plan=_plan(document_id=document_id, before=before, after=after),
        databases=databases,
        plan_file_sha256="a" * 64,
    )

    assert databases["order"].mutation_log == []
    assert manifest["changes"][0]["before_document"] == before
    assert manifest["changes"][0]["after_document"] == after
    assert len(manifest["plan_hash"]) == 64
    assert len(manifest["preimage_hash"]) == 64
    assert len(manifest["postimage_hash"]) == 64
    assert len(manifest["manifest_hash"]) == 64


def test_stage_rejects_stale_plan_preimage_without_writes():
    document_id = ObjectId("64f000000000000000000003")
    current = _document(document_id, filled_quantity=48_700)
    planned_before = _document(document_id, filled_quantity=38_700)
    databases = _databases(order_documents={"om_broker_orders": [current]})

    with pytest.raises(PreimageHashMismatch, match="current document"):
        stage_targeted_repair(
            plan=_plan(
                document_id=document_id,
                before=planned_before,
                after={**planned_before, "filled_quantity": 10_000},
            ),
            databases=databases,
            plan_file_sha256="b" * 64,
        )
    assert databases["order"].mutation_log == []


@pytest.mark.parametrize(
    ("store", "collection"),
    [
        ("order", "om_order_requests"),
        ("order", "om_order_events"),
        ("order", "om_execution_history_archive"),
        ("order", "position_review_evidence_archive"),
        ("business", "xt_orders"),
        ("business", "xt_trades"),
        ("business", "xt_positions"),
        ("business", "stock_orders"),
        ("business", "stock_fills"),
        ("business", "stock_fills_compat"),
    ],
)
def test_stage_rejects_mutation_of_every_read_only_evidence_collection(
    store,
    collection,
):
    document_id = ObjectId("64f000000000000000000004")
    before = _document(document_id)
    plan = _plan(document_id=document_id, before=before, after={**before, "volume": 1})
    plan["changes"][0]["store"] = store
    plan["changes"][0]["collection"] = collection
    databases = _databases(
        order_documents={collection: [before]} if store == "order" else None,
        business_documents={collection: [before]} if store == "business" else None,
    )

    with pytest.raises(TargetedRepairError, match="read-only evidence"):
        stage_targeted_repair(
            plan=plan,
            databases=databases,
            plan_file_sha256="c" * 64,
        )
    assert databases[store].mutation_log == []


@pytest.mark.parametrize(
    "mutate_scope",
    [
        lambda scope: scope.update(account_id="000000000000"),
        lambda scope: scope.update(symbols=["000001"]),
        lambda scope: scope.update(trading_days=[20260806]),
        lambda scope: scope.update(document_ids={}),
        lambda scope: scope["document_ids"]["order"].update(om_broker_orders=[]),
    ],
)
def test_scope_has_hard_account_symbol_day_and_approved_id_gates(mutate_scope):
    document_id = ObjectId("64f000000000000000000005")
    before = _document(document_id)
    plan = _plan(document_id=document_id, before=before, after={**before, "volume": 1})
    mutate_scope(plan["scope"])
    databases = _databases(order_documents={"om_broker_orders": [before]})

    with pytest.raises(
        (InvalidRepairPlan, TargetedRepairError),
        match="scope|approved|account|symbol|day",
    ):
        stage_targeted_repair(
            plan=plan,
            databases=databases,
            plan_file_sha256="d" * 64,
        )
    assert databases["order"].mutation_log == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "000000000000"),
        ("symbol", "000001"),
        ("trading_day", 20260806),
    ],
)
def test_scope_rejects_approved_collection_documents_outside_scope(field, value):
    document_id = ObjectId("64f000000000000000000006")
    before = _document(document_id)
    before[field] = value
    after = {**before, "volume": 1}
    databases = _databases(order_documents={"om_broker_orders": [before]})
    plan = _plan(document_id=document_id, before=before, after=after)

    with pytest.raises(
        (InvalidRepairPlan, TargetedRepairError),
        match="scope|approved|account|symbol|day|id",
    ):
        stage_targeted_repair(
            plan=plan,
            databases=databases,
            plan_file_sha256="e" * 64,
        )
    assert databases["order"].mutation_log == []


@pytest.mark.parametrize(
    "field",
    [
        "order_sysid",
        "broker_order_id",
        "broker_trade_id",
        "internal_order_id",
    ],
)
def test_scope_rejects_unapproved_business_identity(field):
    document_id = ObjectId("64f000000000000000000006")
    approved_before = _document(document_id)
    approved_after = {**approved_before, "volume": 1}
    plan = _plan(
        document_id=document_id,
        before=approved_before,
        after=approved_after,
    )
    actual_before = deepcopy(approved_before)
    actual_before[field] = "not-approved"
    plan["changes"][0]["before_document"] = deepcopy(actual_before)
    plan["changes"][0]["after_document"] = {**actual_before, "volume": 1}
    databases = _databases(order_documents={"om_broker_orders": [actual_before]})

    with pytest.raises(
        (InvalidRepairPlan, TargetedRepairError),
        match="scope|approved|identity|id",
    ):
        stage_targeted_repair(
            plan=plan,
            databases=databases,
            plan_file_sha256="e" * 64,
        )
    assert databases["order"].mutation_log == []


@pytest.mark.parametrize(
    ("field", "approved_key"),
    [
        ("order_sysid", "order_sysids"),
        ("broker_order_id", "broker_order_ids"),
        ("broker_trade_id", "broker_trade_ids"),
        ("internal_order_id", "internal_order_ids"),
    ],
)
def test_scope_rejects_identity_field_when_approved_list_is_empty(
    field,
    approved_key,
):
    document_id = ObjectId("64f000000000000000000007")
    before = _document(document_id)
    after = {**before, "volume": 1}
    plan = _plan(document_id=document_id, before=before, after=after)
    plan["scope"]["approved_ids"][approved_key] = []
    databases = _databases(order_documents={"om_broker_orders": [before]})

    with pytest.raises(InvalidRepairPlan, match=f"approved {field}"):
        stage_targeted_repair(
            plan=plan,
            databases=databases,
            plan_file_sha256="e" * 64,
        )
    assert databases["order"].mutation_log == []


@pytest.mark.parametrize(
    ("argument", "error_type"),
    [
        ("expected_plan_file_sha256", PlanFileHashMismatch),
        ("expected_plan_hash", ManifestHashMismatch),
        ("expected_preimage_hash", PreimageHashMismatch),
        ("expected_manifest_hash", ManifestHashMismatch),
    ],
)
def test_execute_has_four_independent_hash_gates(tmp_path, argument, error_type):
    document_id = ObjectId("64f000000000000000000007")
    before = _document(document_id)
    after = {**before, "volume": 1}
    databases = _databases(order_documents={"om_broker_orders": [before]})
    plan_sha = "f" * 64
    plan = _plan(document_id=document_id, before=before, after=after)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256=plan_sha,
    )
    kwargs = _execute_kwargs(plan, manifest, databases, tmp_path / "backup")
    kwargs[argument] = "0" * 64

    with pytest.raises(error_type):
        execute_targeted_repair(**kwargs)
    assert databases["order"].mutation_log == []
    assert not (tmp_path / "backup" / "backup-receipt.json").exists()


def test_first_apply_requires_every_change_to_be_preimage_and_blocks_mixed_state(
    tmp_path,
):
    first_id = ObjectId("64f000000000000000000008")
    second_id = ObjectId("64f000000000000000000009")
    first_before = _document(first_id, internal_order_id="ord-first")
    first_after = {**first_before, "volume": 1}
    second_before = _document(second_id, internal_order_id="ord-second")
    second_after = {**second_before, "volume": 2}
    plan = _multi_change_plan(
        [
            ("first", "om_broker_orders", first_id, first_before, first_after),
            ("second", "om_execution_fills", second_id, second_before, second_after),
        ]
    )
    databases = _databases(
        order_documents={
            "om_broker_orders": [first_before],
            "om_execution_fills": [second_before],
        }
    )
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="1" * 64,
    )
    databases["order"]["om_execution_fills"].documents[0] = deepcopy(second_after)

    with pytest.raises(TargetedRepairError, match="preimage|mixed|first apply"):
        execute_targeted_repair(
            **_execute_kwargs(plan, manifest, databases, tmp_path / "backup")
        )
    assert databases["order"].mutation_log == []
    assert not (tmp_path / "backup" / "backup-receipt.json").exists()


def test_backup_bundle_is_complete_and_read_back_before_first_database_write(tmp_path):
    document_id = ObjectId("64f00000000000000000000a")
    before = _document(document_id)
    after = {**before, "volume": 1, "new_field": Decimal128("0.125")}
    databases = _databases(order_documents={"om_broker_orders": [before]})
    plan = _plan(document_id=document_id, before=before, after=after)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="2" * 64,
    )
    backup_dir = tmp_path / "backup"
    observed = {"called": False}

    def assert_backup_before_replace(_query, _document):
        observed["called"] = True
        expected_files = {
            "manifest.json",
            "preimage.json",
            "postimage.json",
            "backup-receipt.json",
        }
        assert expected_files.issubset({item.name for item in backup_dir.iterdir()})
        receipt = load_repair_document(backup_dir / "backup-receipt.json")
        assert receipt["repair_id"] == manifest["repair_id"]
        for filename, expected_hash in receipt["files"].items():
            assert sha256_file(backup_dir / filename) == expected_hash
        assert _bson_equal(
            load_repair_document(backup_dir / "preimage.json")["documents"][0][
                "document"
            ],
            before,
        )
        assert _bson_equal(
            load_repair_document(backup_dir / "postimage.json")["documents"][0][
                "document"
            ],
            after,
        )

    databases["order"]["om_broker_orders"].before_replace = assert_backup_before_replace
    result = execute_targeted_repair(
        **_execute_kwargs(plan, manifest, databases, backup_dir)
    )

    assert observed["called"] is True
    assert result["status"] == "applied"
    assert databases["order"]["om_broker_orders"].documents == [after]


def test_already_applied_requires_a_valid_backup_bundle(tmp_path):
    document_id = ObjectId("64f00000000000000000000b")
    before = _document(document_id)
    after = {**before, "volume": 1}
    plan = _plan(document_id=document_id, before=before, after=after)
    databases = _databases(order_documents={"om_broker_orders": [before]})
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="3" * 64,
    )
    backup_dir = tmp_path / "backup"
    execute_targeted_repair(**_execute_kwargs(plan, manifest, databases, backup_dir))

    assert (
        execute_targeted_repair(
            **_execute_kwargs(plan, manifest, databases, backup_dir)
        )["status"]
        == "already_applied"
    )

    (backup_dir / "backup-receipt.json").unlink()
    with pytest.raises(TargetedRepairError, match="backup"):
        execute_targeted_repair(
            **_execute_kwargs(plan, manifest, databases, backup_dir)
        )


def test_apply_uses_no_database_journal_index_or_lease(tmp_path):
    document_id = ObjectId("64f00000000000000000000c")
    before = _document(document_id)
    after = {**before, "volume": 1}
    databases = _databases(
        order_documents={"om_broker_orders": [before]},
        strict=True,
        forbidden_names={
            "om_targeted_repair_runs",
            "targeted_repair_runs",
            "repair_leases",
            "om_repair_leases",
        },
    )
    plan = _plan(document_id=document_id, before=before, after=after)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="4" * 64,
    )

    result = execute_targeted_repair(
        **_execute_kwargs(plan, manifest, databases, tmp_path / "backup")
    )

    assert result["status"] == "applied"
    assert all(
        name not in databases["order"].collections
        for name in databases["order"].forbidden_names
    )
    assert all(
        event["operation"] in {"replace", "insert", "delete"}
        for event in databases["order"].mutation_log
    )


def test_later_cas_failure_compensates_written_items_in_reverse_order(tmp_path):
    first_id = ObjectId("64f00000000000000000000d")
    second_id = ObjectId("64f00000000000000000000e")
    third_id = ObjectId("64f00000000000000000000f")
    first_before = _document(first_id, internal_order_id="ord-first")
    first_after = {**first_before, "volume": 1}
    second_before = _document(second_id, internal_order_id="ord-second")
    second_after = {**second_before, "volume": 2}
    third_before = _document(third_id, internal_order_id="ord-third")
    third_after = {**third_before, "volume": 3}
    plan = _multi_change_plan(
        [
            ("first", "om_broker_orders", first_id, first_before, first_after),
            ("second", "om_execution_fills", second_id, second_before, second_after),
            ("third", "om_trade_facts", third_id, third_before, third_after),
        ]
    )
    databases = _databases(
        order_documents={
            "om_broker_orders": [first_before],
            "om_execution_fills": [second_before],
            "om_trade_facts": [third_before],
        }
    )

    def race_third(_query, _document):
        collection = databases["order"]["om_trade_facts"]
        collection.before_replace = None
        collection.documents[0]["concurrent_marker"] = "preserve"

    databases["order"]["om_trade_facts"].before_replace = race_third
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="5" * 64,
    )

    with pytest.raises(TargetedRepairError):
        execute_targeted_repair(
            **_execute_kwargs(plan, manifest, databases, tmp_path / "backup")
        )

    replacements = [
        event
        for event in databases["order"].mutation_log
        if event["operation"] == "replace"
    ]
    assert [event["document_id"] for event in replacements] == [
        first_id,
        second_id,
        second_id,
        first_id,
    ]
    assert databases["order"]["om_broker_orders"].documents == [first_before]
    assert databases["order"]["om_execution_fills"].documents == [second_before]
    assert (
        databases["order"]["om_trade_facts"].documents[0]["concurrent_marker"]
        == "preserve"
    )


def test_compensation_failure_is_reported_as_partial_state(tmp_path):
    first_id = ObjectId("64f000000000000000000010")
    second_id = ObjectId("64f000000000000000000011")
    first_before = _document(first_id, internal_order_id="ord-first")
    first_after = {**first_before, "volume": 1}
    second_before = _document(second_id, internal_order_id="ord-second")
    second_after = {**second_before, "volume": 2}
    plan = _multi_change_plan(
        [
            ("first", "om_broker_orders", first_id, first_before, first_after),
            ("second", "om_execution_fills", second_id, second_before, second_after),
        ]
    )
    databases = _databases(
        order_documents={
            "om_broker_orders": [first_before],
            "om_execution_fills": [second_before],
        }
    )

    def race_and_break_compensation(_query, document):
        if document == first_after:
            collection = databases["order"]["om_execution_fills"]
            collection.documents[0]["concurrent_marker"] = "second-race"
        elif document == first_before:
            collection = databases["order"]["om_broker_orders"]
            collection.documents[0]["concurrent_marker"] = "rollback-race"

    databases["order"]["om_broker_orders"].before_replace = race_and_break_compensation
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="6" * 64,
    )

    with pytest.raises(RepairRollbackIncomplete, match="compensation"):
        execute_targeted_repair(
            **_execute_kwargs(plan, manifest, databases, tmp_path / "backup")
        )
    assert (
        databases["order"]["om_broker_orders"].documents[0]["concurrent_marker"]
        == "rollback-race"
    )
    assert (
        databases["order"]["om_execution_fills"].documents[0]["concurrent_marker"]
        == "second-race"
    )


def test_restore_requires_valid_backup_and_restores_exact_bson_state(tmp_path):
    document_id = ObjectId("64f000000000000000000012")
    before = _document(document_id, filled_quantity=48_700)
    before["bson_payload"] = {
        "decimal": Decimal128("14.7000"),
        "binary": Binary(b"\\x02\\x03", subtype=0x80),
        "when": datetime(2026, 8, 5, 10, 2, 3, tzinfo=timezone.utc),
    }
    after = deepcopy(before)
    after["filled_quantity"] = 38_700
    after["new_field"] = {"nested": [Int64(1), Decimal128("0.1250")]}
    databases = _databases(order_documents={"om_broker_orders": [before]})
    plan = _plan(document_id=document_id, before=before, after=after)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="7" * 64,
    )
    backup_dir = tmp_path / "backup"
    execute_targeted_repair(**_execute_kwargs(plan, manifest, databases, backup_dir))
    preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
        backup_dir=backup_dir,
    )

    restored = restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_manifest_hash=manifest["manifest_hash"],
        expected_current_hash=preview["current_hash"],
        backup_dir=backup_dir,
    )

    assert restored["status"] == "restored"
    assert databases["order"]["om_broker_orders"].documents == [before]


def test_restore_refuses_missing_or_tampered_backup_and_no_backup_dir(tmp_path):
    document_id = ObjectId("64f000000000000000000013")
    before = _document(document_id)
    after = {**before, "volume": 1}
    databases = _databases(order_documents={"om_broker_orders": [before]})
    plan = _plan(document_id=document_id, before=before, after=after)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="8" * 64,
    )
    backup_dir = tmp_path / "backup"
    execute_targeted_repair(**_execute_kwargs(plan, manifest, databases, backup_dir))
    preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
        backup_dir=backup_dir,
    )

    (backup_dir / "preimage.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(TargetedRepairError, match="backup"):
        restore_targeted_repair(
            manifest=manifest,
            databases=databases,
            expected_manifest_hash=manifest["manifest_hash"],
            expected_current_hash=preview["current_hash"],
            backup_dir=backup_dir,
        )

    with pytest.raises(TypeError):
        restore_targeted_repair(
            manifest=manifest,
            databases=databases,
            expected_manifest_hash=manifest["manifest_hash"],
            expected_current_hash=preview["current_hash"],
            backup_dir=None,
        )


def test_apply_and_restore_support_exact_insert_delete_and_replace_states(tmp_path):
    replace_id = ObjectId("64f000000000000000000014")
    delete_id = ObjectId("64f000000000000000000015")
    insert_id = ObjectId("64f000000000000000000016")
    replace_before = _document(replace_id, internal_order_id="ord-replace")
    replace_after = {**replace_before, "volume": 1}
    delete_before = _document(delete_id, internal_order_id="ord-delete")
    insert_after = _document(insert_id, internal_order_id="ord-insert")
    insert_after["volume"] = 2
    plan = _multi_change_plan(
        [
            ("replace", "om_broker_orders", replace_id, replace_before, replace_after),
            ("delete", "om_execution_fills", delete_id, delete_before, None),
            ("insert", "om_trade_facts", insert_id, None, insert_after),
        ]
    )
    databases = _databases(
        order_documents={
            "om_broker_orders": [replace_before],
            "om_execution_fills": [delete_before],
            "om_trade_facts": [],
        }
    )
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="9" * 64,
    )
    backup_dir = tmp_path / "backup"
    execute_targeted_repair(**_execute_kwargs(plan, manifest, databases, backup_dir))
    assert databases["order"]["om_broker_orders"].documents == [replace_after]
    assert databases["order"]["om_execution_fills"].documents == []
    assert databases["order"]["om_trade_facts"].documents == [insert_after]

    preview = preview_targeted_restore(
        manifest=manifest,
        databases=databases,
        backup_dir=backup_dir,
    )
    restore_targeted_repair(
        manifest=manifest,
        databases=databases,
        expected_manifest_hash=manifest["manifest_hash"],
        expected_current_hash=preview["current_hash"],
        backup_dir=backup_dir,
    )
    assert databases["order"]["om_broker_orders"].documents == [replace_before]
    assert databases["order"]["om_execution_fills"].documents == [delete_before]
    assert databases["order"]["om_trade_facts"].documents == []


def _databases(
    *,
    order_documents=None,
    business_documents=None,
    strict=False,
    forbidden_names=None,
):
    order = MemoryDatabase(
        {
            name: MemoryCollection(rows, name=name, store="order")
            for name, rows in dict(order_documents or {}).items()
        },
        strict=strict,
        forbidden_names=forbidden_names,
    )
    business = MemoryDatabase(
        {
            name: MemoryCollection(rows, name=name, store="business")
            for name, rows in dict(business_documents or {}).items()
        },
        strict=strict,
        forbidden_names=forbidden_names,
    )
    return {"order": order, "business": business}


def _document(
    document_id,
    *,
    account_id=ACCOUNT_ID,
    symbol="688772",
    trading_day=20260804,
    order_sysid="557",
    broker_order_id="1209008130",
    broker_trade_id="0000000012941469",
    internal_order_id="ord_broker_fixture",
    filled_quantity=10_000,
):
    return {
        "_id": document_id,
        "account_id": account_id,
        "symbol": symbol,
        "trading_day": trading_day,
        "order_sysid": order_sysid,
        "broker_order_id": broker_order_id,
        "broker_trade_id": broker_trade_id,
        "internal_order_id": internal_order_id,
        "filled_quantity": filled_quantity,
        "volume": filled_quantity,
        "updated_at": datetime(2026, 8, 4, tzinfo=timezone.utc),
    }


def _plan(*, document_id, before, after):
    return _multi_change_plan(
        [("broker-order", "om_broker_orders", document_id, before, after)]
    )


def _multi_change_plan(changes, *, scope=None):
    normalized_changes = [
        {
            "change_id": change_id,
            "store": "order",
            "collection": collection,
            "document_id": document_id,
            "before_document": deepcopy(before),
            "after_document": deepcopy(after),
        }
        for change_id, collection, document_id, before, after in changes
    ]
    if scope is None:
        scope = _scope_for_changes(normalized_changes)
    return {
        "schema_version": 1,
        "repair_id": REPAIR_ID,
        "target_main_sha": TARGET_MAIN_SHA,
        "reason": "repair 688772 external order identity contamination",
        "scope": deepcopy(scope),
        "changes": normalized_changes,
    }


def _scope_for_changes(changes):
    documents = [
        document
        for change in changes
        for document in (change["before_document"], change["after_document"])
        if document is not None
    ]
    return {
        "account_id": ACCOUNT_ID,
        "symbols": list(SYMBOLS),
        "trading_days": list(TRADING_DAYS),
        "document_ids": _approved_document_ids(changes),
        "approved_ids": {
            "order_sysids": _unique_values(
                document.get("order_sysid") for document in documents
            ),
            "broker_order_ids": _unique_values(
                document.get("broker_order_id") for document in documents
            ),
            "broker_trade_ids": _unique_values(
                document.get("broker_trade_id") for document in documents
            ),
            "internal_order_ids": _unique_values(
                document.get("internal_order_id") for document in documents
            ),
        },
    }


def _unique_values(values):
    result = []
    for value in values:
        if value in (None, "") or value in result:
            continue
        result.append(deepcopy(value))
    return result


def _approved_document_ids(changes):
    approved = {}
    for change in changes:
        approved.setdefault(change["store"], {}).setdefault(
            change["collection"], []
        ).append(deepcopy(change["document_id"]))
    return approved


def _execute_kwargs(plan, manifest, databases, backup_dir):
    return {
        "plan": plan,
        "manifest": manifest,
        "databases": databases,
        "expected_plan_file_sha256": manifest["plan_file_sha256"],
        "expected_plan_hash": manifest["plan_hash"],
        "expected_preimage_hash": manifest["preimage_hash"],
        "expected_manifest_hash": manifest["manifest_hash"],
        "deployed_main_sha": TARGET_MAIN_SHA,
        "backup_dir": backup_dir,
    }


def _bson_equal(left, right):
    options = json_util.CANONICAL_JSON_OPTIONS
    return json_util.dumps(
        left,
        json_options=options,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) == json_util.dumps(
        right,
        json_options=options,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _matches(document, query):
    if not query:
        return True
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
            operands = expected.get("$eq")
            if not operands or len(operands) != 2:
                return False
            left, right = operands
            left = document if left == "$$ROOT" else _get_path(document, left)
            if isinstance(right, dict) and set(right) == {"$literal"}:
                right = right["$literal"]
            if left != right:
                return False
            continue
        actual = _get_path(document, key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _get_path(document, path):
    if not isinstance(path, str) or not path.startswith("$"):
        return document.get(path) if isinstance(document, dict) else None
    current = document
    for part in path[1:].split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
