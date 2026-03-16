import freshquant.order_management.ingest.xt_reports as xt_reports_module
from freshquant.order_management.ingest.xt_reports import (
    OrderManagementXtIngestService,
)
from freshquant.order_management.tracking.service import OrderTrackingService


class FakeRuntimeLogger:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(dict(event))
        return True


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

    def find_order_by_request_id(self, request_id):
        for order in self.orders:
            if order["request_id"] == request_id:
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


def test_ingest_trade_report_emits_runtime_events():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_xt_1",
            "request_id": "req_xt_1",
            "trace_id": "trc_xt_1",
            "intent_id": "int_xt_1",
        }
    )
    repository.update_order(
        "ord_xt_1",
        {"broker_order_id": "90001", "state": "SUBMITTED"},
    )
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )

    service.ingest_trade_report(
        {
            "internal_order_id": "ord_xt_1",
            "broker_order_id": "90001",
            "broker_trade_id": "T-90001",
            "symbol": "000001",
            "side": "buy",
            "quantity": 300,
            "price": 10.0,
            "trade_time": 1710000000,
            "date": 20240102,
            "time": "09:31:00",
            "source": "xt_trade_callback",
            "trace_id": "trc_xt_1",
            "intent_id": "int_xt_1",
            "request_id": "req_xt_1",
        },
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert [event["node"] for event in runtime_logger.events] == [
        "report_receive",
        "trade_match",
    ]
    assert runtime_logger.events[0]["trace_id"] == "trc_xt_1"
    assert runtime_logger.events[1]["internal_order_id"] == "ord_xt_1"


def test_ingest_order_report_emits_runtime_events():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_xt_2",
            "request_id": "req_xt_2",
            "trace_id": "trc_xt_2",
            "intent_id": "int_xt_2",
        }
    )
    repository.update_order(
        "ord_xt_2",
        {"broker_order_id": "90002", "state": "SUBMITTED"},
    )
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )

    service.ingest_order_report(
        {
            "order_id": 90002,
            "stock_code": "000001.SZ",
            "order_time": 1710000000,
            "order_status": 54,
        }
    )

    assert [event["node"] for event in runtime_logger.events] == [
        "report_receive",
        "order_match",
    ]
    assert runtime_logger.events[0]["request_id"] == "req_xt_2"
    assert runtime_logger.events[1]["internal_order_id"] == "ord_xt_2"


def test_try_ingest_xt_trade_dict_emits_runtime_error_when_wrapper_catches_exception(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    monkeypatch.setattr(xt_reports_module, "_runtime_logger", runtime_logger)
    monkeypatch.setattr(
        xt_reports_module,
        "logger",
        type("Logger", (), {"exception": staticmethod(lambda *args, **kwargs: None)})(),
    )
    monkeypatch.setattr(
        xt_reports_module,
        "ingest_xt_trade_dict",
        lambda _report: (_ for _ in ()).throw(KeyError("traded_time")),
    )

    result = xt_reports_module.try_ingest_xt_trade_dict(
        {
            "trace_id": "trc_xt_raw_trade",
            "intent_id": "int_xt_raw_trade",
            "request_id": "req_xt_raw_trade",
            "internal_order_id": "ord_xt_raw_trade",
            "symbol": "000001",
            "source": "xt_trade_callback",
        }
    )

    assert result is None
    assert runtime_logger.events[-1]["node"] == "report_receive"
    assert runtime_logger.events[-1]["status"] == "error"
    assert runtime_logger.events[-1]["reason_code"] == "unexpected_exception"
    assert runtime_logger.events[-1]["payload"]["error_type"] == "KeyError"
    assert "traded_time" in runtime_logger.events[-1]["payload"]["error_message"]


def test_try_ingest_xt_order_dict_emits_runtime_error_when_wrapper_catches_exception(
    monkeypatch,
):
    runtime_logger = FakeRuntimeLogger()
    monkeypatch.setattr(xt_reports_module, "_runtime_logger", runtime_logger)
    monkeypatch.setattr(
        xt_reports_module,
        "logger",
        type("Logger", (), {"exception": staticmethod(lambda *args, **kwargs: None)})(),
    )
    monkeypatch.setattr(
        xt_reports_module,
        "ingest_xt_order_dict",
        lambda _report: (_ for _ in ()).throw(RuntimeError("bad order report")),
    )

    result = xt_reports_module.try_ingest_xt_order_dict(
        {
            "trace_id": "trc_xt_raw_order",
            "intent_id": "int_xt_raw_order",
            "request_id": "req_xt_raw_order",
            "internal_order_id": "ord_xt_raw_order",
            "symbol": "000001",
            "source": "xt_order_callback",
        }
    )

    assert result is None
    assert runtime_logger.events[-1]["node"] == "report_receive"
    assert runtime_logger.events[-1]["status"] == "error"
    assert runtime_logger.events[-1]["reason_code"] == "unexpected_exception"
    assert runtime_logger.events[-1]["payload"]["error_type"] == "RuntimeError"
    assert runtime_logger.events[-1]["payload"]["error_message"] == "bad order report"
