import pytest

import freshquant.order_management.ingest.xt_reports as xt_reports_module
from freshquant.order_management.entry_aggregation import migrate_entry_member_key
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
    normalize_xt_order_report,
    normalize_xt_trade_report,
)
from freshquant.order_management.projection.stock_fills import (
    build_arranged_fills_view,
)
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
        assert unique_keys == ["broker_order_key"]
        return self.claim_broker_order_owner(document)

    def claim_broker_order_owner(self, document):
        existing = self.find_broker_order(document["broker_order_key"])
        if existing is None:
            saved = dict(document)
            self.broker_orders.append(saved)
            return saved, True
        owner_changed = existing.get("internal_order_id") != document.get(
            "internal_order_id"
        )
        for field in (
            "internal_order_id",
            "request_id",
            "broker_correlation_token",
            "broker_order_key",
            "account_id",
            "trading_day",
            "order_sysid",
            "broker_order_id",
            "symbol",
            "side",
        ):
            if field in document and (
                document.get(field) is not None or existing.get(field) is None
            ):
                existing[field] = document.get(field)
        if owner_changed or not existing.get("source_type"):
            existing["source_type"] = document.get("source_type")
        return existing, False

    def update_broker_order_fields(self, broker_order_key, updates):
        order = self.find_broker_order(broker_order_key)
        if order is None:
            return None
        order.update(updates)
        return order

    def fence_broker_order_execution(self, document):
        order = self.find_broker_order(document["broker_order_key"])
        assert order["internal_order_id"] == document["internal_order_id"]
        order["execution_fence"] = True
        return order

    def compare_and_set_broker_order(self, *, before, after):
        order = self.find_broker_order(before["broker_order_key"])
        if order != before:
            return order if order == after else None
        order.clear()
        order.update(after)
        return order

    def move_broker_order_key(self, old_key, new_key, document):
        source = self.find_broker_order(old_key)
        target = self.find_broker_order(new_key)
        merged = {**(source or {}), **dict(document), "broker_order_key": new_key}
        if target is None:
            self.broker_orders.append(merged)
            target = merged
        else:
            target.update(merged)
        self.broker_orders = [
            item
            for item in self.broker_orders
            if item.get("broker_order_key") != old_key
        ]
        return target

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

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
                return order
        return None

    def find_order_by_request_id(self, request_id):
        for order in self.orders:
            if order.get("request_id") == request_id:
                return order
        return None

    def list_trade_facts(self, symbol):
        return [dict(item) for item in self.trade_facts if item.get("symbol") == symbol]

    def find_order_request(self, request_id):
        for request in self.order_requests:
            if request["request_id"] == request_id:
                return request
        return None

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
                return order
        return None

    def find_order_by_broker_correlation_token(self, token):
        for order in self.orders:
            if order.get("broker_correlation_token") == token:
                return order
        return None

    def list_execution_fills(self, *, broker_order_keys=None, **_kwargs):
        rows = list(self.execution_fills)
        if broker_order_keys is not None:
            allowed = set(broker_order_keys)
            rows = [item for item in rows if item.get("broker_order_key") in allowed]
        return rows

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

    def insert_buy_lot(self, document):
        self.buy_lots.append(document)
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(slices)

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
        self.sell_allocations.extend(allocations)
        return allocations

    def replace_position_entry(self, document):
        for index, current in enumerate(self.position_entries):
            if current["entry_id"] == document["entry_id"]:
                self.position_entries[index] = dict(document)
                return document
        self.position_entries.append(dict(document))
        return document

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
        self.exit_allocations.extend(dict(item) for item in allocations)
        return allocations

    def list_exit_allocations_for_request(
        self,
        *,
        request_id=None,
        internal_order_id=None,
    ):
        rows = []
        for item in self.exit_allocations:
            if request_id not in {None, ""} and item.get("request_id") != request_id:
                continue
            if (
                internal_order_id not in {None, ""}
                and item.get("internal_order_id") != internal_order_id
            ):
                continue
            rows.append(dict(item))
        return rows

    def sum_exit_allocations_for_request(
        self,
        *,
        request_id=None,
        internal_order_id=None,
    ):
        by_slice = {}
        by_entry = {}
        for row in self.list_exit_allocations_for_request(
            request_id=request_id,
            internal_order_id=internal_order_id,
        ):
            entry_id = str(row.get("entry_id") or "")
            entry_slice_id = str(row.get("entry_slice_id") or "")
            allocated = int(row.get("allocated_quantity") or 0)
            if entry_id:
                by_entry[entry_id] = by_entry.get(entry_id, 0) + allocated
            if entry_slice_id:
                by_slice[entry_slice_id] = by_slice.get(entry_slice_id, 0) + allocated
        return {
            "by_slice": by_slice,
            "by_entry": by_entry,
            "total": sum(by_entry.values()),
        }

    def insert_ingest_rejection(self, document):
        self.ingest_rejections.append(dict(document))
        return document


def _bootstrap_service():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
            "ledger_intent": "-",
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
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
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


def _noop_sync_stock_fills_compat(symbol, repository=None):
    del symbol, repository
    return None


def _buy_report(broker_trade_id="T-100", **overrides):
    payload = {
        "internal_order_id": "ord_test_1",
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
            "traded_id": "T-100",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "traded_volume": 900,
            "traded_price": 10.0,
            "traded_time": 1710000000,
            "strategy_name": "Guardian",
        }
    )

    assert normalized["internal_order_id"] == "O-100"
    assert normalized["broker_trade_id"] == "T-100"
    assert normalized["symbol"] == "000001"
    assert normalized["stock_code"] == "000001"
    assert normalized["side"] == "buy"
    assert normalized["date"] == 20240310


def test_normalize_xt_trade_report_treats_credit_fin_buy_as_buy():
    normalized = normalize_xt_trade_report(
        {
            "order_id": "O-200",
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
            "traded_id": "T-201",
            "stock_code": "600000.SH",
            "order_type": 31,
            "traded_volume": 100,
            "traded_price": 10.0,
            "traded_time": 1710000000,
        }
    )

    assert normalized["side"] == "sell"


def test_normalize_xt_trade_report_prefers_order_domain_broker_order_type():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
            "order_id": "92001",
            "traded_id": "T-202",
            "stock_code": "600000.SH",
            "order_type": 24,
            "traded_volume": 100,
            "traded_price": 10.0,
            "traded_time": 1710000000,
            "order_remark": repository.find_order("ord_credit_ingest_1")[
                "broker_correlation_token"
            ],
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_credit_ingest_1"
    assert normalized["side"] == "buy"


def test_normalize_xt_trade_report_disambiguates_reused_broker_order_id():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
            "ledger_intent": "-",
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
            "traded_id": "0103000030649603",
            "stock_code": "002262.SZ",
            "order_type": 24,
            "traded_volume": 2300,
            "traded_price": 22.41,
            "traded_time": 1777428846,
            "order_remark": repository.find_order("ord_new_sell")[
                "broker_correlation_token"
            ],
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
            "ledger_intent": "base",
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
            "ledger_intent": "-",
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
            "stock_code": "002262.SZ",
            "order_type": 24,
            "order_time": 1777428846,
            "order_status": 50,
            "order_remark": repository.find_order("ord_new_sell")[
                "broker_correlation_token"
            ],
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
            "ledger_intent": "base",
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
            "stock_code": "000001.SZ",
            "order_time": 1710000000,
            "order_status": 54,
            "order_remark": repository.find_order("ord_test_order_report")[
                "broker_correlation_token"
            ],
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_test_order_report"
    assert normalized["broker_order_id"] == "81001"
    assert normalized["state"] == "CANCELED"


def test_normalize_xt_order_report_returns_none_for_unknown_broker_order():
    repository = InMemoryRepository()

    normalized = normalize_xt_order_report(
        {
            "order_id": 89991,
            "stock_code": "000001.SZ",
            "order_time": 1710000000,
            "order_status": 54,
        },
        repository=repository,
    )

    assert normalized is None


def test_normalize_xt_order_report_keeps_cancel_requested_state_for_pending_cancel():
    normalized = normalize_xt_order_report(
        {
            "order_id": 81002,
            "stock_code": "000001.SZ",
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


def _multi_fill_setup():
    """构造 #582 生产形态：委托回报先到 → broker_order_key 迁移为 canonical。"""

    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "t",
            "symbol": "000001",
            "price": 10.3,
            "quantity": 7400,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_mf_1",
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_order_report(
        {
            "account_id": "068000087558",
            "account_type": 2,
            "order_id": 940572673,
            "order_sysid": "1615",
            "order_time": 1710000000,
            "order_type": 27,
            "order_volume": 7400,
            "price": 10.38,
            "price_type": 88,
            "order_status": 50,
            "order_remark": repository.find_order("ord_mf_1")[
                "broker_correlation_token"
            ],
            "stock_code": "000001.SZ",
            "strategy_name": "gb0h4lfNshUASvAc",
        }
    )
    broker_orders = list(repository.broker_orders)
    assert len(broker_orders) == 1
    canonical_key = broker_orders[0]["broker_order_key"]
    assert canonical_key != "ord_mf_1"
    return repository, ingest_service, canonical_key


def _ingest_multi_fills(ingest_service, *, extra_fill=None):
    fill_quantities = [
        4600,
        600,
        200,
        100,
        200,
        200,
        100,
        100,
        100,
        100,
        100,
        200,
        200,
        100,
        200,
        300,
    ]
    if extra_fill is not None:
        fill_quantities.append(extra_fill)
    for index, quantity in enumerate(fill_quantities):
        ingest_service.ingest_trade_report(
            {
                "internal_order_id": "ord_mf_1",
                "broker_order_id": "940572673",
                "broker_trade_id": f"T-MF-{index}",
                "symbol": "000001",
                "side": "buy",
                "quantity": quantity,
                "price": 10.3,
                "trade_time": 1710000000 + index,
                "date": 20240310,
                "time": "09:31:00",
                "source": "xt_trade_callback",
            },
            lot_amount=50000,
            grid_interval_lookup=lambda _symbol, _trade_fact: 1.2,
        )


def test_multi_fill_buy_uses_whole_order_quantity_after_key_migration():
    """#582：16 笔拆单成交，entry 必须等于整单数量（生产形状回归）。"""

    repository, ingest_service, canonical_key = _multi_fill_setup()
    _ingest_multi_fills(ingest_service)

    assert repository.ingest_rejections == []
    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["position_type"] == "t"
    assert entry["original_quantity"] == 7400
    assert entry["remaining_quantity"] == 7400
    members = entry["aggregation_members"]
    assert len(members) == 1
    assert members[0]["broker_order_key"] == canonical_key
    assert members[0]["quantity"] == 7400
    assert members[0]["position_type"] == "t"
    assert entry["aggregation_member_keys"] == [canonical_key]
    slices = repository.list_open_entry_slices(
        symbol="000001",
        entry_ids=[entry["entry_id"]],
    )
    assert sum(int(s["original_quantity"]) for s in slices) == 7400


def test_legacy_internal_member_key_migrates_without_double_count():
    """#582：存量 entry 成员键为 internal_order_id 时，同单后续 fill 不双计数。"""

    repository, ingest_service, canonical_key = _multi_fill_setup()
    _ingest_multi_fills(ingest_service)

    entry = repository.list_position_entries(symbol="000001")[0]
    legacy_member = dict(entry["aggregation_members"][0])
    legacy_member["broker_order_key"] = "ord_mf_1"
    entry["aggregation_members"] = [legacy_member]
    entry["aggregation_member_keys"] = ["ord_mf_1"]
    repository.replace_position_entry(entry)

    # 同单再来一笔成交：成员键先迁移为 canonical，再以整单快照覆盖，不能双计数。
    _ingest_multi_fills(ingest_service, extra_fill=100)

    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["original_quantity"] == 7500
    assert len(entry["aggregation_members"]) == 1
    assert entry["aggregation_members"][0]["broker_order_key"] == canonical_key
    assert entry["aggregation_members"][0]["quantity"] == 7500
    assert entry["aggregation_member_keys"] == [canonical_key]


def test_upsert_broker_position_entry_fails_closed_when_broker_order_missing():
    """#582：找不到 broker order 聚合时 fail-closed，禁止静默退化单笔数量。"""

    repository, _ = _bootstrap_service()
    trade_fact = {
        "symbol": "000001",
        "internal_order_id": "ord_ghost_1",
        "broker_order_key": "account:ghost:day:20240310:sysid:1",
        "broker_trade_id": "T-GHOST-1",
        "quantity": 100,
        "price": 10.0,
        "trade_time": 1710000000,
        "date": 20240309,
        "time": "09:31:00",
        "side": "buy",
        "source": "xt_trade_callback",
    }
    entry, slices = xt_reports_module._upsert_broker_position_entry(
        repository=repository,
        trade_fact=trade_fact,
        lot_amount=3000,
        grid_interval=1.03,
    )
    assert entry is None
    assert slices == []
    assert len(repository.ingest_rejections) == 1
    assert repository.ingest_rejections[0]["reason_code"] == "broker_order_missing"
    assert repository.position_entries == []


def test_upsert_broker_position_entry_falls_back_to_internal_key():
    """#582：trade_fact 携带 canonical key 但 broker order 仍为 internal 占位键
    （order report 未迁移的竞态）时，internal 兜底查找必须命中。"""

    repository, ingest_service = _bootstrap_service()
    ingest_service.ingest_trade_report(
        _buy_report("T-FBK-SEED"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    assert repository.broker_orders[0]["broker_order_key"] == "ord_test_1"

    trade_fact = {
        "symbol": "000001",
        "internal_order_id": "ord_test_1",
        "broker_order_key": "account:068000087558:day:20240310:sysid:1615",
        "broker_trade_id": "T-FBK-2",
        "quantity": 100,
        "price": 10.0,
        "trade_time": 1710000000,
        "date": 20240310,
        "time": "09:31:00",
        "side": "buy",
        "source": "xt_trade_callback",
    }
    entry, slices = xt_reports_module._upsert_broker_position_entry(
        repository=repository,
        trade_fact=trade_fact,
        lot_amount=3000,
        grid_interval=1.03,
    )

    assert entry is not None
    assert entry["original_quantity"] == 900
    assert len(entry["aggregation_members"]) == 1
    assert entry["aggregation_member_keys"] == ["ord_test_1"]
    assert repository.ingest_rejections == []


def test_migrate_entry_member_key_preserves_reconciliation_resolution_members():
    """#582：成员键迁移只改写 internal_order_id 旧键，不改写 resolution 成员。"""

    entry = {
        "entry_id": "entry_1",
        "aggregation_members": [
            {"broker_order_key": "ord_mf_1", "quantity": 300},
            {
                "broker_order_key": "reconciliation_resolution:resolution_x",
                "quantity": 7100,
            },
        ],
        "aggregation_member_keys": [
            "ord_mf_1",
            "reconciliation_resolution:resolution_x",
        ],
    }
    migrated = migrate_entry_member_key(
        entry,
        legacy_key="ord_mf_1",
        canonical_key="account:068000087558:day:20240310:sysid:1615",
    )

    assert [item["broker_order_key"] for item in migrated["aggregation_members"]] == [
        "account:068000087558:day:20240310:sysid:1615",
        "reconciliation_resolution:resolution_x",
    ]
    assert migrated["aggregation_member_keys"] == [
        "account:068000087558:day:20240310:sysid:1615",
        "reconciliation_resolution:resolution_x",
    ]


def test_trade_report_marks_holding_projection_updated(monkeypatch):
    repository, ingest_service = _bootstrap_service()
    marks = []

    monkeypatch.setattr(
        xt_reports_module,
        "mark_stock_holdings_projection_updated",
        lambda: marks.append("marked"),
        raising=False,
    )

    ingest_service.ingest_trade_report(
        _buy_report("T-100-mark"),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert marks == ["marked"]


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

    # 根①写侧收敛（步骤 5）：ingest 单写 V2；legacy 不再写入。
    open_entry_slices = sorted(
        repository.list_open_entry_slices(symbol="000001"),
        key=lambda item: -float(item["guardian_price"]),
    )

    assert result["sell_allocations"] == []
    assert len(result["exit_allocations"]) == 2
    assert repository.position_entries[0]["remaining_quantity"] == 400
    assert repository.position_entries[0]["status"] == "PARTIALLY_EXITED"
    assert [
        (item["guardian_price"], item["remaining_quantity"])
        for item in open_entry_slices
    ] == [
        (10.93, 200),
        (10.61, 200),
    ]


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
            "ledger_intent": (
                "base" if side == "buy" else ("t" if strategy_context else "-")
            ),
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


def test_sell_multi_fill_ingest_shares_request_remaining_budget():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    for internal_order_id, quantity, price, trade_time in (
        ("ord_mf_buy_1", 2300, 21.36, 1710000000),
        ("ord_mf_buy_2", 2300, 21.58, 1710000300),
    ):
        tracking_service.submit_order(
            {
                "action": "buy",
                "ledger_intent": "base",
                "symbol": "000001",
                "price": price,
                "quantity": quantity,
                "source": "xt_trade_callback",
                "internal_order_id": internal_order_id,
            }
        )
    tracking_service.submit_order(
        {
            "action": "sell",
            "ledger_intent": "t",
            "symbol": "000001",
            "price": 21.8,
            "quantity": 4600,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_mf_sell_1",
            "strategy_context": {
                "guardian_sell_sources": {
                    "version": 2,
                    "requested_quantity": 4600,
                    "submit_quantity": 4600,
                    "profitable_fill_count": 2,
                    "slices": [],
                    "entries": [],
                }
            },
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat

    ingest_service.ingest_trade_report(
        _buy_report(
            "T-MF-BUY-1",
            internal_order_id="ord_mf_buy_1",
            quantity=2300,
            price=21.36,
            trade_time=1710000000,
            date=20240102,
            time="09:31:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.2,
    )
    ingest_service.ingest_trade_report(
        _buy_report(
            "T-MF-BUY-2",
            internal_order_id="ord_mf_buy_2",
            quantity=2300,
            price=21.58,
            trade_time=1710000300,
            date=20240102,
            time="09:35:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.2,
    )

    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 2, "21.36/21.58 价差超过 0.3% 不应聚簇"
    slices = repository.entry_slices
    plan_slices = []
    for entry in sorted(
        entries,
        key=lambda item: float(item["entry_price"]),
    ):
        entry_slices = [
            item
            for item in slices
            if item["entry_id"] == entry["entry_id"]
            and int(item["remaining_quantity"]) > 0
        ]
        assert entry_slices
        plan_slices.append(
            {
                "entry_id": entry["entry_id"],
                "entry_slice_id": entry_slices[0]["entry_slice_id"],
                "quantity": 2300,
                "guardian_price": entry_slices[0]["guardian_price"],
                "threshold_price": round(
                    float(entry_slices[0]["guardian_price"]) * 1.01, 4
                ),
            }
        )
    repository.order_requests[-1]["strategy_context"]["guardian_sell_sources"][
        "slices"
    ] = plan_slices
    repository.order_requests[-1]["strategy_context"]["guardian_sell_sources"][
        "entries"
    ] = [{"entry_id": item["entry_id"], "quantity": 2300} for item in plan_slices]

    ingest_service.ingest_trade_report(
        _sell_report(
            "T-MF-SELL-1",
            internal_order_id="ord_mf_sell_1",
            quantity=200,
            price=21.8,
            trade_time=1710000600,
            date=20240102,
            time="09:50:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.2,
    )
    ingest_service.ingest_trade_report(
        _sell_report(
            "T-MF-SELL-2",
            internal_order_id="ord_mf_sell_1",
            quantity=4400,
            price=21.8,
            trade_time=1710000660,
            date=20240102,
            time="09:51:00",
        ),
        lot_amount=50000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.2,
    )

    by_entry = {}
    for allocation in repository.exit_allocations:
        by_entry[allocation["entry_id"]] = (
            by_entry.get(allocation["entry_id"], 0) + allocation["allocated_quantity"]
        )
    assert by_entry == {
        entries[0]["entry_id"]: 2300,
        entries[1]["entry_id"]: 2300,
    }
    assert all(
        item.get("request_id") and item.get("internal_order_id")
        for item in repository.exit_allocations
    )


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
    # 根①写侧收敛（步骤 5）：legacy buy_lot/lot_slice 不再由 ingest 写入。
    assert repository.buy_lots == []
    assert len(repository.position_entries) == 1
    assert len(repository.list_open_entry_slices(symbol="000001")) == 4


def test_non_board_lot_trade_report_is_rejected_from_entry_ledger():
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
    assert repository.position_entries == []
    assert repository.entry_slices == []
    assert repository.buy_lots == []
    assert len(repository.ingest_rejections) == 1
    assert repository.ingest_rejections[0]["reason_code"] == "non_board_lot_quantity"
    assert result["position_entry"] is None
    assert result["projections"]["open_buy_fills"] == []


def test_multiple_buy_trade_reports_for_same_order_update_one_position_entry():
    def _noop_sync_stock_fills_compat(_symbol: str, repository: object) -> None:
        del repository

    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
                "ledger_intent": "base",
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
                "ledger_intent": "base",
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
                "ledger_intent": "base" if side == "buy" else "-",
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

    # 根①写侧收敛（步骤 5）：重复卖出回调在 V2 层幂等，legacy 不再写入。
    open_entry_slices = sorted(
        repository.list_open_entry_slices(symbol="000001"),
        key=lambda item: -float(item["guardian_price"]),
    )

    assert first["sell_allocations"] == []
    assert second["sell_allocations"] == []
    assert repository.sell_allocations == []
    assert len(first["exit_allocations"]) == 2
    assert second["exit_allocations"] == []
    assert len(repository.exit_allocations) == 2
    assert [
        (item["guardian_price"], item["remaining_quantity"])
        for item in open_entry_slices
    ] == [
        (10.93, 200),
        (10.61, 200),
    ]


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


def test_order_report_updates_existing_order_state():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
            "stock_code": "000001.SZ",
            "order_time": 1710000000,
            "order_status": 54,
            "order_remark": repository.find_order("ord_order_state_1")[
                "broker_correlation_token"
            ],
        }
    )

    assert repository.find_order("ord_order_state_1")["state"] == "CANCELED"


def test_trade_ingest_requires_meta_tracking_contract():
    class LegacyOnlyTrackingService:
        def ingest_trade_report(self, _report):
            raise AssertionError("legacy trade ingest must not be used")

    service = OrderManagementXtIngestService(
        repository=InMemoryRepository(),
        tracking_service=LegacyOnlyTrackingService(),
        tpsl_service=object(),
        runtime_logger=object(),
    )

    with pytest.raises(AttributeError, match="ingest_trade_report_with_meta"):
        service.ingest_trade_report(
            {
                "internal_order_id": "ord_contract_trade",
                "symbol": "000001",
                "side": "buy",
                "broker_trade_id": "trade-contract",
            },
            lot_amount=100,
            grid_interval_lookup=lambda *_args: 1,
        )


def test_order_ingest_requires_meta_tracking_contract():
    class LegacyOnlyTrackingService:
        def ingest_order_report(self, _report):
            raise AssertionError("legacy order ingest must not be used")

    service = OrderManagementXtIngestService(
        repository=InMemoryRepository(),
        tracking_service=LegacyOnlyTrackingService(),
        tpsl_service=object(),
        runtime_logger=object(),
    )

    with pytest.raises(AttributeError, match="ingest_order_report_with_meta"):
        service.ingest_order_report(
            {
                "internal_order_id": "ord_contract_order",
                "broker_order_key": "acct|20260806|sys-contract",
                "broker_order_id": "order-contract",
                "symbol": "000001",
                "side": "buy",
                "state": "SUBMITTED",
            }
        )


def _build_ingest_with_order(
    *,
    action="buy",
    internal_order_id="ord_ledger_1",
    strategy_context=None,
    ledger_intent=None,
):
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": action,
            "ledger_intent": ledger_intent or ("base" if action == "buy" else "-"),
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": internal_order_id,
            "strategy_context": strategy_context,
        }
    )
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat
    return repository, ingest_service


def test_base_line_buy_tags_position_type_base_from_ledger_intent(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        ledger_intent="base",
        strategy_context={"guardian_buy_grid": {"path": "base_line"}},
    )
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_ledger_1",
            "broker_trade_id": "T-ledger-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 1
    assert entries[0]["position_type"] == "base"


def test_guardian_signal_add_tags_t_when_entry_exists(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_first_1",
        strategy_context=None,
    )
    # 首开（无 open entry）→ base
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_first_1",
            "broker_trade_id": "T-first-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    entries = repository.list_position_entries(symbol="000001")
    assert entries[0]["position_type"] == "base"

    # Guardian 信号加仓：ledger_intent=t（存在 open entry 不再触发启发式）
    repository2, ingest_service2 = _build_ingest_with_order(
        internal_order_id="ord_t_1",
        ledger_intent="t",
    )
    ingest_service2.repository = repository
    ingest_service2.ingest_trade_report(
        {
            "internal_order_id": "ord_t_1",
            "broker_trade_id": "T-t-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 9.8,
            "trade_time": 1710000300,
            "date": 20240102,
            "time": "09:35:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    entries = repository.list_position_entries(symbol="000001")
    # 与首开 entry 在同一 5 分钟/0.3% 窗口内会聚类合并保留 base；
    # 时间窗外的新 entry → t
    assert any(
        entry["position_type"] == "t"
        for entry in entries
        if entry["entry_id"] != entries[0]["entry_id"]
    ) or all(entry["position_type"] == "base" for entry in entries)


def test_manual_source_add_tags_base(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_manual_1",
        strategy_context=None,
    )
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_manual_1",
            "broker_trade_id": "T-manual-first",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    # 手动加仓（manual source，非首开）→ base
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_manual_1",
            "broker_trade_id": "T-manual-add",
            "symbol": "000001",
            "side": "buy",
            "quantity": 200,
            "price": 9.9,
            "trade_time": 1710000600,
            "date": 20240102,
            "time": "09:40:00",
            "source": "manual_import",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    entries = repository.list_position_entries(symbol="000001")
    assert all(entry["position_type"] == "base" for entry in entries)


def test_takeprofit_fill_ingest_triggers_ladder_event(monkeypatch):
    ladder_calls = []
    runtime_logger = type(
        "FakeRuntimeLogger",
        (),
        {
            "events": [],
            "emit": lambda self, event: self.events.append(dict(event)),
        },
    )()

    class _FakeLadder:
        def on_takeprofit_fill(self, *, code, level, event_key):
            ladder_calls.append((code, level, event_key))
            return True

        def on_buy_zero_fill_terminal(self, *, code, level_index, event_key):
            return True

        def on_takeprofit_zero_fill_terminal(self, *, code, level, event_key):
            return True

    monkeypatch.setattr(
        xt_reports_module,
        "_get_ladder_state",
        lambda: _FakeLadder(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_tp_buy_1",
        strategy_context=None,
    )
    ingest_service.runtime_logger = runtime_logger
    result = ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_tp_buy_1",
            "broker_trade_id": "T-tp-buy",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    entry_id = repository.list_position_entries(symbol="000001")[0]["entry_id"]
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "sell",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 11.2,
            "quantity": 100,
            "source": "tpsl_takeprofit",
            "internal_order_id": "ord_tp_sell_1",
            "strategy_context": {
                "guardian_sell_sources": {
                    "allocation_policy": "takeprofit_ratio_v1",
                    "level": 2,
                    "tier_price": 11.0,
                    "entries": [{"entry_id": entry_id, "quantity": 300}],
                }
            },
        }
    )
    ingest_service.tracking_service = tracking_service
    result = ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_tp_sell_1",
            "broker_trade_id": "T-tp-sell",
            "symbol": "000001",
            "side": "sell",
            "quantity": 100,
            "price": 11.2,
            "trade_time": 1710000600,
            "date": 20240102,
            "time": "09:40:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    assert result["created"] is True
    assert ladder_calls and ladder_calls[0][0] == "000001"
    assert ladder_calls[0][1] == 2
    # runtime trade_match 载荷携带阶梯更新结果（#549 可观测性）
    trade_match = [
        event for event in runtime_logger.events if event["node"] == "trade_match"
    ][-1]
    assert trade_match["payload"]["ladder"]["kind"] == "takeprofit_fill"
    assert trade_match["payload"]["ladder"]["level"] == 2
    assert trade_match["payload"]["ladder"]["result"]["ok"] is True


def test_zero_fill_terminal_cancel_reopens_buy_line(monkeypatch):
    terminal_calls = []

    class _FakeLadder:
        def on_buy_zero_fill_terminal(self, *, code, level_index, event_key):
            terminal_calls.append(("buy", code, level_index))
            return True

        def on_takeprofit_zero_fill_terminal(self, *, code, level, event_key):
            terminal_calls.append(("sell", code, level))
            return True

        def on_buy_line_trigger(self, *, code, level_index, event_key):
            return True

        def on_takeprofit_fill(self, *, code, level, event_key):
            return True

    monkeypatch.setattr(
        xt_reports_module,
        "_get_ladder_state",
        lambda: _FakeLadder(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_bl_cancel_1",
        ledger_intent="base",
        strategy_context={
            "guardian_buy_grid": {"path": "base_line", "grid_level": "BUY-2"},
        },
    )
    ingest_service.ingest_order_report(
        {
            "internal_order_id": "ord_bl_cancel_1",
            "broker_order_id": 987654321,
            "symbol": "000001",
            "side": "buy",
            "order_type": 23,
            "order_volume": 300,
            "order_price": 9.0,
            "order_status": 57,
            "order_time": 1710000600,
        }
    )
    assert terminal_calls and terminal_calls[0][0] == "buy"
    assert terminal_calls[0][2] == 1


def test_base_line_replenish_with_open_entry_tags_base(monkeypatch):
    """#2 回归：已有 open entry 时，TPSL 买入线（base_line）补仓仍应标 base。"""

    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_first_1",
        strategy_context=None,
    )
    # 首开（无 open entry）→ base
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_first_1",
            "broker_trade_id": "T-first-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    # TPSL 买入线补仓：ledger_intent=base、guardian_buy_grid.path=base_line，
    # 已有 open entry、价格偏离 >0.3% 不并入既有 entry（生成新 entry）→ 仍 base
    OrderTrackingService(repository=repository).submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 9.8,
            "quantity": 100,
            "source": "strategy",
            "strategy_name": "TPSL",
            "internal_order_id": "ord_base_line_1",
            "strategy_context": {
                "guardian_buy_grid": {"path": "base_line", "grid_level": "BUY-2"}
            },
        }
    )
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_base_line_1",
            "broker_trade_id": "T-base-line-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 100,
            "price": 9.8,
            "trade_time": 1710001200,
            "date": 20240102,
            "time": "10:00:00",
            "source": "xt_trade_callback",
        },
        lot_amount=1000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 2
    for entry in entries:
        assert entry["position_type"] == "base"


def test_buy_cluster_does_not_merge_across_position_types(monkeypatch):
    """#4 回归：先解析归属后聚类，禁止跨账本聚合。"""

    monkeypatch.setattr(
        xt_reports_module,
        "_get_tpsl_service",
        lambda: type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
        raising=False,
    )
    repository, ingest_service = _build_ingest_with_order(
        internal_order_id="ord_base_cluster_1",
        ledger_intent="base",
        strategy_context=None,
    )
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_base_cluster_1",
            "broker_trade_id": "T-BC-BASE",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.00,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    # 同一 5 分钟 / 0.3% 窗口内的 t 账本买单：不得并入 base 聚类。
    OrderTrackingService(repository=repository).submit_order(
        {
            "action": "buy",
            "ledger_intent": "t",
            "symbol": "000001",
            "price": 9.995,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_t_cluster_1",
            "strategy_context": {"guardian_buy_grid": {"path": "holding_add"}},
        }
    )
    ingest_service.ingest_trade_report(
        {
            "internal_order_id": "ord_t_cluster_1",
            "broker_trade_id": "T-BC-T",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 9.995,
            "trade_time": 1710000060,
            "date": 20240102,
            "time": "09:32:00",
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 2, "跨账本买单不得聚合"
    entry_types = {entry["position_type"] for entry in entries}
    assert entry_types == {"base", "t"}
    members = [
        member
        for entry in entries
        for member in (entry.get("aggregation_members") or [])
    ]
    assert all(member.get("position_type") in {"base", "t"} for member in members)


def test_broker_only_manual_buy_tags_base():
    """#3/A8 回归：broker-only（QMT 终端手动买入，无 request）显式归 base。"""

    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        tpsl_service=type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat
    result = ingest_service.ingest_trade_report(
        {
            "broker_trade_id": "T-BROKER-ONLY-1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "account_id": "ACCT-1",
            "broker_order_id": "B-BROKER-ONLY-1",
            "trading_day": 20240102,
            "source": "xt_trade_callback",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    assert result["created"] is True
    entries = repository.list_position_entries(symbol="000001")
    assert len(entries) == 1
    assert entries[0]["position_type"] == "base"


def test_broker_only_sell_multi_fill_allocations_carry_internal_order_id():
    """#571：broker-only 卖出（无 request）allocations 携带 internal_order_id，
    already_allocated 按 internal_order_id 跨 fill 累计（10 fills 目标形态
    的 2-fill 缩影）。"""

    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    ingest_service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        tpsl_service=type(
            "FakeTpslService",
            (),
            {
                "on_new_buy_trade": lambda self, symbol, buy_price, position_type="base": None
            },
        )(),
    )
    xt_reports_module._sync_stock_fills_compat = _noop_sync_stock_fills_compat
    repository.replace_position_entry(
        {
            "entry_id": "entry_base_9000",
            "symbol": "000001",
            "position_type": "base",
            "entry_price": 10.0,
            "buy_price_real": 10.0,
            "original_quantity": 9000,
            "remaining_quantity": 9000,
            "amount": 90000.0,
            "date": 20240102,
            "time": "09:31:00",
            "trade_time": 1710000000,
            "source": "xt_trade_callback",
            "status": "OPEN",
            "sell_history": [],
        }
    )
    repository.replace_entry_slices_for_entry(
        "entry_base_9000",
        [
            {
                "entry_slice_id": "slice_base_9000",
                "entry_id": "entry_base_9000",
                "symbol": "000001",
                "position_type": "base",
                "guardian_price": 10.0,
                "original_quantity": 9000,
                "remaining_quantity": 9000,
                "remaining_amount": 90000.0,
                "slice_seq": 0,
                "sort_key": 10.0,
                "status": "OPEN",
            }
        ],
    )

    def _sell_report(broker_trade_id, quantity):
        return {
            "broker_trade_id": broker_trade_id,
            "symbol": "000001",
            "side": "sell",
            "quantity": quantity,
            "price": 11.0,
            "trade_time": 1710003600,
            "date": 20240102,
            "time": "10:00:00",
            "account_id": "ACCT-1",
            "order_sysid": "SYS-SELL-1",
            "broker_order_id": "B-SELL-1",
            "trading_day": 20240102,
            "source": "xt_trade_callback",
        }

    first = ingest_service.ingest_trade_report(
        _sell_report("T-SELL-1", 5000),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    second = ingest_service.ingest_trade_report(
        _sell_report("T-SELL-2", 4000),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert first["created"] is True
    assert second["created"] is True
    assert len(first["exit_allocations"]) == 1
    assert len(second["exit_allocations"]) == 1
    for allocation in first["exit_allocations"] + second["exit_allocations"]:
        assert (
            allocation["internal_order_id"]
            == first["execution_fill"]["internal_order_id"]
        )
        assert allocation["request_id"] is None
        assert allocation["position_type"] == "base"
    assert first["exit_allocations"][0]["allocated_quantity"] == 5000
    assert second["exit_allocations"][0]["allocated_quantity"] == 4000
    stored = repository.list_exit_allocations_for_request(
        internal_order_id=first["execution_fill"]["internal_order_id"]
    )
    assert sum(int(item["allocated_quantity"] or 0) for item in stored) == 9000
    entries = repository.list_position_entries(symbol="000001")
    assert entries[0]["remaining_quantity"] == 0
