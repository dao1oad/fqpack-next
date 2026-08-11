from types import SimpleNamespace

import pytest

from freshquant.order_management.broker_correlation import (
    build_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    build_broker_only_internal_order_id,
    build_broker_order_key,
)
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
    normalize_xt_order_report,
    normalize_xt_trade_report,
)
from freshquant.order_management.repository import OrderManagementRepository
from freshquant.order_management.tracking.service import OrderTrackingService


class _FakeCollection:
    def __init__(self):
        self.rows = []

    def create_index(self, *_args, **_kwargs):
        return None

    def find_one(self, query):
        for document in self.find(query):
            return document
        return None

    def find(self, query):
        return [item for item in self.rows if _matches(item, query or {})]

    def update_one(self, query, update, upsert=False):
        for index, document in enumerate(self.rows):
            if not _matches(document, query or {}):
                continue
            saved = dict(document)
            saved.update(dict((update or {}).get("$set") or {}))
            self.rows[index] = saved
            return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            saved = dict(query or {})
            saved.update(dict((update or {}).get("$setOnInsert") or {}))
            saved.update(dict((update or {}).get("$set") or {}))
            self.rows.append(saved)
            return SimpleNamespace(matched_count=0, upserted_id=len(self.rows))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def replace_one(self, query, document, upsert=False):
        for index, current in enumerate(self.rows):
            if _matches(current, query or {}):
                self.rows[index] = dict(document)
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            self.rows.append(dict(document))
            return SimpleNamespace(matched_count=0, upserted_id=len(self.rows))
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def delete_one(self, query):
        for index, document in enumerate(self.rows):
            if _matches(document, query or {}):
                del self.rows[index]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def insert_one(self, document):
        self.rows.append(dict(document))
        return SimpleNamespace(inserted_id=len(self.rows))


class _PromotionRaceCollection(_FakeCollection):
    def __init__(self, broker_order_key):
        super().__init__()
        self.broker_order_key = broker_order_key
        self.before_replace = None
        self.triggered = False

    def replace_one(self, query, document, upsert=False):
        current = self.find_one({"broker_order_key": self.broker_order_key})
        is_promotion = (
            current is not None
            and current.get("source_type") == "broker_only"
            and document.get("source_type") != "broker_only"
        )
        if is_promotion and not self.triggered:
            self.triggered = True
            self.before_replace()
        return super().replace_one(query, document, upsert=upsert)


class _MutateBeforeDeleteCollection(_FakeCollection):
    def __init__(self, source_key):
        super().__init__()
        self.source_key = source_key
        self.triggered = False

    def delete_one(self, query):
        if not self.triggered:
            self.triggered = True
            source = self.find_one({"broker_order_key": self.source_key})
            source.update(
                {
                    "state": "FILLED",
                    "filled_quantity": 100,
                    "fill_count": 1,
                    "aggregate_revision": 1,
                }
            )
        return super().delete_one(query)


class _FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = _FakeCollection()
        return dict.__getitem__(self, name)


def _matches(document, query):
    for key, expected in dict(query or {}).items():
        if key == "$expr":
            operands = list((expected or {}).get("$eq") or [])
            expected_document = operands[1] if len(operands) == 2 else None
            actual_document = {
                field: value for field, value in document.items() if field != "_id"
            }
            if actual_document != expected_document:
                return False
            continue
        if isinstance(expected, dict) and "$in" in expected:
            if document.get(key) not in list(expected.get("$in") or []):
                return False
            continue
        if document.get(key) != expected:
            return False
    return True


def _real_owner(internal_order_id="ord-real"):
    return {
        "broker_order_key": build_broker_order_key(
            account_id="acct-1",
            trading_day=20260805,
            symbol="688772",
            side="buy",
            broker_order_id="557",
        ),
        "internal_order_id": internal_order_id,
        "request_id": f"request-{internal_order_id}",
        "broker_correlation_token": build_broker_correlation_token(internal_order_id),
        "account_id": "acct-1",
        "trading_day": 20260805,
        "broker_order_id": "557",
        "symbol": "688772",
        "side": "buy",
        "source_type": "strategy",
        "state": "SUBMITTED",
        "filled_quantity": 0,
        "fill_count": 0,
        "aggregate_revision": 0,
    }


def _seed_internal_order(database, owner):
    database["om_orders"].rows.append(
        {
            "internal_order_id": owner["internal_order_id"],
            "request_id": owner["request_id"],
            "broker_correlation_token": owner["broker_correlation_token"],
            "account_id": owner["account_id"],
            "trading_day": owner["trading_day"],
            "broker_order_id": owner["broker_order_id"],
            "symbol": owner["symbol"],
            "side": owner["side"],
            "source_type": "strategy",
        }
    )


def test_external_identity_is_deterministic_and_account_scoped():
    key = build_broker_order_key(
        account_id="acct-1",
        trading_day=20260805,
        symbol="688772.SH",
        side="BUY",
        broker_order_id=557,
    )
    assert key == ("account:acct-1:day:20260805:symbol:688772:side:buy:order:557")
    assert build_broker_only_internal_order_id(
        account_id="acct-1",
        trading_day=20260805,
        symbol="688772",
        side="buy",
        broker_order_id="557",
    ).startswith("ord_broker_")


def test_same_owner_claim_never_rolls_back_newer_fill_aggregate():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    _seed_internal_order(database, owner)
    repository.claim_broker_order_owner(owner)
    database["om_broker_orders"].rows[0].update(
        {
            "state": "FILLED",
            "filled_quantity": 100,
            "fill_count": 1,
            "avg_filled_price": 14.8,
            "aggregate_revision": 1,
        }
    )

    saved, created = repository.claim_broker_order_owner(
        {
            **owner,
            "state": "CANCELED",
            "filled_quantity": 0,
            "fill_count": 0,
            "avg_filled_price": None,
            "aggregate_revision": 0,
        }
    )

    assert created is False
    assert saved["state"] == "FILLED"
    assert saved["filled_quantity"] == 100
    assert saved["fill_count"] == 1
    assert saved["avg_filled_price"] == 14.8
    assert saved["aggregate_revision"] == 1


def test_broker_only_promotion_loses_race_with_first_execution_fence():
    real_owner = _real_owner()
    key = real_owner["broker_order_key"]
    broker_only_id = build_broker_only_internal_order_id(
        account_id="acct-1",
        trading_day=20260805,
        symbol="688772",
        side="buy",
        broker_order_id="557",
    )
    broker_only = {
        **real_owner,
        "internal_order_id": broker_only_id,
        "request_id": None,
        "broker_correlation_token": None,
        "source_type": "broker_only",
    }
    database = _FakeDatabase()
    collection = _PromotionRaceCollection(key)
    collection.rows.append(broker_only)
    database["om_broker_orders"] = collection
    _seed_internal_order(database, real_owner)
    repository = OrderManagementRepository(database=database)

    collection.before_replace = lambda: repository.fence_broker_order_execution(
        {
            "broker_order_key": key,
            "internal_order_id": broker_only_id,
            "account_id": "acct-1",
            "trading_day": 20260805,
            "broker_order_id": "557",
            "symbol": "688772",
            "side": "buy",
        }
    )

    with pytest.raises(BrokerIdentityConflict, match="targeted repair"):
        repository.claim_broker_order_owner(real_owner)

    saved = repository.find_broker_order(key)
    assert saved["internal_order_id"] == broker_only_id
    assert saved["execution_fence"] is True


def test_internal_state_update_does_not_move_canonical_broker_key_back_to_placeholder():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    database["om_orders"].rows.append(
        {
            **owner,
            "state": "ACCEPTED",
        }
    )
    repository.claim_broker_order_owner(owner)
    tracking_service = OrderTrackingService(repository=repository)

    tracking_service.mark_order_queued(owner["internal_order_id"])

    assert len(database["om_broker_orders"].rows) == 1
    saved = repository.find_broker_order(owner["broker_order_key"])
    assert saved["state"] == "QUEUED"
    assert repository.find_broker_order(owner["internal_order_id"]) is None


def test_terminal_order_replay_does_not_downgrade_broker_aggregate_state():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    database["om_orders"].rows.append(
        {
            **owner,
            "state": "FILLED",
        }
    )
    repository.claim_broker_order_owner(
        {
            **owner,
            "state": "FILLED",
            "filled_quantity": 100,
            "fill_count": 1,
            "aggregate_revision": 1,
        }
    )
    tracking_service = OrderTrackingService(repository=repository)

    result = tracking_service.ingest_order_report_with_meta(
        {
            "internal_order_id": owner["internal_order_id"],
            "broker_order_key": owner["broker_order_key"],
            "broker_order_id": owner["broker_order_id"],
            "state": "CANCELED",
            "event_type": "stale_cancel_replay",
        }
    )

    assert result["absorbed"] is True
    assert repository.find_order(owner["internal_order_id"])["state"] == "FILLED"
    assert repository.find_broker_order(owner["broker_order_key"])["state"] == "FILLED"


def test_move_missing_source_cannot_silently_accept_fenced_target():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    owner = _real_owner()
    broker_only_id = build_broker_only_internal_order_id(
        account_id="acct-1",
        trading_day=20260805,
        symbol="688772",
        side="buy",
        broker_order_id="557",
    )
    database["om_orders"].rows.append(
        {
            **owner,
            "state": "SUBMITTED",
        }
    )
    target = {
        **owner,
        "internal_order_id": broker_only_id,
        "request_id": None,
        "broker_correlation_token": None,
        "source_type": "broker_only",
        "execution_fence": True,
    }
    database["om_broker_orders"].rows.append(target)

    with pytest.raises(BrokerIdentityConflict, match="targeted repair"):
        repository.move_broker_order_key(
            "missing-placeholder", owner["broker_order_key"], owner
        )

    saved = repository.find_broker_order(owner["broker_order_key"])
    assert saved["internal_order_id"] == broker_only_id
    assert saved["execution_fence"] is True


def test_late_order_sysid_promotes_existing_fallback_broker_order_without_duplication():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )

    first = ingest_service.ingest_order_report(_xt_order_callback(order_sysid=None))
    fallback_key = first["broker_order_key"]
    second = ingest_service.ingest_order_report(_xt_order_callback())
    canonical_key = build_broker_order_key(
        account_id="acct-xt-1",
        order_sysid="SYS-557",
        trading_day=20260805,
    )

    assert second["internal_order_id"] == first["internal_order_id"]
    assert len(database["om_orders"].rows) == 1
    assert len(database["om_broker_orders"].rows) == 1
    assert repository.find_broker_order(fallback_key) is None
    assert repository.find_broker_order(canonical_key)["internal_order_id"] == (
        first["internal_order_id"]
    )
    assert repository.find_order(first["internal_order_id"])["order_sysid"] == "SYS-557"


def test_move_retries_source_delete_cas_and_keeps_concurrent_aggregate():
    owner = _real_owner()
    old_key = owner["internal_order_id"]
    new_key = owner["broker_order_key"]
    source = {**owner, "broker_order_key": old_key}
    database = _FakeDatabase()
    collection = _MutateBeforeDeleteCollection(old_key)
    collection.rows.append(source)
    database["om_broker_orders"] = collection
    _seed_internal_order(database, owner)
    repository = OrderManagementRepository(database=database)

    saved = repository.move_broker_order_key(old_key, new_key, owner)

    assert repository.find_broker_order(old_key) is None
    assert saved == repository.find_broker_order(new_key)
    assert saved["state"] == "FILLED"
    assert saved["filled_quantity"] == 100
    assert saved["fill_count"] == 1
    assert saved["aggregate_revision"] == 1
    assert len(database["om_broker_orders"].rows) == 1


def _xt_order_callback(*, account_id="acct-xt-1", order_id="557", **overrides):
    return {
        "account_id": account_id,
        "order_id": order_id,
        "order_sysid": "SYS-557",
        "order_time": 1785947400,
        "date": 20260805,
        "stock_code": "688772.SH",
        "order_type": 23,
        "order_volume": 100,
        "order_status": 50,
        "source": "xtquant",
        **overrides,
    }


def _xt_trade_callback(*, account_id="acct-xt-1", order_id="557", **overrides):
    return {
        "account_id": account_id,
        "order_id": order_id,
        "order_sysid": "SYS-557",
        "traded_id": "TRADE-557-1",
        "traded_time": 1785947460,
        "date": 20260805,
        "stock_code": "688772.SH",
        "order_type": 23,
        "traded_volume": 100,
        "traded_price": 14.8,
        "source": "xtquant",
        **overrides,
    }


def test_unknown_xt_order_callback_creates_deterministic_broker_only_owner():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    callback = _xt_order_callback()

    normalized = normalize_xt_order_report(callback, repository=repository)
    expected_key = build_broker_order_key(
        account_id="acct-xt-1",
        order_sysid="SYS-557",
        trading_day=20260805,
    )
    expected_order_id = build_broker_only_internal_order_id(
        account_id="acct-xt-1",
        order_sysid="SYS-557",
        trading_day=20260805,
    )

    assert normalized["internal_order_id"] == expected_order_id
    assert normalized["broker_order_key"] == expected_key

    result = ingest_service.ingest_order_report(callback)

    assert result["internal_order_id"] == expected_order_id
    assert repository.find_order(expected_order_id)["source_type"] == "broker_only"
    broker_order = repository.find_broker_order(expected_key)
    assert broker_order["internal_order_id"] == expected_order_id
    assert broker_order["source_type"] == "broker_only"


def test_unknown_xt_trade_callback_fences_owner_before_idempotent_execution_write():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    order_callback = _xt_order_callback()
    trade_callback = _xt_trade_callback()
    ingest_service.ingest_order_report(order_callback)

    normalized_trade = normalize_xt_trade_report(
        trade_callback,
        repository=repository,
    )
    first = tracking_service.ingest_trade_report_with_meta(normalized_trade)
    second = tracking_service.ingest_trade_report_with_meta(normalized_trade)

    broker_order = repository.find_broker_order(normalized_trade["broker_order_key"])
    assert broker_order["execution_fence"] is True
    assert broker_order["filled_quantity"] == 100
    assert first["execution_fill"]["execution_identity"]
    assert second["created"] is False
    assert len(database["om_trade_facts"].rows) == 1
    assert len(database["om_execution_fills"].rows) == 1


def test_real_internal_order_promotes_unfilled_broker_only_owner_only_once():
    database = _FakeDatabase()
    repository = OrderManagementRepository(database=database)
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    callback = _xt_order_callback()
    normalized = ingest_service.ingest_order_report(callback)

    tracking_service.submit_order(
        {
            "internal_order_id": "ord-real-557",
            "request_id": "req-real-557",
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "688772",
            "price": 14.8,
            "quantity": 100,
            "source": "strategy",
            "account_id": "acct-xt-1",
            "order_sysid": "SYS-557",
            "trading_day": 20260805,
            "broker_order_id": "557",
        }
    )

    broker_order = repository.find_broker_order(normalized["broker_order_key"])
    assert broker_order["internal_order_id"] == "ord-real-557"
    assert broker_order["request_id"] == "req-real-557"
    assert broker_order["source_type"] == "strategy"
    assert broker_order.get("execution_fence") is not True
