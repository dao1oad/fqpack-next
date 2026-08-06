# -*- coding: utf-8 -*-

from pymongo.errors import DuplicateKeyError

from freshquant.order_management.broker_correlation import (
    build_broker_correlation_token,
    normalize_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    BrokerIdentityError,
    build_broker_only_internal_order_id,
    identity_conflicts,
    normalize_identifier,
    resolve_trading_day,
)
from freshquant.order_management.db import DBOrderManagement

_BROKER_ORDER_OWNER_FIELDS = (
    "internal_order_id",
    "request_id",
    "broker_correlation_token",
)
_BROKER_ORDER_IDENTITY_FIELDS = (
    "broker_order_key",
    "account_id",
    "trading_day",
    "order_sysid",
    "broker_order_id",
    "symbol",
    "side",
)
_BROKER_ORDER_CLAIM_FIELDS = (
    *_BROKER_ORDER_OWNER_FIELDS,
    *_BROKER_ORDER_IDENTITY_FIELDS,
    "source_type",
)
_BROKER_ORDER_AGGREGATE_FIELDS = (
    "filled_quantity",
    "fill_count",
    "avg_filled_price",
    "fill_set_fingerprint",
    "aggregate_revision",
    "first_fill_time",
    "last_fill_time",
)
_BROKER_ORDER_CLAIM_ATTEMPTS = 16
_BROKER_ORDER_MOVE_ATTEMPTS = 16
_MISSING = object()


class OrderManagementRepository:
    def __init__(self, database=None):
        self.database = database if database is not None else DBOrderManagement
        self._canonical_indexes_ready = False

    def _ensure_canonical_indexes(self):
        if self._canonical_indexes_ready:
            return
        for collection, field, name in (
            (self.orders, "internal_order_id", "uq_om_orders_internal_order_id"),
            (
                self.orders,
                "broker_correlation_token",
                "uq_om_orders_broker_correlation_token",
            ),
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
        ):
            create_index = getattr(collection, "create_index", None)
            if callable(create_index):
                create_index(
                    [(field, 1)],
                    unique=True,
                    partialFilterExpression={field: {"$type": "string"}},
                    name=name,
                )
        self._canonical_indexes_ready = True

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
        self._ensure_canonical_indexes()
        payload = _without_mongo_id(document)
        internal_order_id = normalize_identifier(payload.get("internal_order_id"))
        if internal_order_id is None:
            raise BrokerIdentityConflict("internal_order_id is required")
        payload["internal_order_id"] = internal_order_id
        try:
            self.orders.update_one(
                {"internal_order_id": internal_order_id},
                {"$setOnInsert": payload},
                upsert=True,
            )
        except DuplicateKeyError:
            pass
        saved = self.find_order(internal_order_id)
        if saved is None:
            raise BrokerIdentityConflict("canonical order insert did not persist")
        _assert_broker_order_identity_consistent(saved, payload)
        for field in ("request_id", "broker_correlation_token"):
            if (
                normalize_identifier(saved.get(field)) is not None
                and normalize_identifier(payload.get(field)) is not None
                and normalize_identifier(saved.get(field))
                != normalize_identifier(payload.get(field))
            ):
                raise BrokerIdentityConflict(
                    f"order conflicts with canonical {field} ownership"
                )
        return saved

    def upsert_broker_order(self, document, unique_keys):
        if list(unique_keys or []) != ["broker_order_key"]:
            raise BrokerIdentityConflict(
                "broker order upsert requires broker_order_key identity"
            )
        return self.claim_broker_order_owner(document)

    def claim_broker_order_owner(self, document):
        self._ensure_canonical_indexes()
        payload = _without_mongo_id(document)
        broker_order_key = normalize_identifier(payload.get("broker_order_key"))
        if broker_order_key is None:
            raise BrokerIdentityConflict("broker_order_key is required")
        payload["broker_order_key"] = broker_order_key
        incoming_owner_kind = _classify_broker_order_owner(payload)
        if incoming_owner_kind == "real":
            self._assert_canonical_real_broker_order_owner(payload)

        for _attempt in range(_BROKER_ORDER_CLAIM_ATTEMPTS):
            existing = self.find_broker_order(broker_order_key)
            if existing is None:
                if incoming_owner_kind == "real_partial":
                    raise BrokerIdentityConflict(
                        "new broker order requires complete canonical owner"
                    )
                try:
                    result = self.broker_orders.update_one(
                        {"broker_order_key": broker_order_key},
                        {"$setOnInsert": payload},
                        upsert=True,
                    )
                except DuplicateKeyError:
                    continue
                saved = self.find_broker_order(broker_order_key)
                if saved is None:
                    continue
                if result.upserted_id is not None:
                    return saved, True
                existing = saved

            self._assert_broker_order_owner_claim_allowed(
                existing,
                payload,
                incoming_owner_kind=incoming_owner_kind,
            )
            next_payload = _merge_broker_order_claim(existing, payload)
            if _without_mongo_id(existing) == next_payload:
                return existing, False
            result = self.broker_orders.replace_one(
                _exact_document_selector(existing, identity_field="broker_order_key"),
                next_payload,
                upsert=False,
            )
            if not result.matched_count:
                continue
            saved = self.find_broker_order(broker_order_key)
            if saved is not None:
                return saved, False
        raise BrokerIdentityConflict(
            "broker order owner claim could not converge after concurrent updates"
        )

    def _assert_canonical_real_broker_order_owner(self, incoming):
        internal_order = self.find_order(
            normalize_identifier(incoming.get("internal_order_id"))
        )
        if internal_order is None:
            raise BrokerIdentityConflict(
                "canonical broker order owner requires an existing internal order"
            )
        if str(internal_order.get("source_type") or "").lower() == "broker_only":
            raise BrokerIdentityConflict(
                "canonical broker order owner cannot reference a broker-only order"
            )
        _assert_broker_order_identity_consistent(internal_order, incoming)
        for field in ("request_id", "broker_correlation_token"):
            if normalize_identifier(internal_order.get(field)) != normalize_identifier(
                incoming.get(field)
            ):
                raise BrokerIdentityConflict(
                    f"canonical broker order owner conflicts with internal {field}"
                )

    def _assert_broker_order_owner_claim_allowed(
        self, existing, incoming, *, incoming_owner_kind
    ):
        _assert_broker_order_owner_transition(existing, incoming)
        if incoming_owner_kind == "real_partial":
            if not _is_complete_real_broker_order_owner(existing):
                raise BrokerIdentityConflict(
                    "partial broker order owner requires an existing canonical owner"
                )
        elif incoming_owner_kind == "real":
            self._assert_canonical_real_broker_order_owner(incoming)
        if not _broker_order_internal_owner_changes(existing, incoming):
            return
        if not _is_strict_broker_only_owner(existing):
            return
        if incoming_owner_kind != "real":
            raise BrokerIdentityConflict(
                "broker-only owner promotion requires complete canonical owner"
            )
        if (
            existing.get("execution_fence") is True
            or int(existing.get("fill_count") or 0) > 0
        ):
            raise BrokerIdentityConflict(
                "broker-only owner with executions requires targeted repair"
            )

    def update_broker_order_fields(self, broker_order_key, updates):
        self._ensure_canonical_indexes()
        normalized_key = normalize_identifier(broker_order_key)
        current = self.find_broker_order(normalized_key)
        if current is None:
            return None
        payload = _without_mongo_id(updates)
        if any(field in payload for field in _BROKER_ORDER_AGGREGATE_FIELDS):
            raise BrokerIdentityConflict(
                "broker aggregate fields require compare-and-set"
            )
        candidate = {**_without_mongo_id(current), **payload}
        _assert_broker_order_identity_consistent(current, candidate)
        _assert_broker_order_owner_unchanged(current, candidate)
        update_fields = {
            key: value
            for key, value in payload.items()
            if key not in _BROKER_ORDER_OWNER_FIELDS
            and key != "broker_order_key"
            and current.get(key) != value
        }
        if not update_fields:
            return current
        selector = {"broker_order_key": normalized_key}
        for field in (*_BROKER_ORDER_OWNER_FIELDS, *_BROKER_ORDER_IDENTITY_FIELDS):
            if field != "broker_order_key":
                selector[field] = current.get(field)
        result = self.broker_orders.update_one(selector, {"$set": update_fields})
        saved = self.find_broker_order(normalized_key)
        if result.matched_count or (
            saved is not None
            and all(saved.get(key) == value for key, value in update_fields.items())
        ):
            return saved
        raise BrokerIdentityConflict("broker order field update lost canonical owner")

    def fence_broker_order_execution(self, document):
        self._ensure_canonical_indexes()
        broker_order_key = normalize_identifier(document.get("broker_order_key"))
        internal_order_id = normalize_identifier(document.get("internal_order_id"))
        if broker_order_key is None or internal_order_id is None:
            raise BrokerIdentityConflict(
                "execution fence requires broker_order_key and internal_order_id"
            )
        for _attempt in range(_BROKER_ORDER_CLAIM_ATTEMPTS):
            current = self.find_broker_order(broker_order_key)
            if current is None:
                raise BrokerIdentityConflict(
                    "execution fence requires an existing broker order"
                )
            _assert_broker_order_identity_consistent(current, document)
            if (
                normalize_identifier(current.get("internal_order_id"))
                != internal_order_id
            ):
                raise BrokerIdentityConflict(
                    "broker order execution owner changed; targeted repair required"
                )
            if current.get("execution_fence") is True:
                return current
            result = self.broker_orders.update_one(
                _exact_document_selector(current, identity_field="broker_order_key"),
                {"$set": {"execution_fence": True}},
            )
            if result.matched_count:
                return self.find_broker_order(broker_order_key)
        raise BrokerIdentityConflict(
            "broker order execution fence could not converge after concurrent updates"
        )

    def compare_and_set_broker_order(self, *, before, after):
        self._ensure_canonical_indexes()
        before_payload = _without_mongo_id(before)
        after_payload = _without_mongo_id(after)
        broker_order_key = normalize_identifier(
            after_payload.get("broker_order_key")
            or before_payload.get("broker_order_key")
        )
        if broker_order_key is None:
            raise BrokerIdentityConflict("broker_order_key is required")
        before_payload["broker_order_key"] = broker_order_key
        after_payload["broker_order_key"] = broker_order_key
        _assert_broker_order_identity_consistent(before_payload, after_payload)
        _assert_broker_order_owner_unchanged(before_payload, after_payload)
        result = self.broker_orders.replace_one(
            _exact_document_selector(before_payload, identity_field="broker_order_key"),
            after_payload,
        )
        if result.matched_count:
            return self.find_broker_order(broker_order_key)
        current = self.find_broker_order(broker_order_key)
        return current if _without_mongo_id(current) == after_payload else None

    def move_broker_order_key(self, old_key, new_key, document):
        self._ensure_canonical_indexes()
        old_key = normalize_identifier(old_key)
        new_key = normalize_identifier(new_key)
        if new_key is None:
            raise BrokerIdentityConflict("new broker_order_key is required")
        payload = _without_mongo_id({**document, "broker_order_key": new_key})
        if old_key is None or old_key == new_key:
            return self.claim_broker_order_owner(payload)[0]
        initial_source = self.find_broker_order(old_key)
        for _attempt in range(_BROKER_ORDER_MOVE_ATTEMPTS):
            source = self.find_broker_order(old_key)
            if source is None:
                return self.claim_broker_order_owner(payload)[0]
            if initial_source is None:
                initial_source = source
            _assert_broker_order_identity_consistent(source, payload)
            _assert_broker_order_owner_transition(source, payload)
            _assert_broker_order_owner_unchanged(initial_source, source)
            candidate = _merge_broker_order_move_candidate(
                initial_source=initial_source,
                current_source=source,
                incoming=payload,
                new_key=new_key,
            )
            self.claim_broker_order_owner(candidate)
            saved = self._converge_broker_order_move_target(new_key, candidate)
            result = self.broker_orders.delete_one(
                _exact_document_selector(source, identity_field="broker_order_key")
            )
            if result.deleted_count:
                return saved
        raise BrokerIdentityConflict(
            "broker order key move could not converge after concurrent source updates"
        )

    def _converge_broker_order_move_target(self, broker_order_key, candidate):
        for _attempt in range(_BROKER_ORDER_MOVE_ATTEMPTS):
            current = self.find_broker_order(broker_order_key)
            if current is None:
                return self.claim_broker_order_owner(candidate)[0]
            merged = _merge_broker_order_move_target(current, candidate)
            if _without_mongo_id(current) == merged:
                return current
            saved = self.compare_and_set_broker_order(before=current, after=merged)
            if saved is not None:
                return saved
        raise BrokerIdentityConflict(
            "broker order key move target could not converge after concurrent updates"
        )

    def insert_order_event(self, document):
        self.order_events.insert_one(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        if list(unique_keys or []) == ["execution_identity"]:
            return self._upsert_execution_record(
                self.trade_facts,
                document,
                identity_field="execution_identity",
            )
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

    def find_order_by_broker_correlation_token(self, broker_correlation_token):
        token = normalize_broker_correlation_token(broker_correlation_token)
        if token is None:
            return None
        return self.orders.find_one({"broker_correlation_token": token})

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
        if list(unique_keys or []) == ["execution_identity"]:
            return self._upsert_execution_record(
                self.execution_fills,
                document,
                identity_field="execution_identity",
            )
        query = {key: document[key] for key in unique_keys}
        existing = self.execution_fills.find_one(query)
        if existing is not None:
            return existing, False
        self.execution_fills.insert_one(document)
        return document, True

    def _upsert_execution_record(self, collection, document, *, identity_field):
        self._ensure_canonical_indexes()
        payload = _without_mongo_id(document)
        identity = normalize_identifier(payload.get(identity_field))
        if identity is None:
            raise BrokerIdentityConflict(f"{identity_field} is required")
        payload[identity_field] = identity
        try:
            result = collection.update_one(
                {identity_field: identity},
                {"$setOnInsert": payload},
                upsert=True,
            )
        except DuplicateKeyError:
            result = None
        saved = collection.find_one({identity_field: identity})
        if saved is None:
            raise BrokerIdentityConflict(f"{identity_field} insert did not persist")
        return saved, bool(result is not None and result.upserted_id is not None)

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


def _without_mongo_id(document):
    return {key: value for key, value in dict(document or {}).items() if key != "_id"}


def _exact_document_selector(document, *, identity_field):
    payload = _without_mongo_id(document)
    return {
        identity_field: payload[identity_field],
        "$expr": {
            "$eq": [
                {"$unsetField": {"field": "_id", "input": "$$ROOT"}},
                payload,
            ]
        },
    }


def _assert_broker_order_identity_consistent(existing, incoming):
    conflicts = identity_conflicts(existing, incoming)
    if conflicts:
        raise BrokerIdentityConflict(
            "broker order conflicts with canonical identity: "
            + ", ".join(sorted(conflicts))
        )


def _broker_order_owner(document):
    return {
        field: normalize_identifier((document or {}).get(field))
        for field in _BROKER_ORDER_OWNER_FIELDS
    }


def _assert_broker_order_owner_transition(existing, incoming):
    existing_owner = _broker_order_owner(existing)
    incoming_owner = _broker_order_owner(incoming)
    if (
        existing_owner["internal_order_id"] is not None
        and incoming_owner["internal_order_id"] is not None
        and existing_owner["internal_order_id"] != incoming_owner["internal_order_id"]
        and not (
            _is_strict_broker_only_owner(existing)
            and not _is_strict_broker_only_owner(incoming)
        )
    ):
        raise BrokerIdentityConflict(
            "broker order owner conflicts with canonical internal_order_id"
        )
    for field in ("request_id", "broker_correlation_token"):
        if (
            existing_owner[field] is not None
            and incoming_owner[field] is not None
            and existing_owner[field] != incoming_owner[field]
        ):
            raise BrokerIdentityConflict(
                f"broker order owner conflicts with canonical {field}"
            )


def _assert_broker_order_owner_unchanged(existing, incoming):
    if _broker_order_owner(existing) != _broker_order_owner(incoming):
        raise BrokerIdentityConflict(
            "broker order owner cannot change through aggregate compare-and-set"
        )


def _classify_broker_order_owner(document):
    owner = _broker_order_owner(document)
    internal_order_id = owner["internal_order_id"]
    request_id = owner["request_id"]
    raw_token = normalize_identifier((document or {}).get("broker_correlation_token"))
    token = normalize_broker_correlation_token(raw_token)
    if raw_token is not None and token is None:
        raise BrokerIdentityConflict(
            "broker order owner correlation token is malformed"
        )
    if internal_order_id is None:
        if request_id is not None or raw_token is not None:
            raise BrokerIdentityConflict(
                "broker order owner request/token requires internal_order_id"
            )
        return "empty"
    if str((document or {}).get("source_type") or "").lower() == "broker_only":
        if request_id is not None or raw_token is not None:
            raise BrokerIdentityConflict(
                "broker-only owner cannot carry request or correlation ownership"
            )
        if not _is_strict_broker_only_owner(document):
            raise BrokerIdentityConflict(
                "broker-only owner identity cannot be proven; targeted repair required"
            )
        return "broker_only"
    if token is not None and token != build_broker_correlation_token(internal_order_id):
        raise BrokerIdentityConflict(
            "broker order owner correlation token conflicts with internal_order_id"
        )
    if request_id is None or token is None:
        return "real_partial"
    return "real"


def _is_complete_real_broker_order_owner(document):
    try:
        return _classify_broker_order_owner(document) == "real"
    except BrokerIdentityConflict:
        return False


def _broker_order_internal_owner_changes(existing, incoming):
    return (
        normalize_identifier((existing or {}).get("internal_order_id")) is not None
        and normalize_identifier((incoming or {}).get("internal_order_id")) is not None
        and normalize_identifier((existing or {}).get("internal_order_id"))
        != normalize_identifier((incoming or {}).get("internal_order_id"))
    )


def _is_strict_broker_only_owner(document):
    if str((document or {}).get("source_type") or "").lower() != "broker_only":
        return False
    owner = _broker_order_owner(document)
    if (
        owner["internal_order_id"] is None
        or owner["request_id"] is not None
        or owner["broker_correlation_token"] is not None
    ):
        return False
    expected_ids = []
    identity = {
        "account_id": (document or {}).get("account_id"),
        "order_sysid": (document or {}).get("order_sysid"),
        "trading_day": resolve_trading_day(document or {}),
        "symbol": (document or {}).get("symbol"),
        "side": (document or {}).get("side"),
        "broker_order_id": (document or {}).get("broker_order_id"),
    }
    for order_sysid in (identity["order_sysid"], None):
        try:
            expected_ids.append(
                build_broker_only_internal_order_id(
                    account_id=identity["account_id"],
                    order_sysid=order_sysid,
                    trading_day=identity["trading_day"],
                    symbol=identity["symbol"],
                    side=identity["side"],
                    broker_order_id=identity["broker_order_id"],
                )
            )
        except BrokerIdentityError:
            continue
    return owner["internal_order_id"] in set(expected_ids)


def _merge_broker_order_claim(existing, incoming):
    _assert_broker_order_identity_consistent(existing, incoming)
    _assert_broker_order_owner_transition(existing, incoming)
    merged = _without_mongo_id(existing)
    owner_changes = _broker_order_internal_owner_changes(existing, incoming)
    for field in _BROKER_ORDER_CLAIM_FIELDS:
        if field not in incoming:
            continue
        value = incoming.get(field)
        if field == "source_type":
            if owner_changes or merged.get(field) in (None, ""):
                merged[field] = value
            continue
        if value is None and merged.get(field) is not None:
            continue
        merged[field] = value
    return merged


def _merge_broker_order_move_candidate(
    *, initial_source, current_source, incoming, new_key
):
    initial_payload = _without_mongo_id(initial_source)
    current_payload = _without_mongo_id(current_source)
    merged = {
        **initial_payload,
        **_without_mongo_id(incoming),
        "broker_order_key": new_key,
    }
    for field in set(initial_payload) | set(current_payload):
        if field == "broker_order_key":
            continue
        initial_value = initial_payload.get(field, _MISSING)
        current_value = current_payload.get(field, _MISSING)
        if current_value == initial_value:
            continue
        if current_value is _MISSING:
            merged.pop(field, None)
        else:
            merged[field] = current_value
    _preserve_newer_broker_order_aggregate(merged, current_payload)
    if current_payload.get("execution_fence") is True:
        merged["execution_fence"] = True
    return merged


def _merge_broker_order_move_target(existing, candidate):
    _assert_broker_order_identity_consistent(existing, candidate)
    _assert_broker_order_owner_unchanged(existing, candidate)
    merged = {**_without_mongo_id(existing), **_without_mongo_id(candidate)}
    _preserve_newer_broker_order_aggregate(merged, existing)
    if existing.get("execution_fence") is True:
        merged["execution_fence"] = True
    return merged


def _preserve_newer_broker_order_aggregate(merged, source):
    source_revision = _broker_order_aggregate_revision(source)
    merged_revision = _broker_order_aggregate_revision(merged)
    if source_revision <= merged_revision:
        return
    for field in _BROKER_ORDER_AGGREGATE_FIELDS:
        if field in source:
            merged[field] = source.get(field)
        else:
            merged.pop(field, None)
    if "state" in source:
        merged["state"] = source.get("state")


def _broker_order_aggregate_revision(document):
    try:
        return int((document or {}).get("aggregate_revision") or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BrokerIdentityConflict("broker aggregate revision is invalid") from exc
