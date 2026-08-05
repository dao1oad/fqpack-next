from datetime import datetime, timezone

import pytest

import freshquant.order_management.ingest.xt_reports as xt_reports_module
import freshquant.order_management.submit.service as submit_service_module
from freshquant.order_management.broker_identity import (
    BrokerIdentityConflict,
    BrokerIdentityError,
    build_broker_only_internal_order_id,
    build_broker_order_key,
)
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
    normalize_xt_order_report,
    normalize_xt_trade_report,
)
from freshquant.order_management.submit.service import OrderSubmitService
from freshquant.order_management.tracking.service import OrderTrackingService


class InMemoryRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.broker_orders = []
        self.order_events = []
        self.trade_facts = []
        self.execution_fills = []
        self.buy_lots = []
        self.lot_slices = []
        self.sell_allocations = []
        self.position_entries = []
        self.entry_slices = []
        self.exit_allocations = []
        self.ingest_rejections = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def upsert_broker_order(self, document, unique_keys):
        for existing in self.broker_orders:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                existing.update(document)
                return existing, False
        saved = dict(document)
        self.broker_orders.append(saved)
        return saved, True

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def upsert_execution_fill(self, document, unique_keys):
        for existing in self.execution_fills:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        saved = dict(document)
        self.execution_fills.append(saved)
        return saved, True

    def prepare_execution_projection(self, execution_identity, projection_plan):
        for execution_fill in self.execution_fills:
            if execution_fill.get("execution_identity") != execution_identity:
                continue
            if execution_fill.get("projection_status") != "PENDING":
                return execution_fill
            stored_plan = execution_fill.get("projection_plan")
            if stored_plan is None:
                execution_fill["projection_plan"] = projection_plan
                execution_fill["projection_group_progress"] = {
                    group["operation_id"]: 0
                    for group_name in ("lot_slice_groups", "entry_slice_groups")
                    for group in projection_plan.get(group_name) or []
                }
            return execution_fill
        raise AssertionError("execution fill not found")

    def get_execution_projection_group_progress(
        self,
        execution_identity,
        operation_id,
    ):
        execution_fill = next(
            item
            for item in self.execution_fills
            if item.get("execution_identity") == execution_identity
        )
        return int(execution_fill["projection_group_progress"][operation_id])

    def advance_execution_projection_group_progress(
        self,
        execution_identity,
        operation_id,
        *,
        expected_step,
        next_step,
    ):
        execution_fill = next(
            item
            for item in self.execution_fills
            if item.get("execution_identity") == execution_identity
        )
        progress = execution_fill["projection_group_progress"]
        current = int(progress[operation_id])
        if current == int(next_step):
            return current
        if current != int(expected_step):
            raise BrokerIdentityConflict("projection progress CAS mismatch")
        progress[operation_id] = int(next_step)
        return int(next_step)

    def mark_execution_projection_applied(self, execution_identity, *, applied_at):
        for execution_fill in self.execution_fills:
            if execution_fill.get("execution_identity") != execution_identity:
                continue
            execution_fill["projection_status"] = "APPLIED"
            execution_fill["projection_applied_at"] = applied_at
            return execution_fill
        raise AssertionError("execution fill not found")

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
        collection, identity_field = targets[projection_type]
        identity = (after or before)[identity_field]
        matches = [
            (index, document)
            for index, document in enumerate(collection)
            if document.get(identity_field) == identity
        ]
        if len(matches) > 1:
            raise BrokerIdentityConflict("projection CAS found duplicate identity")
        current = matches[0][1] if matches else None
        if current == after:
            return current
        if current != before:
            raise BrokerIdentityConflict("projection CAS preimage mismatch")
        if after is None:
            if matches:
                del collection[matches[0][0]]
            return None
        if matches:
            collection[matches[0][0]] = dict(after)
        else:
            collection.append(dict(after))
        return after

    def list_execution_fills(self, *, broker_order_keys=None, **_kwargs):
        rows = list(self.execution_fills)
        if broker_order_keys is not None:
            allowed = set(broker_order_keys)
            rows = [item for item in rows if item.get("broker_order_key") in allowed]
        return rows

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
                return order
        return None

    def find_order_request(self, request_id):
        for request in self.order_requests:
            if request["request_id"] == request_id:
                return request
        return None

    def find_order_by_request_id(self, request_id):
        for order in self.orders:
            if order.get("request_id") == request_id:
                return order
        return None

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
                return order
        return None

    def find_order_by_broker_order_id(self, broker_order_id):
        for order in self.orders:
            if str(order.get("broker_order_id")) == str(broker_order_id):
                return order
        return None

    def list_orders_by_broker_order_id(self, broker_order_id):
        return [
            order
            for order in self.orders
            if str(order.get("broker_order_id")) == str(broker_order_id)
        ]

    def find_order_by_broker_correlation_token(self, token):
        for order in self.orders:
            if order.get("broker_correlation_token") == token:
                return order
        return None

    def list_orders(
        self,
        symbol=None,
        states=None,
        missing_broker_only=False,
        **_kwargs,
    ):
        rows = list(self.orders)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if states is not None:
            allowed = set(states)
            rows = [item for item in rows if item.get("state") in allowed]
        if missing_broker_only:
            rows = [item for item in rows if item.get("broker_order_id") in (None, "")]
        return rows

    def update_order(self, internal_order_id, updates):
        order = self.find_order(internal_order_id)
        if order is None:
            return None
        order.update(updates)
        return order

    def find_buy_lot_by_origin_trade_fact_id(self, origin_trade_fact_id):
        for buy_lot in self.buy_lots:
            if buy_lot["origin_trade_fact_id"] == origin_trade_fact_id:
                return buy_lot
        return None

    def find_buy_lot(self, buy_lot_id):
        for buy_lot in self.buy_lots:
            if buy_lot["buy_lot_id"] == buy_lot_id:
                return buy_lot
        return None

    def insert_buy_lot(self, document):
        self.buy_lots.append(document)
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(slices)

    def list_lot_slices(self, *, buy_lot_ids=None):
        rows = list(self.lot_slices)
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item.get("buy_lot_id") in allowed]
        return [dict(item) for item in rows]

    def list_buy_lots(self, symbol):
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def list_open_slices(self, symbol):
        return [
            item
            for item in self.lot_slices
            if item["symbol"] == symbol and item["remaining_quantity"] > 0
        ]

    def replace_buy_lot(self, buy_lot):
        for index, current in enumerate(self.buy_lots):
            if current["buy_lot_id"] == buy_lot["buy_lot_id"]:
                self.buy_lots[index] = buy_lot
                return buy_lot
        self.buy_lots.append(buy_lot)
        return buy_lot

    def replace_open_slices(self, slices):
        slice_ids = {item["lot_slice_id"] for item in slices}
        self.lot_slices = [
            item for item in self.lot_slices if item["lot_slice_id"] not in slice_ids
        ]
        self.lot_slices.extend(slices)

    def insert_sell_allocations(self, allocations):
        return self._insert_allocations(self.sell_allocations, allocations)

    def replace_position_entry(self, document):
        for index, current in enumerate(self.position_entries):
            if current["entry_id"] == document["entry_id"]:
                self.position_entries[index] = dict(document)
                return document
        self.position_entries.append(dict(document))
        return document

    def find_position_entry(self, entry_id):
        for item in self.position_entries:
            if item.get("entry_id") == entry_id:
                return item
        return None

    def list_position_entries(self, *, symbol=None, entry_ids=None, status=None):
        rows = list(self.position_entries)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        if status is not None:
            rows = [item for item in rows if item.get("status") == status]
        return rows

    def replace_entry_slices_for_entry(self, entry_id, slices):
        self.entry_slices = [
            item for item in self.entry_slices if item["entry_id"] != entry_id
        ]
        self.entry_slices.extend(dict(item) for item in slices)
        return slices

    def upsert_entry_slices(self, slices):
        for document in slices:
            for index, current in enumerate(self.entry_slices):
                if current["entry_slice_id"] == document["entry_slice_id"]:
                    self.entry_slices[index] = dict(document)
                    break
            else:
                self.entry_slices.append(dict(document))
        return slices

    def list_entry_slices(self, *, entry_ids=None):
        rows = list(self.entry_slices)
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        return [dict(item) for item in rows]

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = [
            item
            for item in self.entry_slices
            if int(item.get("remaining_quantity") or 0) > 0
        ]
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
        return [dict(item) for item in rows]

    def insert_exit_allocations(self, allocations):
        return self._insert_allocations(self.exit_allocations, allocations)

    @staticmethod
    def _insert_allocations(collection, allocations):
        seen = set()
        for raw_document in allocations:
            document = dict(raw_document)
            allocation_id = str(document.get("allocation_id") or "").strip()
            if not allocation_id or allocation_id in seen:
                raise BrokerIdentityConflict("allocation_id is missing or duplicate")
            seen.add(allocation_id)
            existing = [
                item
                for item in collection
                if item.get("allocation_id") == allocation_id
            ]
            if len(existing) > 1 or (existing and existing[0] != document):
                raise BrokerIdentityConflict("allocation_id conflicts")
            if not existing:
                collection.append(document)
        return allocations

    def insert_ingest_rejection(self, document):
        self.ingest_rejections.append(dict(document))
        return document


def _bootstrap_service():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "trading_day": 20240102,
            "symbol": "000001",
            "price": 10.0,
            "quantity": 900,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_test_1",
        }
    )
    tracking_service.submit_order(
        {
            "action": "sell",
            "account_id": "acct-test",
            "trading_day": 20240103,
            "symbol": "000001",
            "price": 10.8,
            "quantity": 500,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_test_sell_1",
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )

    def _noop_sync_stock_fills_compat(symbol, repository):
        return None

    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat
    return repository, ingest_service


def _stub_ingest_side_effects(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {"on_new_buy_trade": lambda self, symbol, buy_price: None},
        )(),
        raising=False,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "_get_guardian_buy_grid_service",
        lambda: type(
            "FakeGuardianBuyGridService",
            (),
            {"reset_after_sell_trade": lambda self, symbol: None},
        )(),
        raising=False,
    )


def test_ingest_service_defers_default_tpsl_construction_until_buy_notification(
    monkeypatch,
):
    constructed = []
    notifications = []

    class FakeTpslService:
        def on_new_buy_trade(self, *, symbol, buy_price):
            notifications.append((symbol, buy_price))

    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: constructed.append(True) or FakeTpslService(),
    )

    service = OrderManagementXtIngestService(
        repository=InMemoryRepository(),
        tracking_service=object(),
    )

    assert constructed == []

    service._notify_new_buy_trade(symbol="000001", price=10.5)
    service._notify_new_buy_trade(symbol="000001", price=10.6)

    assert constructed == [True]
    assert notifications == [("000001", 10.5), ("000001", 10.6)]


def _noop_sync_stock_fills_compat(symbol, repository=None):
    del symbol, repository
    return None


def _buy_report(broker_trade_id="T-100", **overrides):
    payload = {
        "internal_order_id": "ord_test_1",
        "account_id": "acct-test",
        "broker_trade_id": broker_trade_id,
        "symbol": "000001",
        "side": "buy",
        "quantity": 900,
        "price": 10.0,
        "trade_time": 1710000000,
        "date": 20240102,
        "time": "09:31:00",
        "source": "xt_trade_callback",
    }
    payload.update(overrides)
    return payload


def _sell_report(broker_trade_id="T-101", **overrides):
    payload = {
        "internal_order_id": "ord_test_sell_1",
        "account_id": "acct-test",
        "broker_trade_id": broker_trade_id,
        "symbol": "000001",
        "side": "sell",
        "quantity": 500,
        "price": 10.8,
        "trade_time": 1710003600,
        "date": 20240103,
        "time": "10:00:00",
        "source": "xt_trade_callback",
    }
    payload.update(overrides)
    return payload


def test_normalize_xt_trade_report_extracts_side_symbol_and_timestamp():
    normalized = normalize_xt_trade_report(
        {
            "order_id": "O-100",
            "account_id": "acct-test",
            "traded_id": "T-100",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "traded_volume": 900,
            "traded_price": 10.0,
            "traded_time": 1710000000,
            "strategy_name": "Guardian",
        }
    )

    assert normalized["internal_order_id"].startswith("ord_broker_")
    assert normalized["broker_trade_id"] == "T-100"
    assert normalized["symbol"] == "000001"
    assert normalized["side"] == "buy"
    assert normalized["date"] == 20240310


def test_normalize_xt_trade_report_treats_credit_fin_buy_as_buy():
    normalized = normalize_xt_trade_report(
        {
            "order_id": "O-200",
            "account_id": "acct-test",
            "traded_id": "T-200",
            "stock_code": "600000.SH",
            "order_type": 27,
            "traded_volume": 100,
            "traded_price": 10.0,
            "traded_time": 1710000000,
        }
    )

    assert normalized["side"] == "buy"


def test_normalize_xt_trade_report_treats_sell_repay_as_sell():
    normalized = normalize_xt_trade_report(
        {
            "order_id": "O-201",
            "account_id": "acct-test",
            "traded_id": "T-201",
            "stock_code": "600000.SH",
            "order_type": 31,
            "traded_volume": 100,
            "traded_price": 10.0,
            "traded_time": 1710000000,
        }
    )

    assert normalized["side"] == "sell"


def test_normalize_xt_trade_report_does_not_attach_side_conflict_candidate():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "600000",
            "price": 10.0,
            "quantity": 100,
            "source": "api",
            "internal_order_id": "ord_credit_ingest_1",
            "broker_order_type": 27,
        }
    )
    repository.update_order(
        "ord_credit_ingest_1",
        {
            "state": "SUBMITTED",
            "broker_order_id": "92001",
            "broker_order_type": 27,
        },
    )

    normalized = normalize_xt_trade_report(
        {
            "account_id": "acct-test",
            "order_id": "92001",
            "traded_id": "T-202",
            "stock_code": "600000.SH",
            "order_type": 24,
            "traded_volume": 100,
            "traded_price": 10.0,
            "traded_time": 1710000000,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"].startswith("ord_broker_")
    assert normalized["internal_order_id"] != "ord_credit_ingest_1"
    assert normalized["side"] == "sell"


def test_normalize_xt_trade_report_disambiguates_reused_broker_order_id():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "002262",
            "price": 21.0,
            "quantity": 2300,
            "source": "api",
            "internal_order_id": "ord_old_buy",
            "broker_order_type": 27,
            "trace_id": "trc_old",
            "request_id": "req_old",
        }
    )
    repository.update_order(
        "ord_old_buy",
        {
            "broker_order_id": "1477443585",
            "broker_order_type": 27,
            "state": "FILLED",
            "submitted_at": "2026-04-13T14:22:07+08:00",
        },
    )
    tracking_service.submit_order(
        {
            "action": "sell",
            "account_id": "acct-test",
            "symbol": "002262",
            "price": 22.41,
            "quantity": 2300,
            "source": "api",
            "internal_order_id": "ord_new_sell",
            "broker_order_type": 24,
            "trace_id": "trc_new",
            "request_id": "req_new",
        }
    )
    repository.update_order(
        "ord_new_sell",
        {
            "broker_order_id": "1477443585",
            "broker_order_type": 24,
            "state": "SUBMITTED",
            "submitted_at": "2026-04-29T10:14:06+08:00",
        },
    )

    normalized = normalize_xt_trade_report(
        {
            "order_id": "1477443585",
            "account_id": "acct-test",
            "traded_id": "0103000030649603",
            "stock_code": "002262.SZ",
            "order_type": 24,
            "traded_volume": 2300,
            "traded_price": 22.41,
            "traded_time": 1777428846,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_new_sell"
    assert normalized["side"] == "sell"
    assert normalized["trace_id"] == "trc_new"
    assert normalized["request_id"] == "req_new"


def test_normalize_xt_order_report_disambiguates_reused_broker_order_id():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "002262",
            "price": 21.0,
            "quantity": 2300,
            "source": "api",
            "internal_order_id": "ord_old_buy",
            "broker_order_type": 27,
            "trace_id": "trc_old",
            "request_id": "req_old",
        }
    )
    repository.update_order(
        "ord_old_buy",
        {
            "broker_order_id": "1477443585",
            "broker_order_type": 27,
            "state": "FILLED",
            "submitted_at": "2026-04-13T14:22:07+08:00",
        },
    )
    tracking_service.submit_order(
        {
            "action": "sell",
            "account_id": "acct-test",
            "symbol": "002262",
            "price": 22.41,
            "quantity": 2300,
            "source": "api",
            "internal_order_id": "ord_new_sell",
            "broker_order_type": 24,
            "trace_id": "trc_new",
            "request_id": "req_new",
        }
    )
    repository.update_order(
        "ord_new_sell",
        {
            "broker_order_id": "1477443585",
            "broker_order_type": 24,
            "state": "SUBMITTED",
            "submitted_at": "2026-04-29T10:14:06+08:00",
        },
    )

    normalized = normalize_xt_order_report(
        {
            "order_id": 1477443585,
            "account_id": "acct-test",
            "stock_code": "002262.SZ",
            "order_type": 24,
            "order_time": 1777428846,
            "order_status": 50,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_new_sell"
    assert normalized["state"] == "SUBMITTED"
    assert normalized["trace_id"] == "trc_new"
    assert normalized["request_id"] == "req_new"


def test_upsert_broker_position_entry_uses_beijing_time_when_local_fromtimestamp_differs(
    monkeypatch,
):
    from datetime import datetime, timezone

    class FakeDateTime(datetime):
        @classmethod
        def fromtimestamp(cls, timestamp, tz=None):
            if tz is None:
                return datetime.fromtimestamp(timestamp, timezone.utc).replace(
                    tzinfo=None
                )
            return datetime.fromtimestamp(timestamp, tz=tz)

    monkeypatch.setattr(xt_reports_module, "datetime", FakeDateTime)

    repository = InMemoryRepository()
    repository.broker_orders.append(
        {
            "broker_order_key": "ord_test_fill_time_backfill",
            "filled_quantity": 100,
            "first_fill_time": 1710000000,
            "avg_filled_price": 10.0,
        }
    )

    entry, _ = xt_reports_module._upsert_broker_position_entry(
        repository=repository,
        trade_fact={
            "internal_order_id": "ord_test_fill_time_backfill",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 10.0,
            "trade_time": None,
            "date": None,
            "time": None,
            "source": "xt_trade_callback",
        },
        lot_amount=50000,
        grid_interval=1.03,
    )

    assert entry["date"] == 20240310
    assert entry["time"] == "00:00:00"


def test_normalize_xt_order_report_maps_broker_order_back_to_internal_order():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "trading_day": 20240310,
            "symbol": "000001",
            "price": 10.0,
            "quantity": 900,
            "source": "strategy",
            "internal_order_id": "ord_test_order_report",
        }
    )
    repository.update_order(
        "ord_test_order_report",
        {"state": "SUBMITTED", "broker_order_id": "81001"},
    )

    normalized = normalize_xt_order_report(
        {
            "order_id": 81001,
            "account_id": "acct-test",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "order_time": 1710000000,
            "order_status": 54,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_test_order_report"
    assert normalized["broker_order_id"] == "81001"
    assert normalized["state"] == "CANCELED"


def test_configured_submit_identity_binds_first_xt_report_to_original_order(
    monkeypatch,
):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 8, 5, 1, 30, tzinfo=timezone.utc)
            return value if tz is not None else value.replace(tzinfo=None)

    class QueueClient:
        def __init__(self):
            self.messages = []

        def lpush(self, queue_name, payload):
            self.messages.append((queue_name, payload))
            return len(self.messages)

    class RuntimeLogger:
        def emit(self, _event):
            return None

    monkeypatch.setattr(submit_service_module, "datetime", FixedDateTime)
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    submit_service = OrderSubmitService(
        repository=repository,
        tracking_service=tracking_service,
        queue_client=QueueClient(),
        position_management_service=object(),
        account_type_loader=lambda: "STOCK",
        account_id_loader=lambda: "acct-configured",
        runtime_logger=RuntimeLogger(),
    )
    submitted = submit_service.submit_order(
        {
            "action": "buy",
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        tpsl_service=None,
        runtime_logger=RuntimeLogger(),
    )

    normalized = ingest_service.ingest_order_report(
        {
            "order_id": 90001,
            "account_id": "acct-configured",
            "stock_code": "688772.SH",
            "order_type": 23,
            "order_remark": submitted["queue_payload"]["broker_correlation_token"],
            "order_time": int(
                datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
            ),
            "order_status": 50,
        }
    )

    assert repository.order_requests[0]["trading_day"] == 20260805
    assert repository.orders[0]["trading_day"] == 20260805
    assert normalized["internal_order_id"] == submitted["internal_order_id"]
    assert repository.orders[0]["internal_order_id"] == submitted["internal_order_id"]
    assert repository.orders[0]["broker_order_id"] == "90001"
    assert len(repository.orders) == 1
    assert len(submitted["queue_payload"]["broker_correlation_token"]) == 24


def test_first_xt_report_with_multiple_unbound_candidates_fails_closed():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id in ("ord-unbound-a", "ord-unbound-b"):
        tracking_service.submit_order(
            {
                "action": "buy",
                "account_id": "acct-configured",
                "trading_day": 20260805,
                "symbol": "688772",
                "price": 14.7,
                "quantity": 10000,
                "source": "api",
                "internal_order_id": internal_order_id,
            }
        )

    with pytest.raises(BrokerIdentityConflict, match="correlation token"):
        normalize_xt_order_report(
            {
                "order_id": 90002,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert len(repository.orders) == 2
    assert all(order.get("broker_order_id") is None for order in repository.orders)
    assert repository.ingest_rejections[-1]["reason_code"] == (
        "broker_identity_conflict"
    )


@pytest.mark.parametrize(
    ("order_remark", "error_match"),
    [
        ("FQOMshort", "malformed"),
        ("FQOM00000000000000000000", "unknown"),
    ],
)
def test_first_xt_report_with_invalid_correlation_token_is_quarantined(
    order_remark,
    error_match,
):
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "internal_order_id": "ord-invalid-token",
        }
    )
    assert (
        repository.find_order("ord-invalid-token")["broker_correlation_token"]
        != order_remark
    )

    with pytest.raises(BrokerIdentityConflict, match=error_match):
        normalize_xt_order_report(
            {
                "order_id": 90007,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_remark": order_remark,
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert repository.find_order("ord-invalid-token")["broker_order_id"] is None
    assert repository.ingest_rejections[-1]["reason_code"] == (
        "broker_identity_conflict"
    )


def test_explicit_internal_order_id_conflicting_with_token_is_quarantined():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id in ("ord-pinned-owner", "ord-token-owner"):
        tracking_service.submit_order(
            {
                "action": "buy",
                "account_id": "acct-configured",
                "trading_day": 20260805,
                "symbol": "688772",
                "price": 14.7,
                "quantity": 10000,
                "source": "api",
                "internal_order_id": internal_order_id,
            }
        )
    token_order = repository.find_order("ord-token-owner")

    with pytest.raises(BrokerIdentityConflict, match="pinned internal order"):
        normalize_xt_order_report(
            {
                "internal_order_id": "ord-pinned-owner",
                "order_id": 90008,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_remark": token_order["broker_correlation_token"],
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert all(order.get("broker_order_id") is None for order in repository.orders)
    assert repository.ingest_rejections[-1]["reason_code"] == (
        "broker_identity_conflict"
    )


def test_first_xt_report_without_token_never_binds_unique_unbound_order():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "broker_order_type": 27,
            "internal_order_id": "ord-unbound-only",
        }
    )

    with pytest.raises(BrokerIdentityConflict, match="correlation token"):
        normalize_xt_order_report(
            {
                "order_id": 90003,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_volume": 100,
                "price": 99.99,
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert repository.orders[0]["broker_order_id"] is None
    assert repository.ingest_rejections[-1]["reason_code"] == (
        "broker_identity_conflict"
    )


def test_correlation_token_rejects_conflicting_broker_order_type():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "broker_order_type": 27,
            "internal_order_id": "ord-token-type-conflict",
        }
    )
    order = repository.find_order("ord-token-type-conflict")

    with pytest.raises(BrokerIdentityConflict, match="broker_order_type"):
        normalize_xt_order_report(
            {
                "order_id": 90004,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_remark": order["broker_correlation_token"],
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert order["broker_order_id"] is None


def test_legacy_bound_candidate_plus_unbound_candidate_fails_closed():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "internal_order_id": "ord-legacy-bound",
        }
    )
    repository.update_order(
        "ord-legacy-bound",
        {"state": "SUBMITTED", "broker_order_id": "90005"},
    )
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "internal_order_id": "ord-unbound-current",
        }
    )

    with pytest.raises(BrokerIdentityConflict, match="correlation token"):
        normalize_xt_order_report(
            {
                "order_id": 90005,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert repository.find_order("ord-unbound-current")["broker_order_id"] is None


def test_correlation_token_rejects_broker_identity_owned_by_another_order():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "internal_order_id": "ord-existing-broker-owner",
        }
    )
    repository.update_order(
        "ord-existing-broker-owner",
        {"state": "SUBMITTED", "broker_order_id": "90006"},
    )
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-configured",
            "trading_day": 20260805,
            "symbol": "688772",
            "price": 14.7,
            "quantity": 10000,
            "source": "api",
            "internal_order_id": "ord-token-new-owner",
        }
    )
    token_order = repository.find_order("ord-token-new-owner")

    with pytest.raises(BrokerIdentityConflict, match="already owned"):
        normalize_xt_order_report(
            {
                "order_id": 90006,
                "account_id": "acct-configured",
                "stock_code": "688772.SH",
                "order_type": 23,
                "order_remark": token_order["broker_correlation_token"],
                "order_time": int(
                    datetime(2026, 8, 5, 1, 31, tzinfo=timezone.utc).timestamp()
                ),
                "order_status": 50,
            },
            repository=repository,
        )

    assert (
        repository.find_order("ord-existing-broker-owner")["broker_order_id"] == "90006"
    )
    assert token_order["broker_order_id"] is None


def test_normalize_xt_order_report_creates_deterministic_broker_only_identity():
    repository = InMemoryRepository()

    normalized = normalize_xt_order_report(
        {
            "order_id": 89991,
            "account_id": "acct-test",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "order_time": 1710000000,
            "order_status": 54,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"].startswith("ord_broker_")
    assert normalized["internal_order_id"] != "89991"


def test_broker_only_internal_order_id_requires_complete_identity():
    with pytest.raises(BrokerIdentityError, match="broker order identity requires"):
        build_broker_only_internal_order_id(
            account_id="acct-test",
            broker_order_id="89992",
        )


def test_order_report_does_not_guess_unique_incomplete_candidate():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 900,
            "source": "strategy",
            "internal_order_id": "ord_incomplete_identity",
        }
    )
    repository.update_order(
        "ord_incomplete_identity",
        {"state": "SUBMITTED", "broker_order_id": "89992"},
    )

    normalized = normalize_xt_order_report(
        {
            "account_id": "acct-test",
            "order_id": 89992,
            "stock_code": "000001.SZ",
            "order_status": 54,
        },
        repository=repository,
    )

    assert normalized is None
    assert repository.ingest_rejections[-1]["reason_code"] == (
        "incomplete_broker_order_identity"
    )


def test_normalize_xt_order_report_keeps_cancel_requested_state_for_pending_cancel():
    normalized = normalize_xt_order_report(
        {
            "order_id": 81002,
            "account_id": "acct-test",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "order_time": 1710000000,
            "order_status": 51,
        }
    )

    assert normalized["broker_order_id"] == "81002"
    assert normalized["state"] == "CANCEL_REQUESTED"


def test_trade_report_creates_trade_fact_position_entry_and_slices():
    repository, ingest_service = _bootstrap_service()

    result = ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.trade_facts) == 1
    assert len(repository.execution_fills) == 1
    assert len(repository.position_entries) == 1
    assert repository.position_entries[0]["source_ref_type"] == "buy_cluster"
    assert repository.position_entries[0]["entry_type"] == "broker_execution_cluster"
    assert repository.position_entries[0]["original_quantity"] == 900
    assert repository.position_entries[0]["remaining_quantity"] == 900
    assert len(repository.entry_slices) == 4
    assert result["position_entry"]["original_quantity"] == 900
    assert len(result["entry_slices"]) == 4


def test_trade_report_marks_holding_projection_updated(monkeypatch):
    repository, ingest_service = _bootstrap_service()
    marks = []
    sync_calls = []

    monkeypatch.setattr(
        xt_reports_module,
        "mark_stock_holdings_projection_updated",
        lambda: marks.append("marked"),
        raising=False,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda symbol, repository: sync_calls.append((symbol, repository)),
        raising=False,
    )

    ingest_service.ingest_trade_report(
        _buy_report("T-100-mark"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert marks == ["marked"]
    assert sync_calls == [("000001", repository)]


def test_sell_trade_report_creates_sell_allocations_and_updates_projection():
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = ingest_service.ingest_trade_report(
        _sell_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert result["sell_allocations"] == []
    assert len(result["exit_allocations"]) == 2
    assert repository.sell_allocations == []
    assert repository.buy_lots[0]["remaining_quantity"] == 900
    assert sum(item["remaining_quantity"] for item in repository.lot_slices) == 900
    assert repository.position_entries[0]["remaining_quantity"] == 400
    assert repository.position_entries[0]["status"] == "PARTIALLY_EXITED"


def test_sell_trade_report_prefers_guardian_source_entries_when_allocating_entry_slices():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id, side, quantity, price, strategy_context in (
        ("ord_pref_buy_1", "buy", 100, 10.0, None),
        ("ord_pref_buy_2", "buy", 100, 10.2, None),
        (
            "ord_pref_sell_1",
            "sell",
            100,
            10.8,
            {
                "guardian_sell_sources": {
                    "entries": [{"entry_id": "placeholder", "quantity": 100}],
                    "submit_quantity": 100,
                }
            },
        ),
    ):
        payload = {
            "action": side,
            "symbol": "000001",
            "price": price,
            "quantity": quantity,
            "source": "xt_trade_callback",
            "internal_order_id": internal_order_id,
        }
        if strategy_context is not None:
            payload["strategy_context"] = strategy_context
        tracking_service.submit_order(payload)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_trade_report(
        _buy_report(
            "T-PREF-BUY-1",
            internal_order_id="ord_pref_buy_1",
            quantity=100,
            price=10.0,
            trade_time=1710000000,
            date=20240310,
            time="09:30:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _buy_report(
            "T-PREF-BUY-2",
            internal_order_id="ord_pref_buy_2",
            quantity=100,
            price=10.2,
            trade_time=1710000600,
            date=20240310,
            time="09:40:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    preferred_entry_id = repository.position_entries[0]["entry_id"]
    repository.order_requests[-1]["strategy_context"]["guardian_sell_sources"][
        "entries"
    ][0]["entry_id"] = preferred_entry_id

    result = ingest_service.ingest_trade_report(
        _sell_report(
            "T-PREF-SELL-1",
            internal_order_id="ord_pref_sell_1",
            quantity=100,
            price=10.8,
            trade_time=1710001200,
            date=20240310,
            time="09:50:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(result["exit_allocations"]) == 1
    assert result["exit_allocations"][0]["entry_id"] == preferred_entry_id


def test_sell_trade_report_syncs_stock_fills_compat_when_holdings_change(monkeypatch):
    repository, ingest_service = _bootstrap_service()
    sync_calls = []
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda symbol, repository: sync_calls.append((symbol, repository)),
        raising=False,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "mark_stock_holdings_projection_updated",
        lambda: None,
        raising=False,
    )

    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _sell_report("T-101-sync"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert sync_calls == [
        ("000001", repository),
        ("000001", repository),
    ]


def test_sell_trade_report_resets_guardian_buy_grid_state(monkeypatch):
    repository, ingest_service = _bootstrap_service()
    resets = []
    ingest_service.ingest_trade_report(
        _buy_report("T-100-reset"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "_get_guardian_buy_grid_service",
        lambda: type(
            "FakeGuardianBuyGridService",
            (),
            {"reset_after_sell_trade": lambda self, code: resets.append(code)},
        )(),
    )

    ingest_service.ingest_trade_report(
        _sell_report("T-101-reset"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert resets == ["000001"]


def test_repeated_callback_does_not_duplicate_trade_fact_or_projection():
    repository, ingest_service = _bootstrap_service()
    report = _buy_report()

    ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.trade_facts) == 1
    assert len(repository.buy_lots) == 1
    assert len(repository.position_entries) == 1
    assert len(repository.list_open_entry_slices(symbol="000001")) == 4
    assert len(repository.list_open_slices("000001")) == 4


def test_pending_buy_projection_replay_recovers_missing_entry(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    original_compare_and_set = repository.compare_and_set_projection_document
    failed = False

    def fail_before_entry_write(projection_type, *, before, after):
        nonlocal failed
        if projection_type == "position_entry" and not failed:
            failed = True
            raise RuntimeError("simulated crash before entry write")
        return original_compare_and_set(
            projection_type,
            before=before,
            after=after,
        )

    monkeypatch.setattr(
        repository,
        "compare_and_set_projection_document",
        fail_before_entry_write,
    )
    report = _buy_report("T-PENDING-BUY")

    with pytest.raises(RuntimeError, match="before entry write"):
        ingest_service.ingest_trade_report(
            report,
            lot_amount=3000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    execution_fill = repository.execution_fills[0]
    assert execution_fill["projection_status"] == "PENDING"
    assert execution_fill["projection_plan"] is not None
    assert repository.position_entries == []
    assert len(repository.buy_lots) == 1

    monkeypatch.setattr(
        repository,
        "compare_and_set_projection_document",
        original_compare_and_set,
    )
    replay = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    second_replay = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert replay["created"] is False
    assert replay["position_entry"] is not None
    assert repository.execution_fills[0]["projection_status"] == "APPLIED"
    assert len(repository.position_entries) == 1
    assert len(repository.buy_lots) == 1
    assert len(repository.entry_slices) == 4
    assert second_replay["created"] is False
    assert len(repository.position_entries) == 1


def test_projection_apply_cas_preserves_concurrent_entry_change(monkeypatch):
    repository = InMemoryRepository()
    before = {
        "entry_id": "entry-cas",
        "symbol": "000001",
        "remaining_quantity": 900,
        "status": "OPEN",
    }
    after = {**before, "remaining_quantity": 400}
    repository.position_entries.append(dict(before))
    original_compare_and_set = repository.compare_and_set_projection_document

    def concurrent_change(projection_type, *, before, after):
        if projection_type == "position_entry":
            repository.position_entries[0] = {
                **repository.position_entries[0],
                "remaining_quantity": 777,
            }
        return original_compare_and_set(
            projection_type,
            before=before,
            after=after,
        )

    monkeypatch.setattr(
        repository,
        "compare_and_set_projection_document",
        concurrent_change,
    )
    projection_plan = {
        "version": 1,
        "side": "sell",
        "buy_lots": [],
        "lot_slice_groups": [],
        "position_entries": [{"before": before, "after": after}],
        "entry_slice_groups": [],
        "sell_allocations": [],
        "exit_allocations": [],
    }

    with pytest.raises(BrokerIdentityConflict, match="preimage mismatch"):
        xt_reports_module._apply_execution_projection_plan(
            repository=repository,
            projection_plan=projection_plan,
        )

    assert repository.position_entries[0]["remaining_quantity"] == 777


def test_projection_apply_cas_preserves_concurrent_slice_change(monkeypatch):
    repository = InMemoryRepository()
    before = [
        {
            "entry_slice_id": "slice-cas-1",
            "entry_id": "entry-cas",
            "remaining_quantity": 500,
        },
        {
            "entry_slice_id": "slice-cas-2",
            "entry_id": "entry-cas",
            "remaining_quantity": 400,
        },
    ]
    after = [
        {**before[0], "remaining_quantity": 0},
        dict(before[1]),
    ]
    repository.entry_slices.extend(dict(item) for item in before)
    original_compare_and_set = repository.compare_and_set_projection_document

    def concurrent_change(projection_type, *, before, after):
        if projection_type == "entry_slice":
            repository.entry_slices[0] = {
                **repository.entry_slices[0],
                "remaining_quantity": 333,
            }
        return original_compare_and_set(
            projection_type,
            before=before,
            after=after,
        )

    monkeypatch.setattr(
        repository,
        "compare_and_set_projection_document",
        concurrent_change,
    )
    projection_plan = {
        "version": 1,
        "side": "sell",
        "buy_lots": [],
        "lot_slice_groups": [],
        "position_entries": [],
        "entry_slice_groups": [
            {
                "entry_id": "entry-cas",
                "before": before,
                "after": after,
            }
        ],
        "sell_allocations": [],
        "exit_allocations": [],
    }

    with pytest.raises(BrokerIdentityConflict, match="preimage mismatch"):
        xt_reports_module._apply_execution_projection_plan(
            repository=repository,
            projection_plan=projection_plan,
        )

    assert repository.entry_slices[0]["remaining_quantity"] == 333


def test_projection_group_recovery_accepts_only_deterministic_prefix_states():
    before = [
        {"entry_slice_id": "slice-1", "remaining_quantity": 500},
        {"entry_slice_id": "slice-2", "remaining_quantity": 400},
    ]
    after = [
        {**before[0], "remaining_quantity": 0},
        {**before[1], "remaining_quantity": 0},
    ]

    assert (
        xt_reports_module._assert_projection_group_recoverable(
            [after[0], before[1]],
            before=before,
            after=after,
            identity_field="entry_slice_id",
            label="entry_slices:entry-1",
        )
        == 1
    )
    for current in (
        [],
        [before[0]],
        [before[0], after[1]],
        [*before, {"entry_slice_id": "slice-extra", "remaining_quantity": 1}],
    ):
        with pytest.raises(BrokerIdentityConflict, match="diverged"):
            xt_reports_module._assert_projection_group_recoverable(
                current,
                before=before,
                after=after,
                identity_field="entry_slice_id",
                label="entry_slices:entry-1",
            )


@pytest.mark.parametrize(
    "allocations",
    [
        [{"allocated_quantity": 100}],
        [
            {"allocation_id": "alloc-duplicate", "allocated_quantity": 100},
            {"allocation_id": "alloc-duplicate", "allocated_quantity": 100},
        ],
    ],
)
def test_projection_plan_rejects_missing_or_duplicate_allocation_ids(allocations):
    projection_plan = {
        "version": 1,
        "side": "sell",
        "buy_lots": [],
        "lot_slice_groups": [],
        "position_entries": [],
        "entry_slice_groups": [],
        "sell_allocations": [],
        "exit_allocations": allocations,
    }

    with pytest.raises(BrokerIdentityConflict, match="allocation"):
        xt_reports_module._apply_execution_projection_plan(
            repository=InMemoryRepository(),
            projection_plan=projection_plan,
        )


def test_projection_allocation_insert_does_not_overwrite_concurrent_value(
    monkeypatch,
):
    repository = InMemoryRepository()
    expected = {"allocation_id": "alloc-cas", "allocated_quantity": 100}
    concurrent = {"allocation_id": "alloc-cas", "allocated_quantity": 77}
    original_insert = repository.insert_exit_allocations

    def concurrent_insert(allocations):
        repository.exit_allocations.append(dict(concurrent))
        return original_insert(allocations)

    monkeypatch.setattr(repository, "insert_exit_allocations", concurrent_insert)
    projection_plan = {
        "version": 1,
        "side": "sell",
        "buy_lots": [],
        "lot_slice_groups": [],
        "position_entries": [],
        "entry_slice_groups": [],
        "sell_allocations": [],
        "exit_allocations": [expected],
    }

    with pytest.raises(BrokerIdentityConflict, match="allocation_id conflicts"):
        xt_reports_module._apply_execution_projection_plan(
            repository=repository,
            projection_plan=projection_plan,
        )

    assert repository.exit_allocations == [concurrent]


def test_projection_allocation_insert_requires_final_postimage(monkeypatch):
    repository = InMemoryRepository()
    expected = {"allocation_id": "alloc-final", "allocated_quantity": 100}
    monkeypatch.setattr(
        repository,
        "insert_exit_allocations",
        lambda _allocations: None,
    )

    with pytest.raises(BrokerIdentityConflict, match="allocation is missing"):
        xt_reports_module._persist_projection_allocations(
            repository,
            allocation_type="exit",
            documents=[expected],
        )

    assert repository.exit_allocations == []


def test_final_projection_assertion_detects_postimage_changed_after_apply(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    original_build_entry_projections = xt_reports_module._build_entry_projections

    def mutate_applied_entry(symbol, *, repository):
        repository.position_entries[0]["concurrent_marker"] = "changed-after-apply"
        return original_build_entry_projections(symbol, repository=repository)

    monkeypatch.setattr(
        xt_reports_module,
        "_build_entry_projections",
        mutate_applied_entry,
    )

    with pytest.raises(
        BrokerIdentityConflict,
        match="postimage diverged at position_entry",
    ):
        ingest_service.ingest_trade_report(
            _buy_report("T-FINAL-POSTIMAGE"),
            lot_amount=3000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    execution_fill = next(
        item
        for item in repository.execution_fills
        if item.get("broker_trade_id") == "T-FINAL-POSTIMAGE"
    )
    assert execution_fill["projection_status"] == "PENDING"
    assert repository.position_entries[0]["concurrent_marker"] == "changed-after-apply"


def test_historical_execution_without_projection_state_is_not_reapplied():
    repository = InMemoryRepository()
    trade_fact = {
        "trade_fact_id": "trade-legacy",
        "execution_identity": "execution-legacy",
        "broker_order_key": "legacy-order",
        "internal_order_id": "legacy-order",
        "broker_trade_id": "legacy-trade",
        "symbol": "000001",
        "side": "buy",
        "quantity": 900,
        "price": 10.0,
        "trade_time": 1710000000,
        "date": 20240310,
        "time": "09:30:00",
    }
    execution_fill = {
        "execution_fill_id": "fill-legacy",
        **{key: value for key, value in trade_fact.items() if key != "trade_fact_id"},
    }

    class LegacyReplayTrackingService:
        def ingest_trade_report_with_meta(self, _report):
            return {
                "trade_fact": trade_fact,
                "execution_fill": execution_fill,
                "created": False,
            }

    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=LegacyReplayTrackingService(),
        tpsl_service=None,
    )
    result = ingest_service.ingest_trade_report(
        dict(trade_fact),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert result["created"] is False
    assert repository.buy_lots == []
    assert repository.position_entries == []
    assert repository.entry_slices == []


def test_execution_fragment_quantity_is_accepted_into_entry_ledger():
    repository, ingest_service = _bootstrap_service()

    result = ingest_service.ingest_trade_report(
        {
            **_buy_report("T-odd"),
            "quantity": 18,
            "amount": 180.0,
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.trade_facts) == 1
    assert len(repository.execution_fills) == 1
    assert repository.position_entries[0]["original_quantity"] == 18
    assert sum(int(item["original_quantity"]) for item in repository.entry_slices) == 18
    assert repository.buy_lots[0]["original_quantity"] == 18
    assert repository.ingest_rejections == []
    assert result["position_entry"]["original_quantity"] == 18


def test_multiple_buy_trade_reports_for_same_order_update_one_position_entry():
    def _noop_sync_stock_fills_compat(_symbol: str, repository: object) -> None:
        del repository

    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "trading_day": 20240102,
            "symbol": "000001",
            "price": 10.0,
            "quantity": 1800,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_test_agg_1",
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_trade_report(
        {
            **_buy_report("T-201"),
            "internal_order_id": "ord_test_agg_1",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        {
            **_buy_report("T-202"),
            "internal_order_id": "ord_test_agg_1",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.position_entries) == 1
    assert repository.position_entries[0]["source_ref_type"] == "buy_cluster"
    assert repository.position_entries[0]["entry_type"] == "broker_execution_cluster"
    assert repository.position_entries[0]["original_quantity"] == 1800
    assert repository.position_entries[0]["remaining_quantity"] == 1800


def test_late_buy_fill_after_sell_keeps_entry_and_slice_inventory_consistent():
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report("T-LATE-BUY-1", quantity=900),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _sell_report("T-LATE-BUY-SELL", quantity=500),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = ingest_service.ingest_trade_report(
        _buy_report(
            "T-LATE-BUY-2",
            quantity=100,
            trade_time=1710007200,
            time="11:00:00",
        ),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    entry = result["position_entry"]
    slices = repository.list_entry_slices(entry_ids=[entry["entry_id"]])
    assert entry["original_quantity"] == 1000
    assert entry["remaining_quantity"] == 500
    assert sum(int(item["original_quantity"]) for item in slices) == 1000
    assert sum(int(item["remaining_quantity"]) for item in slices) == 500


def test_trade_report_conservatively_merges_close_buy_orders_into_one_clustered_entry():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id, quantity in (
        ("ord_cluster_1", 400),
        ("ord_cluster_2", 500),
    ):
        tracking_service.submit_order(
            {
                "action": "buy",
                "symbol": "000001",
                "price": 10.0,
                "quantity": quantity,
                "source": "xt_trade_callback",
                "internal_order_id": internal_order_id,
            }
        )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_trade_report(
        _buy_report(
            "T-CLUSTER-1",
            internal_order_id="ord_cluster_1",
            quantity=400,
            price=10.0,
            trade_time=1710000000,
            date=20240310,
            time="09:30:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    result = ingest_service.ingest_trade_report(
        _buy_report(
            "T-CLUSTER-2",
            internal_order_id="ord_cluster_2",
            quantity=500,
            price=10.02,
            trade_time=1710000240,
            date=20240310,
            time="09:34:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.position_entries) == 1
    assert len(repository.entry_slices) == 1
    assert result["position_entry"]["source_ref_type"] == "buy_cluster"
    assert result["position_entry"]["entry_type"] == "broker_execution_cluster"
    assert result["position_entry"]["original_quantity"] == 900
    assert result["position_entry"]["remaining_quantity"] == 900
    assert [
        item["broker_order_key"]
        for item in result["position_entry"]["aggregation_members"]
    ] == [
        "ord_cluster_1",
        "ord_cluster_2",
    ]
    assert result["position_entry"]["aggregation_window"]["member_count"] == 2


def test_trade_report_does_not_chain_merge_beyond_anchor_five_minute_window():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id in ("ord_chain_1", "ord_chain_2", "ord_chain_3"):
        tracking_service.submit_order(
            {
                "action": "buy",
                "symbol": "000001",
                "price": 10.0,
                "quantity": 300,
                "source": "xt_trade_callback",
                "internal_order_id": internal_order_id,
            }
        )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    for broker_trade_id, internal_order_id, price, trade_time, time_text in (
        ("T-CHAIN-1", "ord_chain_1", 10.00, 1710000000, "09:30:00"),
        ("T-CHAIN-2", "ord_chain_2", 10.01, 1710000240, "09:34:00"),
        ("T-CHAIN-3", "ord_chain_3", 10.02, 1710000480, "09:38:00"),
    ):
        ingest_service.ingest_trade_report(
            _buy_report(
                broker_trade_id,
                internal_order_id=internal_order_id,
                quantity=300,
                price=price,
                trade_time=trade_time,
                date=20240310,
                time=time_text,
            ),
            lot_amount=50000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    assert len(repository.position_entries) == 2
    assert sorted(
        int(item["original_quantity"]) for item in repository.position_entries
    ) == [300, 600]


def test_trade_report_does_not_merge_after_sell_touches_clustered_entry():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id, side, quantity, price in (
        ("ord_sell_boundary_1", "buy", 400, 10.00),
        ("ord_sell_boundary_2", "buy", 500, 10.01),
        ("ord_sell_boundary_sell", "sell", 200, 10.60),
        ("ord_sell_boundary_3", "buy", 200, 10.00),
    ):
        tracking_service.submit_order(
            {
                "action": side,
                "symbol": "000001",
                "price": price,
                "quantity": quantity,
                "source": "xt_trade_callback",
                "internal_order_id": internal_order_id,
            }
        )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_trade_report(
        _buy_report(
            "T-SELL-BOUNDARY-1",
            internal_order_id="ord_sell_boundary_1",
            quantity=400,
            price=10.00,
            trade_time=1710000000,
            date=20240310,
            time="09:30:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _buy_report(
            "T-SELL-BOUNDARY-2",
            internal_order_id="ord_sell_boundary_2",
            quantity=500,
            price=10.01,
            trade_time=1710000240,
            date=20240310,
            time="09:34:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _sell_report(
            "T-SELL-BOUNDARY-S",
            internal_order_id="ord_sell_boundary_sell",
            quantity=200,
            price=10.60,
            trade_time=1710003600,
            date=20240310,
            time="10:30:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    ingest_service.ingest_trade_report(
        _buy_report(
            "T-SELL-BOUNDARY-3",
            internal_order_id="ord_sell_boundary_3",
            quantity=200,
            price=10.00,
            trade_time=1710003720,
            date=20240310,
            time="10:32:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.position_entries) == 2
    assert sorted(
        int(item["remaining_quantity"]) for item in repository.position_entries
    ) == [200, 700]


def test_repeated_sell_callback_does_not_duplicate_sell_allocations(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    report = _sell_report()

    first = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    second = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert first["sell_allocations"] == []
    assert len(first["exit_allocations"]) == 2
    assert second["sell_allocations"] == []
    assert second["exit_allocations"] == []
    assert repository.sell_allocations == []
    assert len(repository.exit_allocations) == 2
    assert repository.buy_lots[0]["remaining_quantity"] == 900


def test_pending_sell_projection_replay_recovers_missing_allocation(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report("T-BUY-BEFORE-PENDING-SELL"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    original_insert_exit_allocations = repository.insert_exit_allocations
    failed = False

    def fail_before_allocation_write(allocations):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("simulated crash before allocation write")
        return original_insert_exit_allocations(allocations)

    monkeypatch.setattr(
        repository,
        "insert_exit_allocations",
        fail_before_allocation_write,
    )
    report = _sell_report("T-PENDING-SELL")

    with pytest.raises(RuntimeError, match="before allocation write"):
        ingest_service.ingest_trade_report(
            report,
            lot_amount=3000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    sell_fill = next(
        item
        for item in repository.execution_fills
        if item.get("broker_trade_id") == "T-PENDING-SELL"
    )
    assert sell_fill["projection_status"] == "PENDING"
    assert sell_fill["projection_plan"] is not None
    assert repository.exit_allocations == []
    assert repository.position_entries[0]["remaining_quantity"] == 400

    monkeypatch.setattr(
        repository,
        "insert_exit_allocations",
        original_insert_exit_allocations,
    )
    replay = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    second_replay = ingest_service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert replay["created"] is False
    assert (
        sum(int(item["allocated_quantity"]) for item in repository.exit_allocations)
        == 500
    )
    assert repository.position_entries[0]["remaining_quantity"] == 400
    assert sell_fill["projection_status"] == "APPLIED"
    assert second_replay["created"] is False
    assert second_replay["exit_allocations"] == []
    assert len(repository.exit_allocations) == 2


def test_sell_trade_skips_legacy_allocation_when_v2_entries_are_authoritative(
    monkeypatch,
):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    repository.buy_lots = []
    repository.lot_slices = []
    sync_calls = []
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda symbol, repository=None: sync_calls.append((symbol, repository)),
        raising=False,
    )

    result = ingest_service.ingest_trade_report(
        _sell_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert result["sell_allocations"] == []
    assert (
        sum(int(item["allocated_quantity"]) for item in result["exit_allocations"])
        == 500
    )
    assert repository.sell_allocations == []
    assert (
        sum(int(item["allocated_quantity"]) for item in repository.exit_allocations)
        == 500
    )
    assert (
        sum(
            int(item["remaining_quantity"])
            for item in repository.list_position_entries(symbol="000001")
        )
        == 400
    )
    assert (
        sum(
            int(item["remaining_quantity"])
            for item in repository.list_open_entry_slices(symbol="000001")
        )
        == 400
    )
    assert sync_calls == [("000001", repository)]


def test_sell_trade_fails_closed_when_v2_entry_has_no_open_inventory(
    monkeypatch,
):
    _stub_ingest_side_effects(monkeypatch)
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    for entry in repository.position_entries:
        entry["remaining_quantity"] = 0
        entry["status"] = "CLOSED"
    for entry_slice in repository.entry_slices:
        entry_slice["remaining_quantity"] = 0
        entry_slice["status"] = "CLOSED"

    with pytest.raises(BrokerIdentityConflict, match="no open V2 inventory"):
        ingest_service.ingest_trade_report(
            _sell_report(),
            lot_amount=3000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    assert repository.exit_allocations == []
    assert repository.sell_allocations == []
    assert repository.buy_lots[0]["remaining_quantity"] == 900
    assert sum(item["remaining_quantity"] for item in repository.lot_slices) == 900
    sell_fill = next(
        item
        for item in repository.execution_fills
        if item.get("broker_trade_id") == "T-101"
    )
    assert sell_fill["projection_status"] == "PENDING"


@pytest.mark.parametrize("slice_state", ["missing", "quantity_mismatch"])
def test_sell_trade_fails_closed_when_v2_slice_inventory_is_invalid(slice_state):
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    if slice_state == "missing":
        repository.entry_slices = []
    else:
        repository.entry_slices[0]["remaining_quantity"] -= 1

    with pytest.raises(BrokerIdentityConflict, match="V2 entry slices"):
        ingest_service.ingest_trade_report(
            _sell_report(),
            lot_amount=3000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    assert repository.exit_allocations == []
    assert repository.position_entries[0]["remaining_quantity"] == 900
    sell_fill = next(
        item
        for item in repository.execution_fills
        if item.get("broker_trade_id") == "T-101"
    )
    assert sell_fill["projection_status"] == "PENDING"


def test_order_report_updates_existing_order_state():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "trading_day": 20240310,
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "api",
            "internal_order_id": "ord_order_state_1",
        }
    )
    repository.update_order(
        "ord_order_state_1",
        {"state": "SUBMITTED", "broker_order_id": "90088"},
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )

    ingest_service.ingest_order_report(
        {
            "order_id": 90088,
            "account_id": "acct-test",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "order_time": 1710000000,
            "order_status": 54,
        }
    )

    assert repository.find_order("ord_order_state_1")["state"] == "CANCELED"


def test_broker_order_key_primary_identity_includes_trading_day():
    first = build_broker_order_key(
        account_id="acct-test",
        trading_day=20260526,
        order_sysid="1263",
    )
    second = build_broker_order_key(
        account_id="acct-test",
        trading_day=20260804,
        order_sysid="1263",
    )

    assert first == "account:acct-test:day:20260526:sysid:1263"
    assert second == "account:acct-test:day:20260804:sysid:1263"
    assert first != second


def test_unique_600917_candidate_cannot_match_688772_trade():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "600917",
            "price": 5.16,
            "quantity": 38700,
            "source": "manual",
            "internal_order_id": "ord-600917-history",
        }
    )
    repository.update_order(
        "ord-600917-history",
        {
            "broker_order_id": "1209008130",
            "trading_day": 20260804,
            "state": "FILLED",
        },
    )

    normalized = normalize_xt_trade_report(
        {
            "account_id": "acct-test",
            "order_id": "1209008130",
            "order_sysid": "1263",
            "traded_id": "trade-688772-buy",
            "stock_code": "688772.SH",
            "order_type": 23,
            "traded_volume": 10000,
            "traded_price": 14.70,
            "traded_time": 1785808800,
        },
        repository=repository,
    )

    assert normalized["internal_order_id"].startswith("ord_broker_")
    assert normalized["internal_order_id"] != "ord-600917-history"
    assert normalized["symbol"] == "688772"
    assert normalized["trading_day"] == 20260804


def test_pinned_internal_order_symbol_conflict_is_quarantined():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "600917",
            "price": 5.16,
            "quantity": 38700,
            "source": "manual",
            "internal_order_id": "ord-pinned-600917",
        }
    )

    with pytest.raises(BrokerIdentityConflict, match="symbol"):
        normalize_xt_trade_report(
            {
                "internal_order_id": "ord-pinned-600917",
                "account_id": "acct-test",
                "order_id": "1209008130",
                "traded_id": "trade-pinned-mismatch",
                "stock_code": "688772.SH",
                "order_type": 23,
                "traded_volume": 10000,
                "traded_price": 14.70,
                "traded_time": 1785808800,
            },
            repository=repository,
        )

    assert repository.ingest_rejections[-1]["reason_code"] == "broker_identity_conflict"
    assert repository.trade_facts == []


def test_unknown_xt_order_type_is_quarantined_instead_of_defaulting_to_sell():
    repository = InMemoryRepository()

    with pytest.raises(BrokerIdentityError, match="side"):
        normalize_xt_trade_report(
            {
                "account_id": "acct-test",
                "order_id": "unknown-side-order",
                "traded_id": "unknown-side-trade",
                "stock_code": "688772.SH",
                "order_type": 999,
                "traded_volume": 164,
                "traded_price": 14.80,
                "traded_time": 1785895200,
            },
            repository=repository,
        )

    assert repository.ingest_rejections[-1]["reason_code"] == "unknown_order_side"


def test_164_share_sell_execution_is_allocated_directly():
    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report(quantity=900),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    result = ingest_service.ingest_trade_report(
        _sell_report("T-SELL-164", quantity=164),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert (
        sum(int(item["allocated_quantity"]) for item in result["exit_allocations"])
        == 164
    )
    assert repository.position_entries[0]["remaining_quantity"] == 736
    assert repository.ingest_rejections == []


def test_nine_sell_fragments_conserve_quantity_and_replay_idempotently():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "account_id": "acct-test",
            "symbol": "688772",
            "price": 14.70,
            "quantity": 10000,
            "source": "manual",
            "internal_order_id": "ord-688772-buy",
        }
    )
    tracking_service.submit_order(
        {
            "action": "sell",
            "account_id": "acct-test",
            "symbol": "688772",
            "price": 14.80,
            "quantity": 10000,
            "source": "guardian",
            "internal_order_id": "ord-688772-sell",
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        tpsl_service=type(
            "FakeTpslService",
            (),
            {"on_new_buy_trade": lambda self, symbol, buy_price: None},
        )(),
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat
    ingest_service.ingest_trade_report(
        _buy_report(
            "T-688772-BUY",
            internal_order_id="ord-688772-buy",
            symbol="688772",
            quantity=10000,
            price=14.70,
            trade_time=1785808800,
            date=20260804,
            time="10:00:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    fragments = (164, 203, 340, 358, 200, 2653, 3000, 1000, 2082)
    reports = []
    for index, quantity in enumerate(fragments, start=1):
        report = _sell_report(
            f"T-688772-SELL-{index}",
            internal_order_id="ord-688772-sell",
            symbol="688772",
            quantity=quantity,
            price=14.80,
            trade_time=1785895200 + index,
            date=20260805,
            time=f"10:00:{index:02d}",
        )
        reports.append(report)
        ingest_service.ingest_trade_report(
            report,
            lot_amount=50000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
        )

    replay = ingest_service.ingest_trade_report(
        reports[-1],
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    entry = repository.list_position_entries(symbol="688772")[0]
    entry_slice_ids = {
        item["entry_slice_id"]
        for item in repository.entry_slices
        if item["symbol"] == "688772"
    }
    allocations = list(repository.exit_allocations)
    sell_fills = [
        item
        for item in repository.execution_fills
        if item["symbol"] == "688772" and item["side"] == "sell"
    ]

    assert fragments == (164, 203, 340, 358, 200, 2653, 3000, 1000, 2082)
    assert sum(fragments) == 10000
    assert len(sell_fills) == 9
    assert sum(int(item["quantity"]) for item in sell_fills) == 10000
    assert sum(int(item["allocated_quantity"]) for item in allocations) == 10000
    assert entry["remaining_quantity"] == 0
    assert len(entry_slice_ids) == 4
    assert sorted(
        (
            float(item["guardian_price"]),
            int(item["original_quantity"]),
        )
        for item in repository.entry_slices
        if item["symbol"] == "688772"
    ) == [
        (14.70, 3400),
        (15.14, 3300),
        (15.59, 3200),
        (16.06, 100),
    ]
    assert all(
        int(item["remaining_quantity"]) == 0
        for item in repository.entry_slices
        if item["symbol"] == "688772"
    )
    assert all(item["entry_slice_id"] in entry_slice_ids for item in allocations)
    assert replay["created"] is False
    assert replay["exit_allocations"] == []
    assert repository.ingest_rejections == []
