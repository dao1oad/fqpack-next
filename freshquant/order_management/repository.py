# -*- coding: utf-8 -*-

from freshquant.order_management.db import DBOrderManagement


class OrderManagementRepository:
    def __init__(self, database=None):
        self.database = database if database is not None else DBOrderManagement

    @property
    def order_requests(self):
        return self.database["om_order_requests"]

    # Legacy collection accessors stay available during migration so existing
    # read-models and compatibility flows can keep working while V2 is added.
    @property
    def orders(self):
        return self.database["om_orders"]

    @property
    def broker_orders(self):
        return self.database["om_broker_orders"]

    @property
    def order_events(self):
        return self.database["om_order_events"]

    @property
    def trade_facts(self):
        return self.database["om_trade_facts"]

    @property
    def execution_fills(self):
        return self.database["om_execution_fills"]

    @property
    def buy_lots(self):
        return self.database["om_buy_lots"]

    @property
    def position_entries(self):
        return self.database["om_position_entries"]

    @property
    def lot_slices(self):
        return self.database["om_lot_slices"]

    @property
    def entry_slices(self):
        return self.database["om_entry_slices"]

    @property
    def sell_allocations(self):
        return self.database["om_sell_allocations"]

    @property
    def exit_allocations(self):
        return self.database["om_exit_allocations"]

    @property
    def external_candidates(self):
        return self.database["om_external_candidates"]

    @property
    def reconciliation_gaps(self):
        return self.database["om_reconciliation_gaps"]

    @property
    def reconciliation_resolutions(self):
        return self.database["om_reconciliation_resolutions"]

    @property
    def stoploss_bindings(self):
        return self.database["om_stoploss_bindings"]

    @property
    def entry_stoploss_bindings(self):
        return self.database["om_entry_stoploss_bindings"]

    @property
    def credit_subjects(self):
        return self.database["om_credit_subjects"]

    @property
    def ingest_rejections(self):
        return self.database["om_ingest_rejections"]

    def insert_order_request(self, document):
        self.order_requests.insert_one(document)
        return document

    # Legacy CRUD below remains available for existing runtime paths while V2
    # write/read models are introduced incrementally.
    def find_order_request(self, request_id):
        return self.order_requests.find_one({"request_id": request_id})

    def list_order_requests(
        self,
        *,
        symbol=None,
        action=None,
        states=None,
        scope_type=None,
        scope_ref_id=None,
        scope_ref_ids=None,
        request_ids=None,
        created_at_gte=None,
        sort_created_at_desc=False,
        limit=None,
    ):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if action is not None:
            query["action"] = action
        if states is not None:
            query["state"] = {"$in": list(states)}
        if scope_type is not None:
            query["scope_type"] = scope_type
        if scope_ref_id is not None:
            query["scope_ref_id"] = scope_ref_id
        elif scope_ref_ids is not None:
            query["scope_ref_id"] = {"$in": list(scope_ref_ids)}
        if request_ids is not None:
            query["request_id"] = {"$in": list(request_ids)}
        if created_at_gte is not None:
            query["created_at"] = {"$gte": created_at_gte}
        cursor = self.order_requests.find(query)
        if sort_created_at_desc:
            cursor = cursor.sort("created_at", -1)
        if limit is not None:
            cursor = cursor.limit(max(int(limit), 0))
        return list(cursor)

    def insert_order(self, document):
        self.orders.insert_one(document)
        return document

    def upsert_broker_order(self, document, unique_keys):
        query = {key: document[key] for key in unique_keys}
        existing = self.broker_orders.find_one(query)
        if existing is not None:
            self.broker_orders.update_one(query, {"$set": document})
            return self.broker_orders.find_one(query), False
        self.broker_orders.insert_one(document)
        return document, True

    def insert_order_event(self, document):
        self.order_events.insert_one(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        query = {key: document[key] for key in unique_keys}
        existing = self.trade_facts.find_one(query)
        if existing is not None:
            return existing, False
        self.trade_facts.insert_one(document)
        return document, True

    def find_order(self, internal_order_id):
        return self.orders.find_one({"internal_order_id": internal_order_id})

    def find_broker_order(self, broker_order_key):
        return self.broker_orders.find_one({"broker_order_key": broker_order_key})

    def find_broker_order_by_broker_order_id(self, broker_order_id):
        return self.broker_orders.find_one({"broker_order_id": str(broker_order_id)})

    def find_order_by_request_id(self, request_id):
        return self.orders.find_one({"request_id": request_id})

    def find_order_by_broker_order_id(self, broker_order_id):
        return self.orders.find_one({"broker_order_id": str(broker_order_id)})

    def list_orders_by_broker_order_id(self, broker_order_id):
        if broker_order_id in (None, "", "None"):
            return []
        return list(self.orders.find({"broker_order_id": str(broker_order_id)}))

    def update_order(self, internal_order_id, updates):
        self.orders.update_one(
            {"internal_order_id": internal_order_id},
            {"$set": updates},
        )
        return self.find_order(internal_order_id)

    def upsert_execution_fill(self, document, unique_keys):
        query = {key: document[key] for key in unique_keys}
        existing = self.execution_fills.find_one(query)
        if existing is not None:
            return existing, False
        self.execution_fills.insert_one(document)
        return document, True

    def find_buy_lot_by_origin_trade_fact_id(self, origin_trade_fact_id):
        return self.buy_lots.find_one({"origin_trade_fact_id": origin_trade_fact_id})

    def find_buy_lot(self, buy_lot_id):
        return self.buy_lots.find_one({"buy_lot_id": buy_lot_id})

    def insert_buy_lot(self, document):
        self.buy_lots.insert_one(document)
        return document

    def replace_buy_lot(self, document):
        self.buy_lots.replace_one(
            {"buy_lot_id": document["buy_lot_id"]},
            document,
            upsert=True,
        )
        return document

    def find_position_entry(self, entry_id):
        return self.position_entries.find_one({"entry_id": entry_id})

    def replace_position_entry(self, document):
        self.position_entries.replace_one(
            {"entry_id": document["entry_id"]},
            document,
            upsert=True,
        )
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices.delete_many({"buy_lot_id": buy_lot_id})
        if slices:
            self.lot_slices.insert_many(slices)
        return slices

    def replace_entry_slices_for_entry(self, entry_id, slices):
        self.entry_slices.delete_many({"entry_id": entry_id})
        if slices:
            self.entry_slices.insert_many(slices)
        return slices

    def replace_open_slices(self, slices):
        if not slices:
            return slices
        slice_ids = [item["lot_slice_id"] for item in slices]
        self.lot_slices.delete_many({"lot_slice_id": {"$in": slice_ids}})
        self.lot_slices.insert_many(slices)
        return slices

    def insert_sell_allocations(self, allocations):
        if allocations:
            self.sell_allocations.insert_many(allocations)
        return allocations

    def insert_exit_allocations(self, allocations):
        if allocations:
            self.exit_allocations.insert_many(allocations)
        return allocations

    def insert_reconciliation_gap(self, document):
        self.reconciliation_gaps.insert_one(document)
        return document

    def insert_reconciliation_resolution(self, document):
        self.reconciliation_resolutions.insert_one(document)
        return document

    def insert_ingest_rejection(self, document):
        self.ingest_rejections.insert_one(document)
        return document

    def list_buy_lots(self, symbol=None, buy_lot_ids=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if buy_lot_ids is not None:
            query["buy_lot_id"] = {"$in": list(buy_lot_ids)}
        return list(self.buy_lots.find(query))

    def list_orders(
        self,
        symbol=None,
        states=None,
        missing_broker_only=False,
        request_ids=None,
        internal_order_ids=None,
    ):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if states is not None:
            query["state"] = {"$in": list(states)}
        if missing_broker_only:
            query["$or"] = [
                {"broker_order_id": None},
                {"broker_order_id": ""},
            ]
        if request_ids is not None:
            query["request_id"] = {"$in": list(request_ids)}
        if internal_order_ids is not None:
            query["internal_order_id"] = {"$in": list(internal_order_ids)}
        return list(self.orders.find(query))

    def list_broker_orders(
        self,
        *,
        symbol=None,
        states=None,
        broker_order_keys=None,
    ):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if states is not None:
            query["state"] = {"$in": list(states)}
        if broker_order_keys is not None:
            query["broker_order_key"] = {"$in": list(broker_order_keys)}
        return list(self.broker_orders.find(query))

    def list_order_events(self, *, internal_order_ids=None):
        query = {}
        if internal_order_ids is not None:
            query["internal_order_id"] = {"$in": list(internal_order_ids)}
        return list(self.order_events.find(query))

    def list_trade_facts(self, symbol=None, internal_order_ids=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if internal_order_ids is not None:
            query["internal_order_id"] = {"$in": list(internal_order_ids)}
        return list(self.trade_facts.find(query))

    def list_execution_fills(
        self,
        *,
        symbol=None,
        broker_order_keys=None,
        execution_fill_ids=None,
    ):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if broker_order_keys is not None:
            query["broker_order_key"] = {"$in": list(broker_order_keys)}
        if execution_fill_ids is not None:
            query["execution_fill_id"] = {"$in": list(execution_fill_ids)}
        return list(self.execution_fills.find(query))

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if entry_ids is not None:
            query["entry_id"] = {"$in": list(entry_ids)}
        if status is not None:
            query["status"] = status
        return list(self.position_entries.find(query))

    def list_open_slices(self, symbol=None, buy_lot_ids=None):
        query = {"remaining_quantity": {"$gt": 0}}
        if symbol is not None:
            query["symbol"] = symbol
        if buy_lot_ids is not None:
            query["buy_lot_id"] = {"$in": list(buy_lot_ids)}
        return list(self.lot_slices.find(query))

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        query = {"remaining_quantity": {"$gt": 0}}
        if symbol is not None:
            query["symbol"] = symbol
        if entry_ids is not None:
            query["entry_id"] = {"$in": list(entry_ids)}
        return list(self.entry_slices.find(query))

    def insert_external_candidate(self, document):
        self.external_candidates.insert_one(document)
        return document

    def list_external_candidates(self, state=None):
        query = {}
        if state is not None:
            query["state"] = state
        return list(self.external_candidates.find(query))

    def update_external_candidate(self, candidate_id, updates):
        self.external_candidates.update_one(
            {"candidate_id": candidate_id},
            {"$set": updates},
        )
        return self.external_candidates.find_one({"candidate_id": candidate_id})

    def update_reconciliation_gap(self, gap_id, updates):
        self.reconciliation_gaps.update_one(
            {"gap_id": gap_id},
            {"$set": updates},
        )
        return self.reconciliation_gaps.find_one({"gap_id": gap_id})

    def find_stoploss_binding(self, buy_lot_id):
        return self.stoploss_bindings.find_one({"buy_lot_id": buy_lot_id})

    def find_entry_stoploss_binding(self, entry_id):
        return self.entry_stoploss_bindings.find_one({"entry_id": entry_id})

    def upsert_stoploss_binding(self, document):
        self.stoploss_bindings.replace_one(
            {"buy_lot_id": document["buy_lot_id"]},
            document,
            upsert=True,
        )
        return self.find_stoploss_binding(document["buy_lot_id"])

    def upsert_entry_stoploss_binding(self, document):
        self.entry_stoploss_bindings.replace_one(
            {"entry_id": document["entry_id"]},
            document,
            upsert=True,
        )
        return self.find_entry_stoploss_binding(document["entry_id"])

    def list_stoploss_bindings(self, symbol=None, enabled=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if enabled is not None:
            query["enabled"] = bool(enabled)
        return list(self.stoploss_bindings.find(query))

    def list_entry_stoploss_bindings(self, symbol=None, enabled=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if enabled is not None:
            query["enabled"] = bool(enabled)
        return list(self.entry_stoploss_bindings.find(query))

    def list_exit_allocations(self, *, entry_ids=None):
        query = {}
        if entry_ids is not None:
            query["entry_id"] = {"$in": list(entry_ids)}
        return list(self.exit_allocations.find(query))

    def list_reconciliation_gaps(self, *, symbol=None, state=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if state is not None:
            query["state"] = state
        return list(self.reconciliation_gaps.find(query))

    def list_reconciliation_resolutions(self, *, gap_ids=None):
        query = {}
        if gap_ids is not None:
            query["gap_id"] = {"$in": list(gap_ids)}
        return list(self.reconciliation_resolutions.find(query))

    def list_ingest_rejections(self, *, symbol=None, reason_code=None):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if reason_code is not None:
            query["reason_code"] = reason_code
        return list(self.ingest_rejections.find(query))
