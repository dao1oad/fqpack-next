from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from bson import Binary, Decimal128, Int64, ObjectId, json_util
from pymongo import MongoClient

from freshquant.order_management.repair import targeted_ledger as repair_module
from freshquant.order_management.repair.targeted_ledger import (
    TargetedRepairError,
    execute_targeted_repair,
    load_repair_document,
    persist_repair_document,
    preview_targeted_restore,
    restore_targeted_repair,
    sha256_file,
    stage_targeted_repair,
)

TARGET_MAIN_SHA = "2e8754590c1b108637eaf2370ec99f5b1257810f"
ACCOUNT_ID = "068000087558"
SYMBOLS = ["600917", "688772"]
TRADING_DAYS = [20260528, 20260804, 20260805]

_RUN_REAL_MONGO = os.getenv("FQ_FIX_504_REAL_MONGO") == "1"
_REAL_MONGO_URI = "mongodb://127.0.0.1:27027"
_TEST_DATABASE_PREFIX = "fq_test_fix_504_repair_"

pytestmark = pytest.mark.skipif(
    not _RUN_REAL_MONGO,
    reason="set FQ_FIX_504_REAL_MONGO=1 to run FIX-504 repair real Mongo tests",
)


@pytest.fixture
def real_mongo_database():
    client = MongoClient(
        _REAL_MONGO_URI,
        connectTimeoutMS=5_000,
        serverSelectionTimeoutMS=5_000,
        tz_aware=True,
    )
    database_name = f"{_TEST_DATABASE_PREFIX}{uuid4().hex}"
    assert database_name.startswith(_TEST_DATABASE_PREFIX)
    try:
        client.admin.command("ping")
        yield client[database_name]
    finally:
        if database_name.startswith(_TEST_DATABASE_PREFIX):
            client.drop_database(database_name)
        client.close()


class _DatabaseProxy:
    def __init__(self, database, collection_factory):
        self._database = database
        self._collection_factory = collection_factory

    def __getitem__(self, name):
        return self._collection_factory(name, self._database[name])


class _CollectionProxy:
    def __init__(self, collection):
        self._collection = collection

    def __getattr__(self, name):
        return getattr(self._collection, name)


class _NthReplaceRace:
    def __init__(self, *, trigger_at, competing_database):
        self.trigger_at = trigger_at
        self.competing_database = competing_database
        self.attempts = []

    def wrap(self, name, collection):
        return _RaceCollection(collection, name=name, state=self)


class _RaceCollection(_CollectionProxy):
    def __init__(self, collection, *, name, state):
        super().__init__(collection)
        self._name = name
        self._state = state

    def replace_one(self, query, document, *args, **kwargs):
        self._state.attempts.append(
            {
                "collection": self._name,
                "document_id": deepcopy(document["_id"]),
                "repair_value": document.get("repair_value"),
            }
        )
        if len(self._state.attempts) == self._state.trigger_at:
            result = self._state.competing_database[self._name].update_one(
                {"_id": deepcopy(document["_id"])},
                {"$set": {"concurrent_marker": "preserve-third-writer"}},
            )
            assert result.matched_count == 1
        return self._collection.replace_one(query, document, *args, **kwargs)


class _FirstWriteProbe:
    def __init__(self, callback):
        self.callback = callback
        self.write_count = 0

    def wrap(self, _name, collection):
        return _FirstWriteCollection(collection, probe=self)

    def before_write(self):
        self.write_count += 1
        if self.write_count == 1:
            self.callback()


class _FirstWriteCollection(_CollectionProxy):
    def __init__(self, collection, *, probe):
        super().__init__(collection)
        self._probe = probe

    def insert_one(self, *args, **kwargs):
        self._probe.before_write()
        return self._collection.insert_one(*args, **kwargs)

    def replace_one(self, *args, **kwargs):
        self._probe.before_write()
        return self._collection.replace_one(*args, **kwargs)

    def delete_one(self, *args, **kwargs):
        self._probe.before_write()
        return self._collection.delete_one(*args, **kwargs)


def test_real_mongo_manifest_round_trip_apply_and_restore_preserve_bson_order(
    real_mongo_database,
    tmp_path,
):
    collection = real_mongo_database["om_broker_orders"]
    document_id = ObjectId()
    inserted = _document(document_id, internal_order_id="ord-real-round-trip")
    inserted["ordered_payload"] = {
        "decimal": Decimal128("14.7000"),
        "binary": Binary(b"\x00\x01", subtype=0x80),
        "int64": Int64(9_223_372_036_854_775_000),
        "when": datetime(2026, 8, 4, 9, 31, 2, 123000, tzinfo=timezone.utc),
        "items": [
            {"quantity": Int64(3_400), "price": Decimal128("14.7000")},
            {"quantity": Int64(3_300), "price": Decimal128("15.1400")},
        ],
    }
    collection.insert_one(inserted)
    before = collection.find_one({"_id": document_id})
    after = deepcopy(before)
    after["filled_quantity"] = 38_700
    after["repair_value"] = 1
    after["ordered_payload"]["items"].append(
        {"quantity": Int64(100), "price": Decimal128("16.0600")}
    )
    plan = _plan([("round-trip", "om_broker_orders", before, after)])
    plan_path = persist_repair_document(plan, tmp_path / "plan.json")
    loaded_plan = load_repair_document(plan_path)
    databases = _databases(real_mongo_database)

    manifest = stage_targeted_repair(
        plan=loaded_plan,
        databases=databases,
        plan_file_sha256=sha256_file(plan_path),
    )
    manifest_path = persist_repair_document(
        manifest,
        tmp_path / "manifest.json",
    )
    loaded_manifest = load_repair_document(manifest_path)

    staged_before = loaded_manifest["changes"][0]["before_document"]
    staged_after = loaded_manifest["changes"][0]["after_document"]
    assert list(staged_before) == list(before)
    assert list(staged_before["ordered_payload"]) == list(before["ordered_payload"])
    assert list(staged_after) == list(after)
    assert list(staged_after["ordered_payload"]) == list(after["ordered_payload"])

    backup_dir = tmp_path / "backup"
    applied = execute_targeted_repair(
        **_execute_kwargs(
            loaded_plan,
            loaded_manifest,
            databases,
            backup_dir,
        )
    )

    assert applied["status"] == "applied"
    saved_after = collection.find_one({"_id": document_id})
    assert _bson_equal(saved_after, staged_after)
    assert list(saved_after) == list(staged_after)
    assert list(saved_after["ordered_payload"]) == list(staged_after["ordered_payload"])

    preview = preview_targeted_restore(
        manifest=loaded_manifest,
        databases=databases,
        backup_dir=backup_dir,
    )
    restored = restore_targeted_repair(
        manifest=loaded_manifest,
        databases=databases,
        expected_manifest_hash=loaded_manifest["manifest_hash"],
        expected_current_hash=preview["current_hash"],
        backup_dir=backup_dir,
    )

    assert restored["status"] == "restored"
    saved_before = collection.find_one({"_id": document_id})
    assert _bson_equal(saved_before, staged_before)
    assert list(saved_before) == list(staged_before)
    assert list(saved_before["ordered_payload"]) == list(
        staged_before["ordered_payload"]
    )


def test_real_mongo_exact_document_cas_rejects_only_field_order_drift(
    real_mongo_database,
    tmp_path,
):
    collection = real_mongo_database["om_execution_fills"]
    document_id = ObjectId()
    collection.insert_one(
        _document(document_id, internal_order_id="ord-real-order-drift")
    )
    before = collection.find_one({"_id": document_id})
    after = deepcopy(before)
    after["repair_value"] = 1
    plan = _plan([("order-drift", "om_execution_fills", before, after)])
    databases = _databases(real_mongo_database)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=databases,
        plan_file_sha256="a" * 64,
    )
    manifest_path = persist_repair_document(manifest, tmp_path / "manifest.json")
    loaded_manifest = load_repair_document(manifest_path)

    reordered = {"_id": before["_id"]}
    reordered.update(
        (key, deepcopy(value)) for key, value in reversed(list(before.items())[1:])
    )
    result = collection.replace_one({"_id": document_id}, reordered)
    assert result.matched_count == 1
    assert collection.find_one({"_id": document_id}) == before
    assert list(collection.find_one({"_id": document_id})) == list(reordered)

    with pytest.raises(TargetedRepairError, match="restored to its approved preimage"):
        execute_targeted_repair(
            **_execute_kwargs(
                plan,
                loaded_manifest,
                databases,
                tmp_path / "backup",
            )
        )

    current = collection.find_one({"_id": document_id})
    assert current == before
    assert list(current) == list(reordered)
    assert "repair_value" not in current


def test_real_mongo_nth_cas_race_compensates_prior_writes_in_reverse_order(
    real_mongo_database,
    tmp_path,
):
    specifications = [
        ("first", "om_broker_orders", "ord-real-first"),
        ("second", "om_execution_fills", "ord-real-second"),
        ("third", "om_trade_facts", "ord-real-third"),
    ]
    changes = []
    for index, (change_id, collection_name, internal_order_id) in enumerate(
        specifications,
        start=1,
    ):
        collection = real_mongo_database[collection_name]
        document_id = ObjectId()
        inserted = _document(
            document_id,
            internal_order_id=internal_order_id,
            order_sysid=str(556 + index),
            broker_order_id=str(1_209_008_130 + index),
            broker_trade_id=f"00000000129414{68 + index:02d}",
        )
        inserted["repair_value"] = 0
        collection.insert_one(inserted)
        before = collection.find_one({"_id": document_id})
        after = deepcopy(before)
        after["repair_value"] = index
        changes.append((change_id, collection_name, before, after))

    plan = _plan(changes)
    plain_databases = _databases(real_mongo_database)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=plain_databases,
        plan_file_sha256="b" * 64,
    )

    competing_client = MongoClient(
        _REAL_MONGO_URI,
        connectTimeoutMS=5_000,
        serverSelectionTimeoutMS=5_000,
        tz_aware=True,
    )
    try:
        competing_database = competing_client[real_mongo_database.name]
        race = _NthReplaceRace(
            trigger_at=3,
            competing_database=competing_database,
        )
        raced_databases = {
            "order": _DatabaseProxy(real_mongo_database, race.wrap),
            "business": real_mongo_database,
        }

        with pytest.raises(
            TargetedRepairError,
            match="restored to its approved preimage",
        ):
            execute_targeted_repair(
                **_execute_kwargs(
                    plan,
                    manifest,
                    raced_databases,
                    tmp_path / "backup",
                )
            )
    finally:
        competing_client.close()

    assert [attempt["collection"] for attempt in race.attempts] == [
        "om_broker_orders",
        "om_execution_fills",
        "om_trade_facts",
        "om_execution_fills",
        "om_broker_orders",
    ]
    assert [attempt["repair_value"] for attempt in race.attempts] == [
        1,
        2,
        3,
        0,
        0,
    ]
    for change_id, collection_name, before, _after in changes[:2]:
        assert change_id
        assert (
            real_mongo_database[collection_name].find_one({"_id": before["_id"]})
            == before
        )
    third_before = changes[2][2]
    third_current = real_mongo_database["om_trade_facts"].find_one(
        {"_id": third_before["_id"]}
    )
    assert third_current["repair_value"] == 0
    assert third_current["concurrent_marker"] == "preserve-third-writer"


def test_real_mongo_backup_bundle_is_read_back_before_first_write(
    real_mongo_database,
    tmp_path,
    monkeypatch,
):
    collection = real_mongo_database["om_broker_orders"]
    document_id = ObjectId()
    collection.insert_one(
        _document(document_id, internal_order_id="ord-real-backup-probe")
    )
    before = collection.find_one({"_id": document_id})
    after = deepcopy(before)
    after["repair_value"] = 1
    plan = _plan([("backup-probe", "om_broker_orders", before, after)])
    plain_databases = _databases(real_mongo_database)
    manifest = stage_targeted_repair(
        plan=plan,
        databases=plain_databases,
        plan_file_sha256="c" * 64,
    )
    backup_dir = tmp_path / "backup"
    original_load = repair_module.load_repair_document
    read_paths = []

    def recording_load(path):
        read_paths.append(Path(path).resolve())
        return original_load(path)

    monkeypatch.setattr(repair_module, "load_repair_document", recording_load)

    def assert_backup_is_verified():
        required = {
            "manifest.json",
            "preimage.json",
            "postimage.json",
            "backup-receipt.json",
        }
        names_at_first_write = {path.name for path in backup_dir.iterdir()}
        assert required.issubset(names_at_first_write)
        assert names_at_first_write - required == {".apply.lock"}
        resolved = {name: (backup_dir / name).resolve() for name in required}
        assert read_paths.count(resolved["backup-receipt.json"]) >= 2
        assert resolved["manifest.json"] in read_paths
        assert resolved["preimage.json"] in read_paths
        assert resolved["postimage.json"] in read_paths

        receipt = original_load(resolved["backup-receipt.json"])
        assert receipt["manifest_hash"] == manifest["manifest_hash"]
        for filename, expected_hash in receipt["files"].items():
            assert sha256_file(backup_dir / filename) == expected_hash

    probe = _FirstWriteProbe(assert_backup_is_verified)
    probed_databases = {
        "order": _DatabaseProxy(real_mongo_database, probe.wrap),
        "business": real_mongo_database,
    }

    result = execute_targeted_repair(
        **_execute_kwargs(
            plan,
            manifest,
            probed_databases,
            backup_dir,
        )
    )

    assert result["status"] == "applied"
    assert probe.write_count == 1
    assert collection.find_one({"_id": document_id}) == after


def _databases(database):
    return {"order": database, "business": database}


def _document(
    document_id,
    *,
    internal_order_id,
    order_sysid="557",
    broker_order_id="1209008130",
    broker_trade_id="0000000012941469",
):
    return {
        "_id": document_id,
        "account_id": ACCOUNT_ID,
        "symbol": "688772",
        "trading_day": 20260804,
        "order_sysid": order_sysid,
        "broker_order_id": broker_order_id,
        "broker_trade_id": broker_trade_id,
        "internal_order_id": internal_order_id,
        "filled_quantity": 10_000,
        "volume": 10_000,
        "updated_at": datetime(2026, 8, 4, tzinfo=timezone.utc),
    }


def _plan(changes):
    normalized_changes = [
        {
            "change_id": change_id,
            "store": "order",
            "collection": collection,
            "document_id": deepcopy((before or after)["_id"]),
            "before_document": deepcopy(before),
            "after_document": deepcopy(after),
        }
        for change_id, collection, before, after in changes
    ]
    documents = [
        document
        for change in normalized_changes
        for document in (change["before_document"], change["after_document"])
        if document is not None
    ]
    document_ids = {}
    for change in normalized_changes:
        document_ids.setdefault(change["store"], {}).setdefault(
            change["collection"], []
        ).append(deepcopy(change["document_id"]))
    return {
        "schema_version": 1,
        "repair_id": f"fix-504-real-mongo-{uuid4().hex}",
        "target_main_sha": TARGET_MAIN_SHA,
        "reason": "test isolated FIX-504 targeted ledger repair",
        "scope": {
            "account_id": ACCOUNT_ID,
            "symbols": list(SYMBOLS),
            "trading_days": list(TRADING_DAYS),
            "document_ids": document_ids,
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
        },
        "changes": normalized_changes,
    }


def _unique_values(values):
    result = []
    for value in values:
        if value in (None, "") or value in result:
            continue
        result.append(str(value))
    return result


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
