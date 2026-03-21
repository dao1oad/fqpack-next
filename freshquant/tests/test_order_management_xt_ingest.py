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
        self.order_events = []
        self.trade_facts = []
        self.buy_lots = []
        self.lot_slices = []
        self.sell_allocations = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        self.trade_facts.append(document)
        return document, True

    def find_order(self, internal_order_id):
        for order in self.orders:
            if order["internal_order_id"] == internal_order_id:
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


def _buy_report(broker_trade_id="T-100"):
    return {
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


def _sell_report(broker_trade_id="T-101"):
    return {
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


def test_trade_report_creates_trade_fact_buy_lot_and_slices():
    repository, ingest_service = _bootstrap_service()

    result = ingest_service.ingest_trade_report(
        _buy_report(),
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert len(repository.trade_facts) == 1
    assert result["buy_lot"]["original_quantity"] == 900
    assert len(result["lot_slices"]) == 4


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

    arranged_fills = build_arranged_fills_view(repository.list_open_slices("000001"))

    assert len(result["sell_allocations"]) == 2
    assert [(item["price"], item["quantity"]) for item in arranged_fills] == [
        (10.93, 200),
        (10.61, 200),
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
    assert len(repository.list_open_slices("000001")) == 4


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
