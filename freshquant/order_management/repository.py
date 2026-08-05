# -*- coding: utf-8 -*-

from decimal import Decimal, InvalidOperation

from pymongo.errors import DuplicateKeyError

from freshquant.order_management.allocation_integrity import (
    find_exit_allocation_integrity_errors,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    identity_conflicts,
    normalize_account_id,
    normalize_identifier,
    normalize_side,
    normalize_symbol,
    normalize_trading_day,
)
from freshquant.order_management.db import DBOrderManagement

_EXECUTION_IMMUTABLE_FIELDS = (
    "execution_identity",
    "broker_trade_id",
    "broker_order_key",
    "internal_order_id",
    "account_id",
    "trading_day",
    "symbol",
    "side",
    "quantity",
    "price",
    "trade_time",
)


class OrderManagementRepository:
    def __init__(self, database=None):
        self.database = database if database is not None else DBOrderManagement
        self._ensure_canonical_indexes()

    def _ensure_canonical_indexes(self):
        for collection, field, name in (
            (
                self.broker_orders,
                "broker_order_key",
                "uq_om_broker_orders_broker_order_key",
            ),
            (
                self.trade_facts,
                "execution_identity",
                "uq_om_trade_facts_execution_identity",
            ),
            (
                self.execution_fills,
                "execution_identity",
                "uq_om_execution_fills_execution_identity",
            ),
            (
                self.position_entries,
                "entry_id",
                "uq_om_position_entries_entry_id",
            ),
            (
                self.entry_slices,
                "entry_slice_id",
                "uq_om_entry_slices_entry_slice_id",
            ),
            (
                self.exit_allocations,
                "allocation_id",
                "uq_om_exit_allocations_allocation_id",
            ),
        ):
            create_index = getattr(collection, "create_index", None)
            if not callable(create_index):
                continue
            create_index(
                [(field, 1)],
                unique=True,
                partialFilterExpression={field: {"$type": "string"}},
                name=name,
            )

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
        payload = _without_mongo_id(document)
        existing = self._find_canonical_broker_order(document, query=query)
        if existing is not None:
            _assert_broker_order_identity_consistent(existing, document)
        try:
            result = self.broker_orders.update_one(
                query,
                {"$set": payload},
                upsert=True,
            )
        except DuplicateKeyError:
            existing = self._find_canonical_broker_order(document, query=query)
            if existing is None:
                raise
            _assert_broker_order_identity_consistent(existing, document)
            self.broker_orders.update_one(
                {"broker_order_key": existing["broker_order_key"]},
                {"$set": payload},
                upsert=False,
            )
            return self.find_broker_order(existing["broker_order_key"]), False
        saved = self._find_canonical_broker_order(document, query=query)
        return saved, result.upserted_id is not None

    def move_broker_order_key(self, old_key, new_key, document):
        old_key = normalize_identifier(old_key)
        new_key = normalize_identifier(new_key)
        if new_key is None:
            raise ValueError("new broker_order_key is required")
        payload = _without_mongo_id({**document, "broker_order_key": new_key})
        if old_key is None or old_key == new_key:
            saved, _created = self.upsert_broker_order(
                payload,
                unique_keys=["broker_order_key"],
            )
            return saved

        target = self.find_broker_order(new_key)
        if target is not None:
            return self._merge_broker_order_target(
                old_key=old_key,
                new_key=new_key,
                target=target,
                document=payload,
            )

        try:
            result = self.broker_orders.update_one(
                {"broker_order_key": old_key},
                {"$set": payload},
                upsert=False,
            )
        except DuplicateKeyError:
            target = self.find_broker_order(new_key)
            if target is None:
                raise
            return self._merge_broker_order_target(
                old_key=old_key,
                new_key=new_key,
                target=target,
                document=payload,
            )
        if result.matched_count:
            return self.find_broker_order(new_key)

        saved, _created = self.upsert_broker_order(
            payload,
            unique_keys=["broker_order_key"],
        )
        return saved

    def _find_canonical_broker_order(self, document, *, query):
        broker_order_key = normalize_identifier(document.get("broker_order_key"))
        if broker_order_key is not None:
            canonical = self.find_broker_order(broker_order_key)
            if canonical is not None:
                return canonical
        return self.broker_orders.find_one(query)

    def _merge_broker_order_target(self, *, old_key, new_key, target, document):
        placeholder = self.find_broker_order(old_key)
        if placeholder is not None:
            _assert_broker_order_identity_consistent(target, placeholder)
        _assert_broker_order_identity_consistent(target, document)
        merged = {
            **_without_mongo_id(placeholder or {}),
            **_without_mongo_id(target),
            **_without_mongo_id(document),
            "broker_order_key": new_key,
        }
        self.broker_orders.update_one(
            {"broker_order_key": new_key},
            {"$set": merged},
            upsert=False,
        )
        self.broker_orders.delete_one({"broker_order_key": old_key})
        return self.find_broker_order(new_key)

    def insert_order_event(self, document):
        self.order_events.insert_one(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        return self._upsert_execution_document(
            collection=self.trade_facts,
            document=document,
            unique_keys=unique_keys,
        )

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
        return self._upsert_execution_document(
            collection=self.execution_fills,
            document=document,
            unique_keys=unique_keys,
        )

    def _upsert_execution_document(self, *, collection, document, unique_keys):
        query = {key: document[key] for key in unique_keys}
        payload = _without_mongo_id(document)
        try:
            result = collection.update_one(
                query,
                {"$setOnInsert": payload},
                upsert=True,
            )
        except DuplicateKeyError:
            existing = _find_canonical_execution_document(
                collection,
                document,
                query=query,
            )
            if existing is None:
                raise
            _assert_execution_identity_consistent(existing, document)
            return existing, False

        saved = _find_canonical_execution_document(
            collection,
            document,
            query=query,
        )
        if result.upserted_id is None and saved is not None:
            _assert_execution_identity_consistent(saved, document)
        return saved, result.upserted_id is not None

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

    def upsert_entry_slices(self, slices):
        for document in list(slices or []):
            self.entry_slices.replace_one(
                {"entry_slice_id": document["entry_slice_id"]},
                document,
                upsert=True,
            )
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

    def list_entry_slices(
        self,
        *,
        symbol=None,
        entry_ids=None,
        entry_slice_ids=None,
    ):
        query = {}
        if symbol is not None:
            query["symbol"] = symbol
        if entry_ids is not None:
            query["entry_id"] = {"$in": list(entry_ids)}
        if entry_slice_ids is not None:
            query["entry_slice_id"] = {"$in": list(entry_slice_ids)}
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

    def find_exit_allocation_reference_errors(self, *, entry_ids=None):
        allocations = self.list_exit_allocations(entry_ids=entry_ids)
        if entry_ids is None:
            entries = self.list_position_entries()
            slices = self.list_entry_slices()
        else:
            scope_entry_ids = {
                normalize_identifier(item) for item in list(entry_ids or [])
            } - {None}
            scope_entry_ids.update(
                normalize_identifier(item.get("entry_id")) for item in allocations
            )
            scope_entry_ids.discard(None)
            entries = self.list_position_entries(entry_ids=scope_entry_ids)
            referenced_slice_ids = {
                normalize_identifier(item.get("entry_slice_id")) for item in allocations
            } - {None}
            scoped_slices = self.list_entry_slices(entry_ids=scope_entry_ids)
            referenced_slices = self.list_entry_slices(
                entry_slice_ids=referenced_slice_ids
            )
            slices = _deduplicate_documents(
                [*scoped_slices, *referenced_slices],
                identity_field="entry_slice_id",
            )
        return find_exit_allocation_integrity_errors(
            position_entries=entries,
            entry_slices=slices,
            exit_allocations=allocations,
        )

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


def _without_mongo_id(document):
    return {key: value for key, value in dict(document or {}).items() if key != "_id"}


def _assert_broker_order_identity_consistent(existing, incoming):
    conflicts = identity_conflicts(existing, incoming)
    if conflicts:
        raise BrokerIdentityConflict(
            "broker order conflicts with canonical identity: "
            + ", ".join(sorted(conflicts))
        )


def _find_canonical_execution_document(collection, document, *, query):
    execution_identity = normalize_identifier(document.get("execution_identity"))
    if execution_identity is not None:
        canonical = collection.find_one({"execution_identity": execution_identity})
        if canonical is not None:
            return canonical
    return collection.find_one(query)


def _assert_execution_identity_consistent(existing, incoming):
    conflicts = {}
    for field in _EXECUTION_IMMUTABLE_FIELDS:
        left = _normalize_execution_field(field, existing.get(field))
        right = _normalize_execution_field(field, incoming.get(field))
        if left is not None and right is not None and left != right:
            conflicts[field] = (left, right)
    if conflicts:
        raise BrokerIdentityConflict(
            "execution replay conflicts with canonical identity: "
            + ", ".join(sorted(conflicts))
        )


def _normalize_execution_field(field, value):
    if field == "account_id":
        return normalize_account_id(value)
    if field == "trading_day":
        return normalize_trading_day(value)
    if field == "symbol":
        return normalize_symbol(value)
    if field == "side":
        return normalize_side(value)
    if field == "quantity":
        try:
            normalized = int(value)
            return normalized if normalized == float(value) else value
        except (TypeError, ValueError, OverflowError):
            return value
    if field == "price":
        if value is None:
            return None
        try:
            return Decimal(str(value)).normalize()
        except (InvalidOperation, ValueError):
            return value
    if field == "trade_time":
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return normalize_identifier(value)
    return normalize_identifier(value)


def _deduplicate_documents(documents, *, identity_field):
    result = []
    seen = set()
    for document in documents:
        identity = normalize_identifier(document.get(identity_field))
        marker = identity if identity is not None else id(document)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(document)
    return result
