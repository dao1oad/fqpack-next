import importlib
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from freshquant.order_management.broker_identity import BrokerIdentityConflict


def test_order_management_db_uses_bootstrap_dedicated_database(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "order_management:",
                "  mongo_database: unit_test_order_management",
                "  projection_database: unit_test_projection",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as db_module
    import freshquant.order_management.db as om_db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    db_module = importlib.reload(db_module)
    om_db_module = importlib.reload(om_db_module)

    assert (
        bootstrap_module.bootstrap_config.order_management.mongo_database
        == "unit_test_order_management"
    )
    assert om_db_module.DBOrderManagement.name == "unit_test_order_management"
    assert om_db_module.DBOrderProjection.name == "unit_test_projection"
    assert db_module.get_db("order_management") == om_db_module.DBOrderManagement


def test_order_management_projection_db_defaults_to_bootstrap_mongodb_db(
    tmp_path, monkeypatch
):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "order_management:",
                "  mongo_database: freshquant_order_management",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.order_management.db as om_db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    om_db_module = importlib.reload(om_db_module)

    assert bootstrap_module.bootstrap_config.mongodb.db == "freshquant_runtime"
    assert om_db_module.DBOrderProjection.name == "freshquant_runtime"
    assert om_db_module.get_projection_db() == om_db_module.DBOrderProjection


class _FakeCollection:
    def __init__(self):
        self.rows = []
        self.indexes = []

    def create_index(self, keys, **options):
        self.indexes.append((list(keys), dict(options)))
        return options.get("name")

    def insert_one(self, document):
        self.rows.append(dict(document))

    def insert_many(self, documents):
        self.rows.extend(dict(item) for item in documents)

    def find_one(self, query):
        for item in self.find(query):
            return item
        return None

    def find(self, query):
        query = dict(query or {})
        return [item for item in self.rows if _matches_query(item, query)]

    def replace_one(self, query, document, upsert=False):
        query = dict(query or {})
        for index, item in enumerate(self.rows):
            if _matches_query(item, query):
                self.rows[index] = dict(document)
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            self.rows.append(dict(document))
            return SimpleNamespace(matched_count=0, upserted_id=len(self.rows))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def update_one(self, query, update, upsert=False):
        query = dict(query or {})
        updates = dict((update or {}).get("$set") or {})
        assert "_id" not in updates
        for index, item in enumerate(self.rows):
            if _matches_query(item, query):
                next_item = dict(item)
                next_item.update(updates)
                self.rows[index] = next_item
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            inserted = dict(query)
            inserted.update(dict((update or {}).get("$setOnInsert") or {}))
            inserted.update(updates)
            self.rows.append(inserted)
            return SimpleNamespace(matched_count=0, upserted_id=len(self.rows))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def delete_many(self, query):
        query = dict(query or {})
        self.rows = [item for item in self.rows if not _matches_query(item, query)]

    def delete_one(self, query):
        query = dict(query or {})
        for index, item in enumerate(self.rows):
            if _matches_query(item, query):
                del self.rows[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _DuplicateOnFirstUpsertCollection(_FakeCollection):
    def __init__(self, concurrent_document):
        super().__init__()
        self.concurrent_document = dict(concurrent_document)
        self.raise_duplicate = True

    def update_one(self, query, update, upsert=False):
        if upsert and self.raise_duplicate:
            self.raise_duplicate = False
            self.rows.append(dict(self.concurrent_document))
            raise DuplicateKeyError("simulated concurrent canonical insert")
        return super().update_one(query, update, upsert=upsert)


class _FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = _FakeCollection()
        return dict.__getitem__(self, name)


def _matches_query(document, query):
    for key, expected in query.items():
        if key == "$expr":
            operands = list((expected or {}).get("$eq") or [])
            expected_document = operands[1] if len(operands) == 2 else None
            actual_document = {
                field: value for field, value in document.items() if field != "_id"
            }
            if actual_document != expected_document:
                return False
            continue
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in set(expected["$in"]):
                return False
            if "$gt" in expected and not (
                actual is not None and actual > expected["$gt"]
            ):
                return False
            continue
        if actual != expected:
            return False
    return True


def test_order_management_repository_supports_v2_collections_and_basic_crud():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)

    broker_order = {
        "broker_order_key": "border_1",
        "broker_order_id": "9001",
        "symbol": "000001",
        "state": "NEW",
    }
    repository.upsert_broker_order(broker_order, unique_keys=["broker_order_key"])
    assert repository.find_broker_order("border_1") == broker_order
    assert repository.find_broker_order_by_broker_order_id("9001") == broker_order
    assert repository.list_broker_orders(symbol="000001") == [broker_order]

    updated_broker_order = {
        "broker_order_key": "border_1",
        "broker_order_id": "9001",
        "symbol": "000001",
        "state": "FILLED",
        "fill_count": 2,
    }
    saved_order, created_order = repository.upsert_broker_order(
        updated_broker_order,
        unique_keys=["broker_order_key"],
    )
    assert created_order is False
    assert saved_order == updated_broker_order
    assert repository.list_broker_orders(symbol="000001") == [updated_broker_order]

    repository.upsert_broker_order(
        {
            "broker_order_key": "internal_placeholder",
            "symbol": "000002",
            "state": "SUBMITTING",
        },
        unique_keys=["broker_order_key"],
    )
    moved_order = repository.move_broker_order_key(
        "internal_placeholder",
        "account:acct-1:day:20260805:sysid:123",
        {
            "symbol": "000002",
            "state": "FILLED",
        },
    )
    assert repository.find_broker_order("internal_placeholder") is None
    assert moved_order == {
        "broker_order_key": "account:acct-1:day:20260805:sysid:123",
        "symbol": "000002",
        "state": "FILLED",
    }

    execution_fill = {
        "execution_fill_id": "fill_1",
        "broker_trade_id": "trade_1",
        "broker_order_key": "border_1",
        "symbol": "000001",
    }
    saved_fill, created_fill = repository.upsert_execution_fill(
        execution_fill,
        unique_keys=["broker_trade_id"],
    )
    assert created_fill is True
    assert saved_fill == execution_fill
    assert repository.list_execution_fills(symbol="000001") == [execution_fill]
    duplicate_fill, duplicate_created = repository.upsert_execution_fill(
        {
            "execution_fill_id": "fill_ignored",
            "broker_trade_id": "trade_1",
            "broker_order_key": "border_1",
            "symbol": "000001",
        },
        unique_keys=["broker_trade_id"],
    )
    assert duplicate_created is False
    assert duplicate_fill == execution_fill
    assert repository.list_execution_fills(symbol="000001") == [execution_fill]

    gap = {"gap_id": "gap_1", "symbol": "000001", "state": "OPEN"}
    repository.insert_reconciliation_gap(gap)
    repository.update_reconciliation_gap("gap_1", {"state": "RESOLVED"})
    assert repository.list_reconciliation_gaps(state="RESOLVED") == [
        {"gap_id": "gap_1", "symbol": "000001", "state": "RESOLVED"}
    ]

    resolution = {
        "resolution_id": "resolution_1",
        "gap_id": "gap_1",
        "resolution_type": "auto_open_entry",
    }
    repository.insert_reconciliation_resolution(resolution)
    assert repository.list_reconciliation_resolutions(gap_ids=["gap_1"]) == [resolution]

    entry = {"entry_id": "entry_1", "symbol": "000001", "status": "OPEN"}
    repository.replace_position_entry(entry)
    assert repository.find_position_entry("entry_1") == entry
    assert repository.list_position_entries(symbol="000001", status="OPEN") == [entry]
    updated_entry = {
        "entry_id": "entry_1",
        "symbol": "000001",
        "status": "PARTIALLY_EXITED",
        "original_quantity": 400,
        "remaining_quantity": 200,
    }
    repository.replace_position_entry(updated_entry)
    assert repository.find_position_entry("entry_1") == updated_entry
    assert repository.list_position_entries(symbol="000001", status="OPEN") == []
    assert repository.list_position_entries(
        symbol="000001",
        status="PARTIALLY_EXITED",
    ) == [updated_entry]

    slices = [
        {
            "entry_slice_id": "slice_1",
            "entry_id": "entry_1",
            "symbol": "000001",
            "remaining_quantity": 100,
        }
    ]
    repository.replace_entry_slices_for_entry("entry_1", slices)
    assert repository.list_open_entry_slices(symbol="000001") == slices
    replacement_slices = [
        {
            "entry_slice_id": "slice_2",
            "entry_id": "entry_1",
            "symbol": "000001",
            "original_quantity": 200,
            "remaining_quantity": 200,
        }
    ]
    repository.replace_entry_slices_for_entry("entry_1", replacement_slices)
    assert repository.list_open_entry_slices(symbol="000001") == replacement_slices
    closed_slice = {
        "entry_slice_id": "slice_closed",
        "entry_id": "entry_1",
        "symbol": "000001",
        "original_quantity": 0,
        "remaining_quantity": 0,
        "status": "CLOSED",
    }
    repository.upsert_entry_slices([closed_slice])
    repository.upsert_entry_slices(
        [{**replacement_slices[0], "remaining_quantity": 0, "status": "CLOSED"}]
    )
    assert {
        item["entry_slice_id"]
        for item in repository.list_entry_slices(entry_ids=["entry_1"])
    } == {"slice_2", "slice_closed"}

    allocation = {
        "allocation_id": "alloc_1",
        "entry_id": "entry_1",
        "symbol": "000001",
        "allocated_quantity": 200,
    }
    repository.insert_exit_allocations([allocation])
    assert repository.list_exit_allocations(entry_ids=["entry_1"]) == [allocation]
    assert repository.find_exit_allocation_reference_errors() == [
        {
            "allocation_id": "alloc_1",
            "reference_type": "entry_slice_id",
            "reference_id": None,
        },
        {
            "allocation_id": None,
            "reference_type": "entry_slice_allocation_quantity",
            "reference_id": "slice_2",
            "expected_quantity": 200,
            "actual_quantity": 0,
        },
    ]

    repository.exit_allocations.rows[0]["entry_slice_id"] = "slice_2"
    assert repository.find_exit_allocation_reference_errors() == []

    binding = {"entry_id": "entry_1", "symbol": "000001", "enabled": True}
    repository.upsert_entry_stoploss_binding(binding)
    assert repository.find_entry_stoploss_binding("entry_1") == binding
    assert repository.list_entry_stoploss_bindings(symbol="000001", enabled=True) == [
        binding
    ]
    updated_binding = {
        "entry_id": "entry_1",
        "symbol": "000001",
        "enabled": False,
        "trigger_price": 12.3,
    }
    repository.upsert_entry_stoploss_binding(updated_binding)
    assert repository.find_entry_stoploss_binding("entry_1") == updated_binding
    assert repository.list_entry_stoploss_bindings(symbol="000001", enabled=True) == []
    assert repository.list_entry_stoploss_bindings(symbol="000001", enabled=False) == [
        updated_binding
    ]

    rejection = {
        "rejection_id": "reject_1",
        "symbol": "000001",
        "reason_code": "odd_lot",
    }
    repository.insert_ingest_rejection(rejection)
    assert repository.list_ingest_rejections(symbol="000001") == [rejection]


def test_repository_creates_partial_unique_indexes_for_canonical_identities():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)

    assert database == {}

    repository._ensure_canonical_indexes()
    repository._ensure_canonical_indexes()

    assert database["om_orders"].indexes == [
        (
            [("internal_order_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"internal_order_id": {"$type": "string"}},
                "name": "uq_om_orders_internal_order_id",
            },
        ),
        (
            [("broker_correlation_token", 1)],
            {
                "unique": True,
                "partialFilterExpression": {
                    "broker_correlation_token": {"$type": "string"}
                },
                "name": "uq_om_orders_broker_correlation_token",
            },
        ),
    ]
    assert database["om_broker_orders"].indexes == [
        (
            [("broker_order_key", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"broker_order_key": {"$type": "string"}},
                "name": "uq_om_broker_orders_broker_order_key",
            },
        )
    ]
    assert database["om_trade_facts"].indexes == [
        (
            [("execution_identity", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"execution_identity": {"$type": "string"}},
                "name": "uq_om_trade_facts_execution_identity",
            },
        )
    ]
    assert database["om_execution_fills"].indexes == [
        (
            [("execution_identity", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"execution_identity": {"$type": "string"}},
                "name": "uq_om_execution_fills_execution_identity",
            },
        )
    ]
    assert database["om_position_entries"].indexes == [
        (
            [("entry_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"entry_id": {"$type": "string"}},
                "name": "uq_om_position_entries_entry_id",
            },
        )
    ]
    assert database["om_entry_slices"].indexes == [
        (
            [("entry_slice_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"entry_slice_id": {"$type": "string"}},
                "name": "uq_om_entry_slices_entry_slice_id",
            },
        )
    ]
    assert database["om_sell_allocations"].indexes == [
        (
            [("allocation_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"allocation_id": {"$type": "string"}},
                "name": "uq_om_sell_allocations_allocation_id",
            },
        )
    ]
    assert database["om_exit_allocations"].indexes == [
        (
            [("allocation_id", 1)],
            {
                "unique": True,
                "partialFilterExpression": {"allocation_id": {"$type": "string"}},
                "name": "uq_om_exit_allocations_allocation_id",
            },
        )
    ]


def test_repository_upserts_existing_broker_order_without_setting_mongo_id():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_broker_orders"].rows.append(
        {
            "_id": "mongo-id-1",
            "broker_order_key": "canonical-1",
            "account_id": "acct-1",
            "trading_day": 20260805,
            "order_sysid": "123",
            "symbol": "688772",
            "side": "buy",
            "state": "SUBMITTED",
        }
    )

    saved, created = repository.upsert_broker_order(
        {
            "_id": "mongo-id-1",
            "broker_order_key": "canonical-1",
            "account_id": "acct-1",
            "trading_day": 20260805,
            "order_sysid": "123",
            "symbol": "688772",
            "side": "buy",
            "state": "FILLED",
        },
        unique_keys=["broker_order_key"],
    )

    assert created is False
    assert saved["_id"] == "mongo-id-1"
    assert saved["state"] == "FILLED"


def test_insert_order_is_idempotent_during_concurrent_canonical_insert():
    from freshquant.order_management.repository import OrderManagementRepository

    canonical = {
        "internal_order_id": "ord-broker-only-race",
        "request_id": None,
        "account_id": "acct-1",
        "trading_day": 20260805,
        "symbol": "688772",
        "side": "buy",
        "state": "PARTIAL_FILLED",
    }
    database = _FakeDatabase()
    database["om_orders"] = _DuplicateOnFirstUpsertCollection(canonical)
    repository = OrderManagementRepository(database=database)

    saved = repository.insert_order(dict(canonical))

    assert saved == canonical
    assert database["om_orders"].rows == [canonical]


def test_insert_order_rejects_concurrent_document_with_different_owner():
    from freshquant.order_management.repository import OrderManagementRepository

    canonical = {
        "internal_order_id": "ord-broker-only-race",
        "request_id": "request-existing",
        "account_id": "acct-1",
        "trading_day": 20260805,
        "symbol": "688772",
        "side": "buy",
        "state": "PARTIAL_FILLED",
    }
    database = _FakeDatabase()
    database["om_orders"] = _DuplicateOnFirstUpsertCollection(canonical)
    repository = OrderManagementRepository(database=database)

    with pytest.raises(BrokerIdentityConflict, match="request ownership"):
        repository.insert_order({**canonical, "request_id": "request-other"})

    assert database["om_orders"].rows == [canonical]


def test_move_broker_order_key_merges_existing_placeholder_into_canonical_target():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_broker_orders"].rows.extend(
        [
            {
                "_id": "placeholder-id",
                "broker_order_key": "ord-placeholder",
                "internal_order_id": "ord-internal",
                "account_id": "acct-1",
                "symbol": "688772",
                "side": "buy",
                "state": "SUBMITTING",
            },
            {
                "_id": "canonical-id",
                "broker_order_key": "account:acct-1:day:20260805:sysid:557",
                "internal_order_id": "ord-broker-only",
                "account_id": "acct-1",
                "trading_day": 20260805,
                "order_sysid": "557",
                "symbol": "688772",
                "side": "buy",
                "state": "PARTIAL_FILLED",
                "filled_quantity": 100,
            },
        ]
    )

    saved = repository.move_broker_order_key(
        "ord-placeholder",
        "account:acct-1:day:20260805:sysid:557",
        {
            "_id": "canonical-id",
            "internal_order_id": "ord-internal",
            "account_id": "acct-1",
            "trading_day": 20260805,
            "order_sysid": "557",
            "symbol": "688772",
            "side": "buy",
            "state": "FILLED",
            "filled_quantity": 10000,
        },
    )

    assert repository.find_broker_order("ord-placeholder") is None
    assert saved["_id"] == "canonical-id"
    assert saved["internal_order_id"] == "ord-internal"
    assert saved["filled_quantity"] == 10000
    assert len(database["om_broker_orders"].rows) == 1


def test_duplicate_key_race_is_idempotent_only_for_consistent_execution():
    from freshquant.order_management.repository import OrderManagementRepository

    canonical = {
        "execution_fill_id": "fill-existing",
        "execution_identity": "execution:canonical-1",
        "broker_trade_id": "trade-1",
        "broker_order_key": "canonical-order-1",
        "internal_order_id": "ord-1",
        "account_id": "acct-1",
        "trading_day": 20260805,
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
    }
    database = _FakeDatabase()
    database["om_execution_fills"] = _DuplicateOnFirstUpsertCollection(canonical)
    repository = OrderManagementRepository(database=database)

    replay, created = repository.upsert_execution_fill(
        {**canonical, "execution_fill_id": "fill-replay"},
        unique_keys=["execution_identity"],
    )

    assert created is False
    assert replay == canonical

    with pytest.raises(BrokerIdentityConflict, match="quantity"):
        repository.upsert_execution_fill(
            {**canonical, "execution_fill_id": "fill-conflict", "quantity": 203},
            unique_keys=["execution_identity"],
        )


def test_legacy_execution_replay_migrates_fill_and_trade_fact_in_place():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy",
            "account_id": "acct-legacy",
            "broker_order_id": "broker-order-legacy",
        }
    )
    legacy_common = {
        "broker_order_key": "ord-legacy",
        "internal_order_id": "ord-legacy",
        "broker_order_id": "broker-order-legacy",
        "broker_trade_id": 362,
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
        "source": "xt_trade_callback",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "trade-fact-legacy", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "fill-legacy", **legacy_common}
    )
    canonical_common = {
        **legacy_common,
        "broker_order_key": (
            "account:acct-legacy:day:20260805:symbol:688772:"
            "side:sell:order:broker-order-legacy"
        ),
        "execution_identity": "execution:acct-legacy:20260805:trade-legacy",
        "broker_trade_id": "362",
        "account_id": "acct-legacy",
        "trading_day": 20260805,
    }

    saved_trade_fact, created_trade_fact = repository.upsert_trade_fact(
        {"trade_fact_id": "ignored-new-trade-fact", **canonical_common},
        unique_keys=["execution_identity"],
    )
    saved_fill, created_fill = repository.upsert_execution_fill(
        {
            "execution_fill_id": "ignored-new-fill",
            **canonical_common,
            "projection_status": "PENDING",
            "projection_plan": None,
        },
        unique_keys=["execution_identity"],
    )
    replayed_trade_fact, replayed_trade_fact_created = repository.upsert_trade_fact(
        {"trade_fact_id": "ignored-replay-trade-fact", **canonical_common},
        unique_keys=["execution_identity"],
    )
    replayed_fill, replayed_fill_created = repository.upsert_execution_fill(
        {
            "execution_fill_id": "ignored-replay-fill",
            **canonical_common,
            "projection_status": "PENDING",
            "projection_plan": None,
        },
        unique_keys=["execution_identity"],
    )

    assert created_trade_fact is False
    assert created_fill is False
    assert len(database["om_trade_facts"].rows) == 1
    assert len(database["om_execution_fills"].rows) == 1
    assert saved_trade_fact["trade_fact_id"] == "trade-fact-legacy"
    assert saved_fill["execution_fill_id"] == "fill-legacy"
    assert (
        saved_trade_fact["execution_identity"] == canonical_common["execution_identity"]
    )
    assert saved_fill["execution_identity"] == canonical_common["execution_identity"]
    assert saved_fill["projection_status"] == "PENDING"
    assert saved_fill["projection_legacy_replay_required"] is True
    assert saved_fill.get("projection_legacy_proven_applied") is None
    assert replayed_trade_fact_created is False
    assert replayed_fill_created is False
    assert replayed_trade_fact["trade_fact_id"] == "trade-fact-legacy"
    assert replayed_fill["execution_fill_id"] == "fill-legacy"


def test_legacy_buy_execution_with_complete_projection_evidence_is_applied():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    canonical_broker_order_key = (
        "account:acct-legacy:day:20260805:symbol:688772:"
        "side:buy:order:broker-order-legacy-buy"
    )
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy-buy",
            "account_id": "acct-legacy",
            "broker_order_id": "broker-order-legacy-buy",
        }
    )
    legacy_common = {
        "broker_order_key": "ord-legacy-buy",
        "internal_order_id": "ord-legacy-buy",
        "broker_order_id": "broker-order-legacy-buy",
        "broker_trade_id": 501,
        "symbol": "688772",
        "side": "buy",
        "quantity": 10000,
        "price": 14.0,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
        "source": "xt_trade_callback",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "trade-fact-legacy-buy", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "fill-legacy-buy", **legacy_common}
    )
    database["om_buy_lots"].rows.append(
        {
            "buy_lot_id": "lot-legacy-buy",
            "origin_trade_fact_id": "trade-fact-legacy-buy",
            "symbol": "688772",
            "original_quantity": 10000,
            "remaining_quantity": 10000,
            "buy_price_real": 14.0,
        }
    )
    database["om_lot_slices"].rows.extend(
        [
            {
                "lot_slice_id": "lot-slice-legacy-buy-1",
                "buy_lot_id": "lot-legacy-buy",
                "original_quantity": 3400,
            },
            {
                "lot_slice_id": "lot-slice-legacy-buy-2",
                "buy_lot_id": "lot-legacy-buy",
                "original_quantity": 6600,
            },
        ]
    )
    database["om_position_entries"].rows.append(
        {
            "entry_id": "entry-legacy-buy",
            "symbol": "688772",
            "source_ref_type": "broker_order",
            "source_ref_id": canonical_broker_order_key,
            "original_quantity": 10000,
            "remaining_quantity": 10000,
            "entry_price": 14.0,
        }
    )
    database["om_entry_slices"].rows.extend(
        [
            {
                "entry_slice_id": "entry-slice-legacy-buy-1",
                "entry_id": "entry-legacy-buy",
                "original_quantity": 3400,
            },
            {
                "entry_slice_id": "entry-slice-legacy-buy-2",
                "entry_id": "entry-legacy-buy",
                "original_quantity": 6600,
            },
        ]
    )
    canonical_common = {
        **legacy_common,
        "broker_order_key": canonical_broker_order_key,
        "execution_identity": "execution:acct-legacy:20260805:legacy-buy",
        "broker_trade_id": "501",
        "account_id": "acct-legacy",
        "trading_day": 20260805,
    }

    repository.upsert_trade_fact(
        {"trade_fact_id": "ignored-new-buy-fact", **canonical_common},
        unique_keys=["execution_identity"],
    )
    saved_fill, created = repository.upsert_execution_fill(
        {
            "execution_fill_id": "ignored-new-buy-fill",
            **canonical_common,
            "projection_status": "PENDING",
            "projection_plan": None,
        },
        unique_keys=["execution_identity"],
    )

    assert created is False
    assert saved_fill["execution_fill_id"] == "fill-legacy-buy"
    assert saved_fill["projection_status"] == "APPLIED"
    assert saved_fill["projection_legacy_proven_applied"] is True


def test_legacy_sell_execution_with_complete_projection_evidence_is_applied():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy-sell",
            "account_id": "acct-legacy",
            "broker_order_id": "broker-order-legacy-sell",
        }
    )
    legacy_common = {
        "broker_order_key": "ord-legacy-sell",
        "internal_order_id": "ord-legacy-sell",
        "broker_order_id": "broker-order-legacy-sell",
        "broker_trade_id": 502,
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
        "source": "xt_trade_callback",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "trade-fact-legacy-sell", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "fill-legacy-sell", **legacy_common}
    )
    database["om_exit_allocations"].rows.append(
        {
            "allocation_id": "exit-allocation-legacy-sell",
            "entry_id": "entry-legacy-sell",
            "entry_slice_id": "entry-slice-legacy-sell",
            "exit_trade_fact_id": "trade-fact-legacy-sell",
            "allocated_quantity": 164,
        }
    )
    database["om_position_entries"].rows.append(
        {
            "entry_id": "entry-legacy-sell",
            "symbol": "688772",
            "sell_history": [
                {
                    "exit_trade_fact_id": "trade-fact-legacy-sell",
                    "allocated_quantity": 164,
                }
            ],
        }
    )
    canonical_common = {
        **legacy_common,
        "broker_order_key": (
            "account:acct-legacy:day:20260805:symbol:688772:"
            "side:sell:order:broker-order-legacy-sell"
        ),
        "execution_identity": "execution:acct-legacy:20260805:legacy-sell",
        "broker_trade_id": "502",
        "account_id": "acct-legacy",
        "trading_day": 20260805,
    }

    repository.upsert_trade_fact(
        {"trade_fact_id": "ignored-new-sell-fact", **canonical_common},
        unique_keys=["execution_identity"],
    )
    saved_fill, created = repository.upsert_execution_fill(
        {
            "execution_fill_id": "ignored-new-sell-fill",
            **canonical_common,
            "projection_status": "PENDING",
            "projection_plan": None,
        },
        unique_keys=["execution_identity"],
    )

    assert created is False
    assert saved_fill["execution_fill_id"] == "fill-legacy-sell"
    assert saved_fill["projection_status"] == "APPLIED"
    assert saved_fill["projection_legacy_proven_applied"] is True


def test_legacy_buy_execution_with_partial_projection_evidence_fails_closed():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy-partial",
            "account_id": "acct-legacy",
            "broker_order_id": "broker-order-legacy-partial",
        }
    )
    legacy_common = {
        "broker_order_key": "ord-legacy-partial",
        "internal_order_id": "ord-legacy-partial",
        "broker_order_id": "broker-order-legacy-partial",
        "broker_trade_id": 503,
        "symbol": "688772",
        "side": "buy",
        "quantity": 10000,
        "price": 14.0,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "trade-fact-legacy-partial", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "fill-legacy-partial", **legacy_common}
    )
    database["om_buy_lots"].rows.append(
        {
            "buy_lot_id": "lot-legacy-partial",
            "origin_trade_fact_id": "trade-fact-legacy-partial",
            "symbol": "688772",
            "original_quantity": 10000,
            "remaining_quantity": 10000,
            "buy_price_real": 14.0,
        }
    )
    database["om_lot_slices"].rows.append(
        {
            "lot_slice_id": "lot-slice-legacy-partial",
            "buy_lot_id": "lot-legacy-partial",
            "original_quantity": 10000,
        }
    )
    canonical_common = {
        **legacy_common,
        "broker_order_key": (
            "account:acct-legacy:day:20260805:symbol:688772:"
            "side:buy:order:broker-order-legacy-partial"
        ),
        "execution_identity": "execution:acct-legacy:20260805:legacy-partial",
        "broker_trade_id": "503",
        "account_id": "acct-legacy",
        "trading_day": 20260805,
    }

    repository.upsert_trade_fact(
        {"trade_fact_id": "ignored-new-partial-fact", **canonical_common},
        unique_keys=["execution_identity"],
    )
    with pytest.raises(BrokerIdentityConflict, match="partial"):
        repository.upsert_execution_fill(
            {
                "execution_fill_id": "ignored-new-partial-fill",
                **canonical_common,
                "projection_status": "PENDING",
                "projection_plan": None,
            },
            unique_keys=["execution_identity"],
        )

    assert database["om_execution_fills"].rows[0].get("execution_identity") is None


def test_legacy_execution_replay_with_ambiguous_trade_id_fails_closed():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy",
            "account_id": "acct-legacy",
        }
    )
    for execution_fill_id in ("fill-legacy-1", "fill-legacy-2"):
        database["om_execution_fills"].rows.append(
            {
                "execution_fill_id": execution_fill_id,
                "broker_order_key": "ord-legacy",
                "internal_order_id": "ord-legacy",
                "broker_trade_id": "trade-ambiguous",
                "symbol": "688772",
                "side": "sell",
                "quantity": 164,
                "price": 14.8,
                "trade_time": 1785895200,
                "date": 20260805,
                "time": "10:00:00",
            }
        )

    with pytest.raises(BrokerIdentityConflict, match="ambiguous"):
        repository.upsert_execution_fill(
            {
                "execution_fill_id": "fill-new",
                "broker_order_key": "ord-legacy",
                "internal_order_id": "ord-legacy",
                "broker_trade_id": "trade-ambiguous",
                "execution_identity": "execution:ambiguous",
                "account_id": "acct-legacy",
                "trading_day": 20260805,
                "symbol": "688772",
                "side": "sell",
                "quantity": 164,
                "price": 14.8,
                "trade_time": 1785895200,
                "date": 20260805,
                "time": "10:00:00",
                "projection_status": "PENDING",
                "projection_plan": None,
            },
            unique_keys=["execution_identity"],
        )

    assert len(database["om_execution_fills"].rows) == 2
    assert all(
        item.get("execution_identity") is None
        for item in database["om_execution_fills"].rows
    )


def test_legacy_execution_replay_without_provable_account_fails_closed():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    legacy_common = {
        "broker_order_key": "unknown-order",
        "internal_order_id": "unknown-order",
        "broker_trade_id": "trade-unowned",
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "fact-unowned", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "fill-unowned", **legacy_common}
    )

    with pytest.raises(BrokerIdentityConflict, match="account_id"):
        repository.upsert_execution_fill(
            {
                "execution_fill_id": "fill-new",
                "broker_order_key": "unknown-order",
                "internal_order_id": "unknown-order",
                "broker_trade_id": "trade-unowned",
                "execution_identity": "execution:unowned",
                "account_id": "acct-legacy",
                "trading_day": 20260805,
                "symbol": "688772",
                "side": "sell",
                "quantity": 164,
                "price": 14.8,
                "trade_time": 1785895200,
                "date": 20260805,
                "time": "10:00:00",
                "projection_status": "PENDING",
                "projection_plan": None,
            },
            unique_keys=["execution_identity"],
        )

    assert len(database["om_execution_fills"].rows) == 1
    assert database["om_execution_fills"].rows[0].get("execution_identity") is None


@pytest.mark.parametrize("legacy_collection", ["om_trade_facts", "om_execution_fills"])
def test_legacy_execution_replay_requires_paired_fact_and_fill(legacy_collection):
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-legacy-pair",
            "account_id": "acct-legacy",
        }
    )
    legacy = {
        "broker_order_key": "ord-legacy-pair",
        "internal_order_id": "ord-legacy-pair",
        "broker_trade_id": "trade-legacy-pair",
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
    }
    identity_field = (
        "trade_fact_id"
        if legacy_collection == "om_trade_facts"
        else "execution_fill_id"
    )
    database[legacy_collection].rows.append(
        {identity_field: f"legacy-{identity_field}", **legacy}
    )
    incoming = {
        **legacy,
        "execution_identity": "execution:acct-legacy:20260805:trade-legacy-pair",
        "account_id": "acct-legacy",
        "trading_day": 20260805,
        "broker_order_key": (
            "account:acct-legacy:day:20260805:symbol:688772:"
            "side:sell:order:ord-legacy-pair"
        ),
    }

    with pytest.raises(BrokerIdentityConflict, match="requires paired"):
        repository.preflight_execution_replay(incoming)

    assert len(database[legacy_collection].rows) == 1
    assert database[legacy_collection].rows[0].get("execution_identity") is None
    other_collection = (
        "om_execution_fills"
        if legacy_collection == "om_trade_facts"
        else "om_trade_facts"
    )
    assert database[other_collection].rows == []


def test_legacy_account_proof_enumerates_all_broker_order_candidates():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    for account_id in ("acct-a", "acct-b"):
        database["om_orders"].rows.append(
            {
                "internal_order_id": f"ord-{account_id}",
                "broker_order_id": "shared-broker-order",
                "account_id": account_id,
            }
        )
    legacy_common = {
        "broker_trade_id": "shared-trade",
        "broker_order_id": "shared-broker-order",
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "legacy-fact-shared", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "legacy-fill-shared", **legacy_common}
    )

    with pytest.raises(BrokerIdentityConflict, match="account_id"):
        repository.preflight_execution_replay(
            {
                **legacy_common,
                "execution_identity": "execution:acct-a:20260805:shared-trade",
                "account_id": "acct-a",
                "trading_day": 20260805,
            }
        )


def test_tracking_legacy_account_proof_uses_preupdate_order_snapshot():
    from freshquant.order_management.repository import OrderManagementRepository
    from freshquant.order_management.tracking.service import OrderTrackingService

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    database["om_orders"].rows.append(
        {
            "internal_order_id": "ord-unowned",
            "broker_order_id": "broker-unowned",
            "symbol": "688772",
            "side": "sell",
            "state": "SUBMITTED",
        }
    )
    legacy_common = {
        "broker_order_key": "ord-unowned",
        "internal_order_id": "ord-unowned",
        "broker_order_id": "broker-unowned",
        "broker_trade_id": "trade-unowned-tracking",
        "symbol": "688772",
        "side": "sell",
        "quantity": 164,
        "price": 14.8,
        "trade_time": 1785895200,
        "date": 20260805,
        "time": "10:00:00",
        "source": "xt_trade_callback",
    }
    database["om_trade_facts"].rows.append(
        {"trade_fact_id": "legacy-fact-unowned", **legacy_common}
    )
    database["om_execution_fills"].rows.append(
        {"execution_fill_id": "legacy-fill-unowned", **legacy_common}
    )
    service = OrderTrackingService(repository=repository)

    with pytest.raises(BrokerIdentityConflict, match="account_id"):
        service.ingest_trade_report_with_meta(
            {
                **legacy_common,
                "account_id": "arbitrary-account",
                "trading_day": 20260805,
            }
        )

    assert database["om_orders"].rows[0].get("account_id") is None
    assert all(
        item.get("execution_identity") is None
        for collection in ("om_trade_facts", "om_execution_fills")
        for item in database[collection].rows
    )


def test_projection_cas_preserves_concurrent_document_change():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    before = {
        "entry_id": "entry-cas",
        "remaining_quantity": 100,
        "status": "OPEN",
    }
    database["om_position_entries"].rows.append(dict(before))
    database["om_position_entries"].rows[0]["remaining_quantity"] = 77

    with pytest.raises(BrokerIdentityConflict, match="compare-and-set conflict"):
        repository.compare_and_set_projection_document(
            "position_entry",
            before=before,
            after={**before, "remaining_quantity": 0, "status": "CLOSED"},
        )

    assert database["om_position_entries"].rows == [
        {**before, "remaining_quantity": 77}
    ]


def test_allocation_inserts_require_unique_id_and_never_overwrite():
    from freshquant.order_management.repository import OrderManagementRepository

    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)

    with pytest.raises(BrokerIdentityConflict, match="allocation_id is required"):
        repository.insert_sell_allocations([{"allocated_quantity": 100}])
    with pytest.raises(BrokerIdentityConflict, match="duplicate allocation_id"):
        repository.insert_sell_allocations(
            [
                {"allocation_id": "alloc-1", "allocated_quantity": 100},
                {"allocation_id": "alloc-1", "allocated_quantity": 100},
            ]
        )

    repository.insert_sell_allocations(
        [{"allocation_id": "alloc-1", "allocated_quantity": 100}]
    )
    repository.insert_sell_allocations(
        [{"allocation_id": "alloc-1", "allocated_quantity": 100}]
    )
    with pytest.raises(BrokerIdentityConflict, match="compare-and-set conflict"):
        repository.insert_sell_allocations(
            [{"allocation_id": "alloc-1", "allocated_quantity": 200}]
        )

    assert database["om_sell_allocations"].rows == [
        {"allocation_id": "alloc-1", "allocated_quantity": 100}
    ]


def test_allocation_integrity_rejects_slice_owned_by_another_entry():
    from freshquant.order_management.allocation_integrity import (
        find_exit_allocation_integrity_errors,
    )

    errors = find_exit_allocation_integrity_errors(
        position_entries=[
            {
                "entry_id": "entry-1",
                "symbol": "688772",
                "original_quantity": 100,
                "remaining_quantity": 0,
            },
            {
                "entry_id": "entry-2",
                "symbol": "688772",
                "original_quantity": 100,
                "remaining_quantity": 100,
            },
        ],
        entry_slices=[
            {
                "entry_slice_id": "slice-2",
                "entry_id": "entry-2",
                "symbol": "688772",
                "original_quantity": 100,
                "remaining_quantity": 0,
            }
        ],
        exit_allocations=[
            {
                "allocation_id": "allocation-1",
                "entry_id": "entry-1",
                "entry_slice_id": "slice-2",
                "symbol": "688772",
                "allocated_quantity": 100,
            }
        ],
    )

    assert errors == [
        {
            "allocation_id": "allocation-1",
            "reference_type": "entry_slice_owner",
            "reference_id": "slice-2",
            "expected_entry_id": "entry-1",
            "actual_entry_id": "entry-2",
        }
    ]


def test_allocation_integrity_enforces_entry_and_slice_quantity_conservation():
    from freshquant.order_management.allocation_integrity import (
        find_exit_allocation_integrity_errors,
    )

    errors = find_exit_allocation_integrity_errors(
        position_entries=[
            {
                "entry_id": "entry-1",
                "symbol": "688772",
                "original_quantity": 300,
                "remaining_quantity": 100,
            }
        ],
        entry_slices=[
            {
                "entry_slice_id": "slice-1",
                "entry_id": "entry-1",
                "symbol": "688772",
                "original_quantity": 300,
                "remaining_quantity": 100,
            }
        ],
        exit_allocations=[
            {
                "allocation_id": "allocation-1",
                "entry_id": "entry-1",
                "entry_slice_id": "slice-1",
                "symbol": "688772",
                "allocated_quantity": 100,
            }
        ],
    )

    assert errors == [
        {
            "allocation_id": None,
            "reference_type": "entry_allocation_quantity",
            "reference_id": "entry-1",
            "expected_quantity": 200,
            "actual_quantity": 100,
        },
        {
            "allocation_id": None,
            "reference_type": "entry_slice_allocation_quantity",
            "reference_id": "slice-1",
            "expected_quantity": 200,
            "actual_quantity": 100,
        },
    ]
