from __future__ import annotations

from copy import deepcopy

import pytest

from freshquant.order_management.repair.targeted_ledger import (
    TargetedRepairError,
    stage_targeted_repair,
    verify_targeted_repair,
)


class ReadOnlyCollection:
    def __init__(self, documents=None):
        self.documents = {item["_id"]: deepcopy(item) for item in list(documents or [])}
        self.find_one_queries = []
        self.find_queries = []

    def find_one(self, query):
        assert set(query) == {"_id"}
        self.find_one_queries.append(deepcopy(query))
        return deepcopy(self.documents.get(query["_id"]))

    def find(self, query):
        self.find_queries.append(deepcopy(query))
        return [
            deepcopy(document)
            for document in self.documents.values()
            if self._matches(document, query)
        ]

    @staticmethod
    def _matches(document, query):
        for field, expected in query.items():
            actual = document.get(field)
            if isinstance(expected, dict) and set(expected) == {"$in"}:
                if actual not in expected["$in"]:
                    return False
            elif actual != expected:
                return False
        return True

    def insert_one(self, _document):
        raise AssertionError("verifier must not insert")

    def replace_one(self, _query, _document, upsert=False):
        raise AssertionError("verifier must not replace")

    def delete_one(self, _query):
        raise AssertionError("verifier must not delete")


class ReadOnlyDatabase:
    def __init__(self, collections=None):
        self.collections = dict(collections or {})

    def __getitem__(self, name):
        return self.collections.setdefault(name, ReadOnlyCollection())


def test_verify_fixed_fix_504_postconditions_are_read_only():
    manifest, databases = _manifest_and_postimage_databases()

    result = verify_targeted_repair(manifest=manifest, databases=databases)

    assert result["pass"] is True
    assert result["status"] == "verified"
    assert {item["name"] for item in result["checks"]} == {
        "manifest_postimage",
        "orders_fixed_live_scope",
        "broker_order_600917",
        "executions_600917",
        "broker_order_688772_buy",
        "broker_order_688772_sell",
        "executions_688772",
        "position_entry_688772",
        "entry_slices_688772",
        "v2_allocations_688772",
        "reconciliation_gaps_removed",
        "reconciliation_resolutions_removed",
        "odd_lot_rejections_removed",
        "immutable_evidence_unchanged",
    }
    assert sum(
        len(collection.find_one_queries)
        for database in databases.values()
        for collection in database.collections.values()
    ) == len(manifest["changes"])


def test_verify_fails_closed_when_688772_buy_owner_is_wrong():
    manifest, databases = _manifest_and_postimage_databases()
    databases["order"]["om_broker_orders"].documents["broker-688772-buy"][
        "internal_order_id"
    ] = "ord_wrong"

    with pytest.raises(
        TargetedRepairError,
        match="broker_order_688772_buy",
    ):
        verify_targeted_repair(manifest=manifest, databases=databases)


def test_verify_fails_closed_when_688772_sell_broker_order_is_absent():
    manifest, databases = _manifest_and_postimage_databases()
    del databases["order"]["om_broker_orders"].documents["broker-688772-sell"]

    with pytest.raises(TargetedRepairError, match="broker_order_688772_sell"):
        verify_targeted_repair(manifest=manifest, databases=databases)


def test_verify_fails_closed_when_688772_sell_owner_is_wrong():
    manifest, databases = _manifest_and_postimage_databases()
    databases["order"]["om_broker_orders"].documents["broker-688772-sell"][
        "internal_order_id"
    ] = "ord_wrong"

    with pytest.raises(TargetedRepairError, match="broker_order_688772_sell"):
        verify_targeted_repair(manifest=manifest, databases=databases)


def test_verify_fails_closed_when_read_only_evidence_changes():
    manifest, databases = _manifest_and_postimage_databases()
    databases["business"]["xt_trades"].documents["readonly-xt_trades"]["volume"] = 1

    with pytest.raises(
        TargetedRepairError,
        match="immutable_evidence_unchanged",
    ):
        verify_targeted_repair(manifest=manifest, databases=databases)


def test_verify_detects_unplanned_fill_in_fixed_live_scope():
    manifest, databases = _manifest_and_postimage_databases()
    databases["order"]["om_execution_fills"].documents["extra-fill"] = {
        "_id": "extra-fill",
        "account_id": "068000087558",
        "symbol": "600917",
        "trading_day": 20260528,
        "side": "buy",
        "quantity": 1,
        "price": 5.16,
        "execution_identity": "unplanned-extra-execution",
    }

    with pytest.raises(TargetedRepairError, match="executions_600917"):
        verify_targeted_repair(manifest=manifest, databases=databases)


def test_verify_detects_unplanned_order_in_fixed_live_scope():
    manifest, databases = _manifest_and_postimage_databases()
    databases["order"]["om_orders"].documents["extra-order"] = {
        "_id": "extra-order",
        "account_id": "068000087558",
        "symbol": "688772",
        "trading_day": 20260804,
        "side": "buy",
        "internal_order_id": "ord_manifest_external_duplicate",
    }

    with pytest.raises(TargetedRepairError, match="orders_fixed_live_scope"):
        verify_targeted_repair(manifest=manifest, databases=databases)


def _manifest_and_postimage_databases():
    changes = []

    def add(collection, document_id, *, before=None, after=None, store="order"):
        changes.append(
            {
                "change_id": f"{store}-{collection}-{document_id}",
                "store": store,
                "collection": collection,
                "document_id": document_id,
                "before_document": deepcopy(before),
                "after_document": deepcopy(after),
            }
        )

    add(
        "om_broker_orders",
        "broker-600917",
        after={
            "_id": "broker-600917",
            "account_id": "068000087558",
            "symbol": "600917",
            "trading_day": 20260528,
            "side": "buy",
            "internal_order_id": "ord_5a9cf34c627e43abbf4f0297b6b876e7",
            "broker_order_key": ("account:068000087558:day:20260528:sysid:579"),
            "filled_quantity": 38_700,
            "fill_count": 15,
            "avg_filled_price": 5.16,
        },
    )
    for index in range(15):
        execution_identity = f"600917-execution-{index}"
        add(
            "om_execution_fills",
            f"600917-fill-{index}",
            after={
                "_id": f"600917-fill-{index}",
                "account_id": "068000087558",
                "symbol": "600917",
                "trading_day": 20260528,
                "side": "buy",
                "quantity": 2_580,
                "price": 5.16,
                "execution_identity": execution_identity,
            },
        )
        add(
            "om_trade_facts",
            f"600917-fact-{index}",
            after={
                "_id": f"600917-fact-{index}",
                "account_id": "068000087558",
                "symbol": "600917",
                "trading_day": 20260528,
                "side": "buy",
                "quantity": 2_580,
                "price": 5.16,
                "execution_identity": execution_identity,
            },
        )
    add(
        "om_broker_orders",
        "broker-688772-buy",
        after={
            "_id": "broker-688772-buy",
            "account_id": "068000087558",
            "symbol": "688772",
            "trading_day": 20260804,
            "side": "buy",
            "internal_order_id": "ord_broker_1a67aaff23c42ba4622397fb",
            "broker_order_key": ("account:068000087558:day:20260804:sysid:557"),
            "request_id": None,
            "broker_correlation_token": None,
            "filled_quantity": 10_000,
            "fill_count": 1,
            "avg_filled_price": 14.70,
        },
    )
    add(
        "om_broker_orders",
        "broker-688772-sell",
        after={
            "_id": "broker-688772-sell",
            "account_id": "068000087558",
            "symbol": "688772",
            "trading_day": 20260805,
            "side": "sell",
            "internal_order_id": "ord_edc5fbce00c7475c822dd2cbbe9cdb1d",
            "broker_order_id": "1477443586",
            "order_sysid": "362",
            "broker_order_key": ("account:068000087558:day:20260805:sysid:362"),
            "filled_quantity": 10_000,
            "fill_count": 9,
            "avg_filled_price": 14.80,
        },
    )

    sell_quantities = [164, 203, 340, 358, 200, 2_653, 3_000, 1_000, 2_082]
    executions = [("buy", 10_000), *[("sell", item) for item in sell_quantities]]
    for index, (side, quantity) in enumerate(executions):
        execution_identity = f"execution-{index}"
        trade_fact_id = f"trade-{index}"
        add(
            "om_execution_fills",
            f"fill-{index}",
            after={
                "_id": f"fill-{index}",
                "account_id": "068000087558",
                "symbol": "688772",
                "trading_day": 20260804 if side == "buy" else 20260805,
                "side": side,
                "quantity": quantity,
                "price": 14.70 if side == "buy" else 14.80,
                "execution_identity": execution_identity,
            },
        )
        add(
            "om_trade_facts",
            f"fact-{index}",
            after={
                "_id": f"fact-{index}",
                "account_id": "068000087558",
                "symbol": "688772",
                "trading_day": 20260804 if side == "buy" else 20260805,
                "side": side,
                "quantity": quantity,
                "price": 14.70 if side == "buy" else 14.80,
                "execution_identity": execution_identity,
                "trade_fact_id": trade_fact_id,
            },
        )

    add(
        "om_position_entries",
        "entry-688772",
        after={
            "_id": "entry-688772",
            "entry_id": "entry-688772",
            "symbol": "688772",
            "original_quantity": 10_000,
            "entry_price": 14.70,
            "remaining_quantity": 0,
        },
    )
    for index, (quantity, price) in enumerate(
        [(3_400, 14.70), (3_300, 15.14), (3_200, 15.59), (100, 16.06)]
    ):
        add(
            "om_entry_slices",
            f"slice-{index}",
            after={
                "_id": f"slice-{index}",
                "symbol": "688772",
                "original_quantity": quantity,
                "guardian_price": price,
                "remaining_quantity": 0,
            },
        )

    allocation_quantities = [
        164,
        203,
        340,
        358,
        200,
        2_135,
        518,
        2_782,
        218,
        1_000,
        1_982,
        100,
    ]
    allocation_trade_indexes = [1, 2, 3, 4, 5, 6, 6, 7, 7, 8, 9, 9]
    for index, (quantity, trade_index) in enumerate(
        zip(allocation_quantities, allocation_trade_indexes, strict=True)
    ):
        add(
            "om_exit_allocations",
            f"v2-allocation-{index}",
            after={
                "_id": f"v2-allocation-{index}",
                "entry_id": "entry-688772",
                "symbol": "688772",
                "allocated_quantity": quantity,
                "exit_trade_fact_id": f"trade-{trade_index}",
            },
        )

    for index in range(3):
        add(
            "om_reconciliation_gaps",
            f"gap-{index}",
            before={
                "_id": f"gap-{index}",
                "gap_id": f"gap-id-{index}",
                "symbol": "688772",
            },
        )
        add(
            "om_reconciliation_resolutions",
            f"resolution-{index}",
            before={
                "_id": f"resolution-{index}",
                "gap_id": f"gap-id-{index}",
            },
        )
    for index in range(6):
        add(
            "om_ingest_rejections",
            f"rejection-{index}",
            before={
                "_id": f"rejection-{index}",
                "symbol": "688772",
                "reason_code": "non_board_lot_quantity",
            },
        )

    for collection in (
        "om_order_requests",
        "om_order_events",
        "om_execution_history_archive",
        "position_review_evidence_archive",
    ):
        document = {"_id": f"readonly-{collection}", "marker": collection}
        add(collection, document["_id"], before=document, after=document)
    for collection in (
        "xt_orders",
        "xt_trades",
        "xt_positions",
        "stock_orders",
    ):
        document = {
            "_id": f"readonly-{collection}",
            "stock_code": "688772.SH",
            "volume": 10_000,
        }
        add(
            collection,
            document["_id"],
            before=document,
            after=document,
            store="business",
        )

    document_ids = {}
    for change in changes:
        document_ids.setdefault(change["store"], {}).setdefault(
            change["collection"], []
        ).append(change["document_id"])
    plan = {
        "schema_version": 1,
        "repair_id": "FIX-504-verifier-test",
        "target_main_sha": "2e8754590c1b108637eaf2370ec99f5b1257810f",
        "reason": "verify fixed FIX-504 ledger postconditions",
        "scope": {
            "account_id": "068000087558",
            "symbols": ["600917", "688772"],
            "trading_days": [20260528, 20260804, 20260805],
            "document_ids": document_ids,
            "approved_ids": {
                "order_sysids": ["362"],
                "broker_order_ids": ["1477443586"],
                "broker_trade_ids": [],
                "internal_order_ids": [
                    "ord_5a9cf34c627e43abbf4f0297b6b876e7",
                    "ord_broker_1a67aaff23c42ba4622397fb",
                    "ord_edc5fbce00c7475c822dd2cbbe9cdb1d",
                ],
            },
        },
        "changes": changes,
    }
    before_databases = _databases_from_changes(changes, "before_document")
    manifest = stage_targeted_repair(
        plan=plan,
        databases=before_databases,
        plan_file_sha256="a" * 64,
    )
    return manifest, _databases_from_changes(changes, "after_document")


def _databases_from_changes(changes, document_field):
    grouped = {"order": {}, "business": {}}
    for change in changes:
        document = change[document_field]
        if document is None:
            continue
        grouped[change["store"]].setdefault(change["collection"], []).append(document)
    return {
        store: ReadOnlyDatabase(
            {
                collection: ReadOnlyCollection(documents)
                for collection, documents in collections.items()
            }
        )
        for store, collections in grouped.items()
    }
