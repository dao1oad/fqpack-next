import freshquant.order_management.ingest.xt_reports as xt_reports_module
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

    def insert_ingest_rejection(self, document):
        self.ingest_rejections.append(dict(document))
        return document


def _bootstrap_service():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 900,
            "source": "xt_trade_callback",
            "internal_order_id": "ord_test_1",
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
        "internal_order_id": "ord_test_1",
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
        },
        repository=repository,
    )

    assert normalized["internal_order_id"] == "ord_credit_ingest_1"
    assert normalized["side"] == "buy"


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

    arranged_fills = build_arranged_fills_view(repository.list_open_slices("000001"))

    assert len(result["sell_allocations"]) == 2
    assert len(result["exit_allocations"]) == 2
    assert repository.position_entries[0]["remaining_quantity"] == 400
    assert repository.position_entries[0]["status"] == "PARTIALLY_EXITED"
    assert [(item["price"], item["quantity"]) for item in arranged_fills] == [
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

    arranged_fills = build_arranged_fills_view(repository.list_open_slices("000001"))

    assert len(first["sell_allocations"]) == 2
    assert second["sell_allocations"] == []
    assert len(repository.sell_allocations) == 2
    assert [(item["price"], item["quantity"]) for item in arranged_fills] == [
        (10.93, 200),
        (10.61, 200),
    ]


def test_order_report_updates_existing_order_state():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
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
        }
    )

    assert repository.find_order("ord_order_state_1")["state"] == "CANCELED"
