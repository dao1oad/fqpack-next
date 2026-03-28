import importlib


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
                return
        if upsert:
            self.rows.append(dict(document))

    def update_one(self, query, update):
        query = dict(query or {})
        updates = dict((update or {}).get("$set") or {})
        for index, item in enumerate(self.rows):
            if _matches_query(item, query):
                next_item = dict(item)
                next_item.update(updates)
                self.rows[index] = next_item
                return

    def delete_many(self, query):
        query = dict(query or {})
        self.rows = [item for item in self.rows if not _matches_query(item, query)]


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
            "remaining_quantity": 200,
        }
    ]
    repository.replace_entry_slices_for_entry("entry_1", replacement_slices)
    assert repository.list_open_entry_slices(symbol="000001") == replacement_slices

    allocation = {
        "allocation_id": "alloc_1",
        "entry_id": "entry_1",
        "symbol": "000001",
    }
    repository.insert_exit_allocations([allocation])
    assert repository.list_exit_allocations(entry_ids=["entry_1"]) == [allocation]

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
