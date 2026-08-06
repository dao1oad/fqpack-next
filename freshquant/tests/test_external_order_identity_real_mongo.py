import os
import threading
from uuid import uuid4

import pytest
from pymongo import MongoClient

from freshquant.order_management.broker_correlation import (
    build_broker_correlation_token,
)
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    build_broker_only_internal_order_id,
    build_broker_order_key,
)
from freshquant.order_management.repository import OrderManagementRepository

_RUN_REAL_MONGO = os.getenv("FQ_FIX_504_REAL_MONGO") == "1"
_REAL_MONGO_URI = os.getenv(
    "FQ_REAL_MONGO_URI",
    "mongodb://127.0.0.1:27027",
)
_TEST_DATABASE_PREFIX = "fq_test_fix_504_"
_GATE_TIMEOUT_SECONDS = 10

pytestmark = pytest.mark.skipif(
    not _RUN_REAL_MONGO,
    reason="set FQ_FIX_504_REAL_MONGO=1 to run FIX-504 real Mongo tests",
)


class _OneShotGate:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self._triggered = False

    def pause_once(self):
        with self._lock:
            if self._triggered:
                return
            self._triggered = True
        self.entered.set()
        if not self.release.wait(_GATE_TIMEOUT_SECONDS):
            raise AssertionError("timed out waiting to release Mongo race gate")


class _GatedCollection:
    def __init__(
        self,
        collection,
        *,
        gate,
        replace_when=None,
        delete_when=None,
    ):
        self._collection = collection
        self._gate = gate
        self._replace_when = replace_when
        self._delete_when = delete_when

    def __getattr__(self, name):
        return getattr(self._collection, name)

    def replace_one(self, query, document, *args, **kwargs):
        if self._replace_when is not None and self._replace_when(query, document):
            self._gate.pause_once()
        return self._collection.replace_one(query, document, *args, **kwargs)

    def delete_one(self, query, *args, **kwargs):
        if self._delete_when is not None and self._delete_when(query):
            self._gate.pause_once()
        return self._collection.delete_one(query, *args, **kwargs)


class _DatabaseWithBrokerOrderOverride:
    def __init__(self, database, broker_orders):
        self._database = database
        self._broker_orders = broker_orders

    def __getitem__(self, name):
        if name == "om_broker_orders":
            return self._broker_orders
        return self._database[name]


@pytest.fixture
def real_mongo_database():
    client = MongoClient(
        _REAL_MONGO_URI,
        connectTimeoutMS=5_000,
        serverSelectionTimeoutMS=5_000,
        tz_aware=True,
    )
    database_name = f"{_TEST_DATABASE_PREFIX}{uuid4().hex}"
    try:
        client.admin.command("ping")
        yield client[database_name]
    finally:
        if database_name.startswith(_TEST_DATABASE_PREFIX):
            client.drop_database(database_name)
        client.close()


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


def _insert_internal_order(repository, owner):
    return repository.insert_order(
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


def _start_thread(call):
    outcome = {}

    def invoke():
        try:
            outcome["value"] = call()
        except BaseException as exc:  # noqa: BLE001 - asserted by the test thread
            outcome["error"] = exc

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()
    return thread, outcome


def _release_and_join(gate, thread):
    gate.release.set()
    thread.join(_GATE_TIMEOUT_SECONDS)
    assert not thread.is_alive(), "Mongo race worker did not finish"


def test_real_mongo_same_owner_stale_claim_preserves_newer_aggregate(
    real_mongo_database,
):
    writer_repository = OrderManagementRepository(database=real_mongo_database)
    owner = _real_owner()
    key = owner["broker_order_key"]
    _insert_internal_order(writer_repository, owner)
    writer_repository.claim_broker_order_owner({**owner, "source_type": None})

    gate = _OneShotGate()
    gated_collection = _GatedCollection(
        real_mongo_database["om_broker_orders"],
        gate=gate,
        replace_when=lambda query, document: (
            query.get("broker_order_key") == key
            and document.get("source_type") == "strategy"
        ),
    )
    claimant_repository = OrderManagementRepository(
        database=_DatabaseWithBrokerOrderOverride(
            real_mongo_database,
            gated_collection,
        )
    )
    stale_claim = {
        **owner,
        "state": "CANCELED",
        "filled_quantity": 0,
        "fill_count": 0,
        "avg_filled_price": None,
        "aggregate_revision": 0,
    }
    thread, outcome = _start_thread(
        lambda: claimant_repository.claim_broker_order_owner(stale_claim)
    )

    try:
        assert gate.entered.wait(
            _GATE_TIMEOUT_SECONDS
        ), "stale owner claim did not reach the replace CAS gate"
        before = writer_repository.find_broker_order(key)
        concurrent = writer_repository.compare_and_set_broker_order(
            before=before,
            after={
                **before,
                "state": "FILLED",
                "filled_quantity": 100,
                "fill_count": 1,
                "avg_filled_price": 14.8,
                "aggregate_revision": 1,
            },
        )
        assert concurrent is not None
    finally:
        _release_and_join(gate, thread)

    assert "error" not in outcome, repr(outcome.get("error"))
    saved = writer_repository.find_broker_order(key)
    assert saved["source_type"] == "strategy"
    assert saved["state"] == "FILLED"
    assert saved["filled_quantity"] == 100
    assert saved["fill_count"] == 1
    assert saved["avg_filled_price"] == 14.8
    assert saved["aggregate_revision"] == 1


def test_real_mongo_broker_only_promotion_loses_to_execution_fence(
    real_mongo_database,
):
    writer_repository = OrderManagementRepository(database=real_mongo_database)
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
    _insert_internal_order(writer_repository, real_owner)
    writer_repository.claim_broker_order_owner(broker_only)

    gate = _OneShotGate()
    gated_collection = _GatedCollection(
        real_mongo_database["om_broker_orders"],
        gate=gate,
        replace_when=lambda query, document: (
            query.get("broker_order_key") == key
            and document.get("internal_order_id") == real_owner["internal_order_id"]
        ),
    )
    promotion_repository = OrderManagementRepository(
        database=_DatabaseWithBrokerOrderOverride(
            real_mongo_database,
            gated_collection,
        )
    )
    thread, outcome = _start_thread(
        lambda: promotion_repository.claim_broker_order_owner(real_owner)
    )

    try:
        assert gate.entered.wait(
            _GATE_TIMEOUT_SECONDS
        ), "broker-only promotion did not reach the replace CAS gate"
        fenced = writer_repository.fence_broker_order_execution(
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
        assert fenced["execution_fence"] is True
    finally:
        _release_and_join(gate, thread)

    error = outcome.get("error")
    assert isinstance(error, BrokerIdentityConflict)
    assert "targeted repair" in str(error)
    saved = writer_repository.find_broker_order(key)
    assert saved["internal_order_id"] == broker_only_id
    assert saved["source_type"] == "broker_only"
    assert saved["execution_fence"] is True
    assert (
        real_mongo_database["om_broker_orders"].count_documents(
            {"broker_order_key": key}
        )
        == 1
    )
    assert (
        real_mongo_database["om_orders"].count_documents(
            {"internal_order_id": real_owner["internal_order_id"]}
        )
        == 1
    )


def test_real_mongo_move_retries_delete_cas_and_converges_to_one_target(
    real_mongo_database,
):
    writer_repository = OrderManagementRepository(database=real_mongo_database)
    owner = _real_owner()
    old_key = owner["internal_order_id"]
    new_key = owner["broker_order_key"]
    source = {**owner, "broker_order_key": old_key}
    _insert_internal_order(writer_repository, owner)
    writer_repository.claim_broker_order_owner(source)

    gate = _OneShotGate()
    gated_collection = _GatedCollection(
        real_mongo_database["om_broker_orders"],
        gate=gate,
        delete_when=lambda query: query.get("broker_order_key") == old_key,
    )
    mover_repository = OrderManagementRepository(
        database=_DatabaseWithBrokerOrderOverride(
            real_mongo_database,
            gated_collection,
        )
    )
    thread, outcome = _start_thread(
        lambda: mover_repository.move_broker_order_key(old_key, new_key, owner)
    )

    try:
        assert gate.entered.wait(
            _GATE_TIMEOUT_SECONDS
        ), "broker-order move did not reach the source delete CAS gate"
        before = writer_repository.find_broker_order(old_key)
        concurrent = writer_repository.compare_and_set_broker_order(
            before=before,
            after={
                **before,
                "state": "FILLED",
                "filled_quantity": 100,
                "fill_count": 1,
                "avg_filled_price": 14.8,
                "aggregate_revision": 1,
            },
        )
        assert concurrent is not None
    finally:
        _release_and_join(gate, thread)

    assert "error" not in outcome, repr(outcome.get("error"))
    saved = writer_repository.find_broker_order(new_key)
    assert writer_repository.find_broker_order(old_key) is None
    assert saved == outcome["value"]
    assert saved["state"] == "FILLED"
    assert saved["filled_quantity"] == 100
    assert saved["fill_count"] == 1
    assert saved["avg_filled_price"] == 14.8
    assert saved["aggregate_revision"] == 1
    assert (
        real_mongo_database["om_broker_orders"].count_documents(
            {"broker_order_key": {"$in": [old_key, new_key]}}
        )
        == 1
    )
    assert real_mongo_database["om_broker_orders"].count_documents({}) == 1
