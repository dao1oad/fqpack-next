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
    OrderManagementRepository(database=database)

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
