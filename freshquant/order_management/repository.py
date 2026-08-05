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
    resolve_trading_day,
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

_CANONICAL_EXECUTION_RECORD_VERSION = 2


class OrderManagementRepository:
    def __init__(self, database=None):
        self.database = database if database is not None else DBOrderManagement
        self._canonical_indexes_ready = False

    def _ensure_canonical_indexes(self):
        if self._canonical_indexes_ready:
            return
        for collection, field, name in (
            (
                self.orders,
                "internal_order_id",
                "uq_om_orders_internal_order_id",
            ),
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
                self.sell_allocations,
                "allocation_id",
                "uq_om_sell_allocations_allocation_id",
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
        conflicts = identity_conflicts(saved, payload)
        if conflicts:
            raise BrokerIdentityConflict(
                "order conflicts with canonical identity: "
                + ", ".join(sorted(conflicts))
            )
        saved_request_id = normalize_identifier(saved.get("request_id"))
        incoming_request_id = normalize_identifier(payload.get("request_id"))
        if (
            saved_request_id is not None
            and incoming_request_id is not None
            and saved_request_id != incoming_request_id
        ):
            raise BrokerIdentityConflict(
                "order conflicts with canonical request ownership"
            )
        saved_correlation_token = normalize_identifier(
            saved.get("broker_correlation_token")
        )
        incoming_correlation_token = normalize_identifier(
            payload.get("broker_correlation_token")
        )
        if (
            saved_correlation_token is not None
            and incoming_correlation_token is not None
            and saved_correlation_token != incoming_correlation_token
        ):
            raise BrokerIdentityConflict(
                "order conflicts with canonical broker correlation ownership"
            )
        return saved

    def upsert_broker_order(self, document, unique_keys):
        self._ensure_canonical_indexes()
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

    def update_broker_order_fields(self, broker_order_key, updates):
        self._ensure_canonical_indexes()
        normalized_key = normalize_identifier(broker_order_key)
        if normalized_key is None:
            raise BrokerIdentityConflict("broker_order_key is required")
        current = self.find_broker_order(normalized_key)
        if current is None:
            return None
        payload = _without_mongo_id(updates)
        _assert_broker_order_identity_consistent(current, {**current, **payload})
        self.broker_orders.update_one(
            {"broker_order_key": normalized_key},
            {"$set": payload},
            upsert=False,
        )
        return self.find_broker_order(normalized_key)

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
        result = self.broker_orders.replace_one(
            _exact_projection_selector(
                before_payload,
                identity_field="broker_order_key",
            ),
            after_payload,
            upsert=False,
        )
        if result.matched_count:
            return self.find_broker_order(broker_order_key)
        current = self.find_broker_order(broker_order_key)
        if current is not None and _without_mongo_id(current) == after_payload:
            return current
        return None

    def move_broker_order_key(self, old_key, new_key, document):
        self._ensure_canonical_indexes()
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
        self.preflight_execution_replay(document)
        return self._upsert_execution_document(
            collection=self.trade_facts,
            document=document,
            unique_keys=unique_keys,
            document_id_field="trade_fact_id",
        )

    def preflight_execution_replay(self, document):
        execution_identity = normalize_identifier(document.get("execution_identity"))
        if execution_identity is None:
            return
        states = []
        for label, collection in (
            ("trade_fact", self.trade_facts),
            ("execution_fill", self.execution_fills),
        ):
            canonical = (
                collection.find_one({"execution_identity": execution_identity})
                if execution_identity is not None
                else None
            )
            if canonical is not None:
                _assert_execution_identity_consistent(canonical, document)
            legacy = _find_legacy_execution_candidate(
                collection,
                document,
                repository=self,
            )
            if canonical is not None and legacy is not None:
                raise BrokerIdentityConflict(
                    f"execution replay has duplicate canonical and legacy {label} rows"
                )
            states.append(
                {
                    "label": label,
                    "canonical": canonical,
                    "legacy": legacy,
                }
            )
        _assert_execution_replay_pair_state(states)

    def find_order(self, internal_order_id):
        return self.orders.find_one({"internal_order_id": internal_order_id})

    def find_broker_order(self, broker_order_key):
        return self.broker_orders.find_one({"broker_order_key": broker_order_key})

    def find_broker_order_by_broker_order_id(self, broker_order_id):
        return self.broker_orders.find_one({"broker_order_id": str(broker_order_id)})

    def list_broker_orders_by_broker_order_id(self, broker_order_id):
        if broker_order_id in (None, "", "None"):
            return []
        return list(self.broker_orders.find({"broker_order_id": str(broker_order_id)}))

    def find_order_by_request_id(self, request_id):
        return self.orders.find_one({"request_id": request_id})

    def find_order_by_broker_correlation_token(self, token):
        normalized = normalize_identifier(token)
        if normalized is None:
            return None
        return self.orders.find_one({"broker_correlation_token": normalized})

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
        self.preflight_execution_replay(document)
        return self._upsert_execution_document(
            collection=self.execution_fills,
            document=document,
            unique_keys=unique_keys,
            document_id_field="execution_fill_id",
            legacy_projection_status_resolver=(
                lambda incoming: _resolve_legacy_execution_projection_status(
                    self,
                    incoming,
                )
            ),
        )

    def _upsert_execution_document(
        self,
        *,
        collection,
        document,
        unique_keys,
        document_id_field,
        legacy_projection_status=None,
        legacy_projection_status_resolver=None,
    ):
        self._ensure_canonical_indexes()
        query = {key: document[key] for key in unique_keys}
        payload = _without_mongo_id(document)
        if normalize_identifier(payload.get("execution_identity")) is not None:
            payload.setdefault(
                "execution_record_version", _CANONICAL_EXECUTION_RECORD_VERSION
            )
        existing = _find_canonical_execution_document(
            collection,
            document,
            query=query,
        )
        if existing is not None:
            _assert_execution_identity_consistent(existing, document)
            return existing, False

        legacy = _find_legacy_execution_candidate(
            collection,
            document,
            repository=self,
        )
        if legacy is not None:
            resolved_legacy_projection_status = legacy_projection_status
            if callable(legacy_projection_status_resolver):
                resolved_legacy_projection_status = legacy_projection_status_resolver(
                    document
                )
            saved = _migrate_legacy_execution_candidate(
                collection,
                legacy=legacy,
                incoming=document,
                document_id_field=document_id_field,
                legacy_projection_status=resolved_legacy_projection_status,
            )
            _assert_execution_identity_consistent(saved, document)
            return saved, False

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

    def prepare_execution_projection(self, execution_identity, projection_plan):
        normalized_identity = normalize_identifier(execution_identity)
        if normalized_identity is None:
            raise BrokerIdentityConflict("execution projection requires identity")
        group_progress = _initial_projection_group_progress(projection_plan)
        self.execution_fills.update_one(
            {
                "execution_identity": normalized_identity,
                "projection_status": "PENDING",
                "projection_plan": None,
            },
            {
                "$set": {
                    "projection_plan": projection_plan,
                    "projection_group_progress": group_progress,
                }
            },
        )
        saved = self.execution_fills.find_one(
            {"execution_identity": normalized_identity}
        )
        if saved is None:
            raise BrokerIdentityConflict("execution projection fill is missing")
        status = normalize_identifier(saved.get("projection_status"))
        if status not in {"PENDING", "APPLIED"}:
            raise BrokerIdentityConflict(
                "execution projection state is not recoverable"
            )
        return saved

    def get_execution_projection_group_progress(
        self,
        execution_identity,
        operation_id,
    ):
        normalized_identity = normalize_identifier(execution_identity)
        normalized_operation_id = normalize_identifier(operation_id)
        if normalized_identity is None or normalized_operation_id is None:
            raise BrokerIdentityConflict(
                "execution projection group progress requires identity"
            )
        saved = self.execution_fills.find_one(
            {"execution_identity": normalized_identity}
        )
        if saved is None:
            raise BrokerIdentityConflict("execution projection fill is missing")
        progress_by_operation = saved.get("projection_group_progress")
        if not isinstance(progress_by_operation, dict):
            raise BrokerIdentityConflict(
                "execution projection group progress is missing"
            )
        try:
            return int(progress_by_operation[normalized_operation_id])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BrokerIdentityConflict(
                "execution projection group progress is invalid"
            ) from exc

    def advance_execution_projection_group_progress(
        self,
        execution_identity,
        operation_id,
        *,
        expected_step,
        next_step,
    ):
        normalized_identity = normalize_identifier(execution_identity)
        normalized_operation_id = normalize_identifier(operation_id)
        if normalized_identity is None or normalized_operation_id is None:
            raise BrokerIdentityConflict(
                "execution projection group progress requires identity"
            )
        field = f"projection_group_progress.{normalized_operation_id}"
        result = self.execution_fills.update_one(
            {
                "execution_identity": normalized_identity,
                "projection_status": "PENDING",
                field: int(expected_step),
            },
            {"$set": {field: int(next_step)}},
            upsert=False,
        )
        current = self.get_execution_projection_group_progress(
            normalized_identity,
            normalized_operation_id,
        )
        if result.matched_count or current == int(next_step):
            return current
        raise BrokerIdentityConflict(
            "execution projection group progress compare-and-set conflict"
        )

    def mark_execution_projection_applied(self, execution_identity, *, applied_at):
        normalized_identity = normalize_identifier(execution_identity)
        if normalized_identity is None:
            raise BrokerIdentityConflict("execution projection requires identity")
        self.execution_fills.update_one(
            {
                "execution_identity": normalized_identity,
                "projection_status": "PENDING",
            },
            {
                "$set": {
                    "projection_status": "APPLIED",
                    "projection_applied_at": applied_at,
                }
            },
        )
        saved = self.execution_fills.find_one(
            {"execution_identity": normalized_identity}
        )
        if saved is None or saved.get("projection_status") != "APPLIED":
            raise BrokerIdentityConflict(
                "execution projection could not be marked applied"
            )
        return saved

    def compare_and_set_projection_document(
        self,
        projection_type,
        *,
        before,
        after,
    ):
        targets = {
            "buy_lot": (self.buy_lots, "buy_lot_id"),
            "lot_slice": (self.lot_slices, "lot_slice_id"),
            "position_entry": (self.position_entries, "entry_id"),
            "entry_slice": (self.entry_slices, "entry_slice_id"),
        }
        target = targets.get(str(projection_type or ""))
        if target is None:
            raise BrokerIdentityConflict("execution projection target is unsupported")
        collection, identity_field = target
        before_payload = _without_mongo_id(before) if before is not None else None
        after_payload = _without_mongo_id(after) if after is not None else None
        identity = normalize_identifier(
            (after_payload or before_payload or {}).get(identity_field)
        )
        if identity is None:
            raise BrokerIdentityConflict(
                f"execution projection requires {identity_field}"
            )
        if before_payload is not None:
            before_payload[identity_field] = identity
        if after_payload is not None:
            after_payload[identity_field] = identity

        if before_payload is None:
            if after_payload is None:
                return None
            try:
                collection.update_one(
                    {identity_field: identity},
                    {"$setOnInsert": after_payload},
                    upsert=True,
                )
            except DuplicateKeyError:
                pass
            return _assert_projection_cas_result(
                collection,
                identity_field=identity_field,
                identity=identity,
                expected=after_payload,
            )

        if after_payload is None:
            result = collection.delete_one(
                _exact_projection_selector(
                    before_payload,
                    identity_field=identity_field,
                )
            )
            if result.deleted_count:
                return None
            current = list(collection.find({identity_field: identity}))
            if not current:
                return None
            raise BrokerIdentityConflict(
                f"execution projection compare-and-set conflict at {projection_type}:{identity}"
            )

        result = collection.replace_one(
            _exact_projection_selector(
                before_payload,
                identity_field=identity_field,
            ),
            after_payload,
            upsert=False,
        )
        if result.matched_count:
            return after_payload
        return _assert_projection_cas_result(
            collection,
            identity_field=identity_field,
            identity=identity,
            expected=after_payload,
        )

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
        self._ensure_canonical_indexes()
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
        self._ensure_canonical_indexes()
        self.entry_slices.delete_many({"entry_id": entry_id})
        if slices:
            self.entry_slices.insert_many(slices)
        return slices

    def upsert_entry_slices(self, slices):
        self._ensure_canonical_indexes()
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
        self._ensure_canonical_indexes()
        return _insert_allocations_fail_closed(
            self.sell_allocations,
            allocations,
        )

    def insert_exit_allocations(self, allocations):
        self._ensure_canonical_indexes()
        return _insert_allocations_fail_closed(
            self.exit_allocations,
            allocations,
        )

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

    def list_lot_slices(self, *, buy_lot_ids=None):
        query = {}
        if buy_lot_ids is not None:
            query["buy_lot_id"] = {"$in": list(buy_lot_ids)}
        return list(self.lot_slices.find(query))

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

    def list_sell_allocations(self, *, buy_lot_ids=None):
        query = {}
        if buy_lot_ids is not None:
            query["buy_lot_id"] = {"$in": list(buy_lot_ids)}
        return list(self.sell_allocations.find(query))

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


def _insert_allocations_fail_closed(collection, allocations):
    documents = [_without_mongo_id(item) for item in list(allocations or [])]
    allocation_ids = []
    for document in documents:
        allocation_id = normalize_identifier(document.get("allocation_id"))
        if allocation_id is None:
            raise BrokerIdentityConflict(
                "execution projection allocation_id is required"
            )
        document["allocation_id"] = allocation_id
        allocation_ids.append(allocation_id)
    if len(allocation_ids) != len(set(allocation_ids)):
        raise BrokerIdentityConflict(
            "execution projection contains duplicate allocation_id"
        )

    for document in documents:
        allocation_id = document["allocation_id"]
        try:
            collection.update_one(
                {"allocation_id": allocation_id},
                {"$setOnInsert": document},
                upsert=True,
            )
        except DuplicateKeyError:
            pass
        _assert_projection_cas_result(
            collection,
            identity_field="allocation_id",
            identity=allocation_id,
            expected=document,
        )
    return allocations


def _initial_projection_group_progress(projection_plan):
    progress = {}
    for group_name in ("lot_slice_groups", "entry_slice_groups"):
        for group in list((projection_plan or {}).get(group_name) or []):
            operation_id = normalize_identifier(group.get("operation_id"))
            if operation_id is None:
                raise BrokerIdentityConflict(
                    "execution projection group operation_id is required"
                )
            if operation_id in progress:
                raise BrokerIdentityConflict(
                    "execution projection group operation_id is duplicated"
                )
            progress[operation_id] = 0
    return progress


def _exact_projection_selector(document, *, identity_field):
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


def _assert_projection_cas_result(
    collection,
    *,
    identity_field,
    identity,
    expected,
):
    current = list(collection.find({identity_field: identity}))
    if len(current) == 1 and _without_mongo_id(current[0]) == _without_mongo_id(
        expected
    ):
        return current[0]
    raise BrokerIdentityConflict(
        f"execution projection compare-and-set conflict at {identity_field}:{identity}"
    )


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


def _assert_execution_replay_pair_state(states):
    legacy_states = [state for state in states if state.get("legacy") is not None]
    if legacy_states:
        for state in states:
            if state.get("legacy") is not None:
                continue
            canonical = state.get("canonical")
            if canonical is None or not canonical.get("legacy_identity_migrated"):
                raise BrokerIdentityConflict(
                    "legacy execution replay requires paired trade_fact and "
                    "execution_fill rows"
                )
        for state in states:
            canonical = state.get("canonical")
            if canonical is not None and not canonical.get("legacy_identity_migrated"):
                raise BrokerIdentityConflict(
                    "legacy execution replay conflicts with a canonical V2 counterpart"
                )
        return

    canonical_states = [state for state in states if state.get("canonical") is not None]
    if len(canonical_states) in (0, len(states)):
        return
    canonical = canonical_states[0]["canonical"]
    try:
        record_version = int(canonical.get("execution_record_version") or 0)
    except (TypeError, ValueError, OverflowError):
        record_version = 0
    if record_version >= _CANONICAL_EXECUTION_RECORD_VERSION and not canonical.get(
        "legacy_identity_migrated"
    ):
        return
    raise BrokerIdentityConflict(
        "execution replay has an unpaired legacy or unversioned counterpart"
    )


def _find_legacy_execution_candidate(collection, incoming, *, repository):
    execution_identity = normalize_identifier(incoming.get("execution_identity"))
    broker_trade_id = normalize_identifier(incoming.get("broker_trade_id"))
    if execution_identity is None or broker_trade_id is None:
        return None
    broker_trade_id_variants = [broker_trade_id]
    if broker_trade_id.isdigit():
        broker_trade_id_variants.append(int(broker_trade_id))
    candidates = [
        item
        for item in collection.find(
            {"broker_trade_id": {"$in": broker_trade_id_variants}}
        )
        if normalize_identifier(item.get("execution_identity")) is None
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise BrokerIdentityConflict(
            "legacy execution replay is ambiguous for broker_trade_id"
        )
    candidate = candidates[0]
    _assert_legacy_execution_match(candidate, incoming, repository=repository)
    return candidate


def _migrate_legacy_execution_candidate(
    collection,
    *,
    legacy,
    incoming,
    document_id_field,
    legacy_projection_status,
):
    selector = _legacy_execution_selector(
        legacy,
        document_id_field=document_id_field,
    )
    updates = {
        "execution_identity": incoming["execution_identity"],
        "broker_trade_id": incoming["broker_trade_id"],
        "account_id": incoming["account_id"],
        "trading_day": incoming["trading_day"],
        "broker_order_key": incoming.get("broker_order_key"),
        "internal_order_id": incoming.get("internal_order_id"),
        "broker_order_id": incoming.get("broker_order_id"),
        "order_sysid": incoming.get("order_sysid"),
        "legacy_identity_migrated": True,
        "execution_record_version": 1,
        "execution_record_origin": "legacy",
    }
    if legacy_projection_status is not None:
        updates["projection_status"] = legacy_projection_status
        if legacy_projection_status == "APPLIED":
            updates["projection_legacy_proven_applied"] = True
        elif legacy_projection_status == "PENDING":
            updates["projection_legacy_replay_required"] = True
    collection.update_one(
        selector,
        {"$set": {key: value for key, value in updates.items() if value is not None}},
        upsert=False,
    )
    saved = collection.find_one(selector)
    if saved is None:
        raise BrokerIdentityConflict("legacy execution migration lost canonical row")
    return saved


def _legacy_execution_selector(document, *, document_id_field):
    if document.get("_id") is not None:
        return {"_id": document["_id"]}
    document_id = normalize_identifier(document.get(document_id_field))
    if document_id is not None:
        return {document_id_field: document_id}
    return {
        "broker_trade_id": document.get("broker_trade_id"),
        "internal_order_id": document.get("internal_order_id"),
        "trade_time": document.get("trade_time"),
    }


def _assert_legacy_execution_match(existing, incoming, *, repository):
    required_fields = (
        "broker_trade_id",
        "symbol",
        "side",
        "quantity",
        "price",
        "trade_time",
    )
    conflicts = {}
    for field in required_fields:
        left = _normalize_execution_field(field, existing.get(field))
        right = _normalize_execution_field(field, incoming.get(field))
        if left is None or right is None or left != right:
            conflicts[field] = (left, right)

    existing_day = _resolve_execution_trading_day(existing)
    incoming_day = _resolve_execution_trading_day(incoming)
    if existing_day is None or incoming_day is None or existing_day != incoming_day:
        conflicts["trading_day"] = (existing_day, incoming_day)

    existing_clock = _normalize_execution_clock(existing.get("time"))
    incoming_clock = _normalize_execution_clock(incoming.get("time"))
    if (
        existing_clock is None
        or incoming_clock is None
        or existing_clock != incoming_clock
    ):
        conflicts["time"] = (existing_clock, incoming_clock)

    existing_account = _resolve_legacy_execution_account(
        existing,
        repository=repository,
    )
    incoming_account = normalize_account_id(incoming.get("account_id"))
    if (
        existing_account is None
        or incoming_account is None
        or existing_account != incoming_account
    ):
        conflicts["account_id"] = (existing_account, incoming_account)

    for field in ("internal_order_id", "broker_order_id"):
        left = normalize_identifier(existing.get(field))
        right = normalize_identifier(incoming.get(field))
        if left is not None and right is not None and left != right:
            conflicts[field] = (left, right)

    if conflicts:
        raise BrokerIdentityConflict(
            "legacy execution replay cannot be proven identical: "
            + ", ".join(sorted(conflicts))
        )


def _resolve_execution_trading_day(document):
    try:
        return normalize_trading_day(
            resolve_trading_day(
                document,
                report_time=document.get("trade_time"),
            )
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_execution_clock(value):
    normalized = str(value or "").strip()
    if not normalized:
        return None
    digits = "".join(character for character in normalized if character.isdigit())
    if len(digits) == 6:
        return digits
    return normalized


def _resolve_legacy_execution_account(document, *, repository):
    candidates = set()

    def add(value):
        normalized = normalize_account_id(value)
        if normalized is not None:
            candidates.add(normalized)

    add(document.get("account_id"))
    add(_account_from_broker_order_key(document.get("broker_order_key")))

    internal_order_id = normalize_identifier(document.get("internal_order_id"))
    if internal_order_id is not None:
        order = repository.find_order(internal_order_id)
        if order is not None:
            add(order.get("account_id"))
            add(_account_from_broker_order_key(order.get("broker_order_key")))

    broker_order_key = normalize_identifier(document.get("broker_order_key"))
    if broker_order_key is not None:
        broker_order = repository.find_broker_order(broker_order_key)
        if broker_order is not None:
            add(broker_order.get("account_id"))
            add(_account_from_broker_order_key(broker_order.get("broker_order_key")))

    broker_order_id = normalize_identifier(document.get("broker_order_id"))
    if broker_order_id is not None:
        list_orders = getattr(repository, "list_orders_by_broker_order_id", None)
        if callable(list_orders):
            orders = list_orders(broker_order_id)
        else:
            order = repository.find_order_by_broker_order_id(broker_order_id)
            orders = [order] if order is not None else []
        for order in orders:
            add(order.get("account_id"))

        list_broker_orders = getattr(
            repository, "list_broker_orders_by_broker_order_id", None
        )
        if callable(list_broker_orders):
            broker_orders = list_broker_orders(broker_order_id)
        else:
            broker_order = repository.find_broker_order_by_broker_order_id(
                broker_order_id
            )
            broker_orders = [broker_order] if broker_order is not None else []
        for broker_order in broker_orders:
            add(broker_order.get("account_id"))

    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def _account_from_broker_order_key(value):
    normalized = normalize_identifier(value)
    if normalized is None or not normalized.startswith("account:"):
        return None
    account_id, separator, _remainder = normalized[len("account:") :].partition(":day:")
    if not separator:
        return None
    return normalize_account_id(account_id)


def _resolve_legacy_execution_projection_status(repository, incoming):
    execution_identity = normalize_identifier(incoming.get("execution_identity"))
    if execution_identity is None:
        raise BrokerIdentityConflict("legacy execution projection requires identity")
    trade_fact = repository.trade_facts.find_one(
        {"execution_identity": execution_identity}
    )
    if trade_fact is None:
        raise BrokerIdentityConflict(
            "legacy execution projection requires paired canonical trade_fact"
        )
    side = normalize_side(trade_fact.get("side"))
    if side == "buy":
        return _resolve_legacy_buy_projection_status(repository, trade_fact)
    if side == "sell":
        return _resolve_legacy_sell_projection_status(repository, trade_fact)
    raise BrokerIdentityConflict("legacy execution projection side is unsupported")


def _resolve_legacy_buy_projection_status(repository, trade_fact):
    from freshquant.order_management.entry_aggregation import (
        find_entry_for_broker_order,
        list_aggregation_members,
    )

    trade_fact_id = normalize_identifier(trade_fact.get("trade_fact_id"))
    broker_order_key = normalize_identifier(
        trade_fact.get("broker_order_key") or trade_fact.get("internal_order_id")
    )
    buy_lot = (
        repository.find_buy_lot_by_origin_trade_fact_id(trade_fact_id)
        if trade_fact_id is not None
        else None
    )
    lot_slices = (
        repository.list_lot_slices(buy_lot_ids=[buy_lot["buy_lot_id"]])
        if buy_lot is not None
        else []
    )
    entries = repository.list_position_entries(symbol=trade_fact.get("symbol"))
    entry = (
        find_entry_for_broker_order(entries, broker_order_key)
        if broker_order_key is not None
        else None
    )
    entry_slices = (
        repository.list_entry_slices(entry_ids=[entry["entry_id"]])
        if entry is not None
        else []
    )
    evidence_present = bool(buy_lot or lot_slices or entry or entry_slices)
    if not evidence_present:
        return "PENDING"

    expected_quantity = int(trade_fact.get("quantity") or 0)
    expected_price = Decimal(str(trade_fact.get("price") or 0)).normalize()
    buy_lot_complete = bool(
        buy_lot is not None
        and int(buy_lot.get("original_quantity") or 0) == expected_quantity
        and Decimal(str(buy_lot.get("buy_price_real") or 0)).normalize()
        == expected_price
        and sum(int(item.get("original_quantity") or 0) for item in lot_slices)
        == int(buy_lot.get("original_quantity") or 0)
    )
    entry_complete = bool(
        entry is not None
        and broker_order_key
        in {
            normalize_identifier(item.get("broker_order_key"))
            for item in list_aggregation_members(entry)
        }
        and entry_slices
        and sum(int(item.get("original_quantity") or 0) for item in entry_slices)
        == int(entry.get("original_quantity") or 0)
    )
    if buy_lot_complete and entry_complete:
        return "APPLIED"
    raise BrokerIdentityConflict(
        "legacy buy execution projection is partial or cannot be proven applied"
    )


def _resolve_legacy_sell_projection_status(repository, trade_fact):
    trade_fact_id = normalize_identifier(trade_fact.get("trade_fact_id"))
    if trade_fact_id is None:
        raise BrokerIdentityConflict(
            "legacy sell execution projection requires trade_fact_id"
        )
    expected_quantity = int(trade_fact.get("quantity") or 0)
    exit_allocations = [
        item
        for item in repository.list_exit_allocations()
        if normalize_identifier(item.get("exit_trade_fact_id")) == trade_fact_id
    ]
    sell_allocations = [
        item
        for item in repository.list_sell_allocations()
        if normalize_identifier(item.get("sell_trade_fact_id")) == trade_fact_id
    ]
    entries = repository.list_position_entries(symbol=trade_fact.get("symbol"))
    buy_lots = repository.list_buy_lots(trade_fact.get("symbol"))
    entry_history = [
        allocation
        for entry in entries
        for allocation in list(entry.get("sell_history") or [])
        if normalize_identifier(allocation.get("exit_trade_fact_id")) == trade_fact_id
    ]
    lot_history = [
        allocation
        for buy_lot in buy_lots
        for allocation in list(buy_lot.get("sell_history") or [])
        if normalize_identifier(allocation.get("sell_trade_fact_id")) == trade_fact_id
    ]
    evidence_present = bool(
        exit_allocations or sell_allocations or entry_history or lot_history
    )
    if not evidence_present:
        return "PENDING"

    exit_quantity = sum(
        int(item.get("allocated_quantity") or 0) for item in exit_allocations
    )
    sell_quantity = sum(
        int(item.get("allocated_quantity") or 0) for item in sell_allocations
    )
    entry_history_quantity = sum(
        int(item.get("allocated_quantity") or 0) for item in entry_history
    )
    lot_history_quantity = sum(
        int(item.get("allocated_quantity") or 0) for item in lot_history
    )
    v2_complete = bool(
        exit_allocations
        and not sell_allocations
        and exit_quantity == expected_quantity
        and entry_history_quantity == expected_quantity
        and not lot_history
    )
    legacy_complete = bool(
        sell_allocations
        and not exit_allocations
        and sell_quantity == expected_quantity
        and lot_history_quantity == expected_quantity
        and not entry_history
    )
    if v2_complete or legacy_complete:
        return "APPLIED"
    raise BrokerIdentityConflict(
        "legacy sell execution projection is partial or cannot be proven applied"
    )


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
