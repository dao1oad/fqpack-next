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
        self.broker_orders = []
        self.order_events = []
        self.trade_facts = []
        self.execution_fills = []
        self.buy_lots = []
        self.lot_slices = []
        self.sell_allocations = []
        self.position_entries = []
        self.entry_slices = []

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
            if order["request_id"] == request_id:
                return order
        return None

    def find_order_request(self, request_id):
        for request in self.order_requests:
            if request["request_id"] == request_id:
                return request
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

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
                return order
        return None

    def claim_broker_order_owner(self, document):
        existing = self.find_broker_order(document["broker_order_key"])
        if existing is None:
            saved = dict(document)
            self.broker_orders.append(saved)
            return saved, True
        for field in (
            "internal_order_id",
            "request_id",
            "broker_correlation_token",
            "account_id",
            "trading_day",
            "order_sysid",
            "broker_order_id",
            "symbol",
            "side",
            "source_type",
        ):
            if field in document:
                existing[field] = document.get(field)
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
            item for item in self.broker_orders if item["broker_order_key"] != old_key
        ]
        return target

    def list_execution_fills(self, *, broker_order_keys=None, **_kwargs):
        rows = list(self.execution_fills)
        if broker_order_keys is not None:
            allowed = set(broker_order_keys)
            rows = [item for item in rows if item.get("broker_order_key") in allowed]
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

    def replace_position_entry(self, document):
        for index, entry in enumerate(self.position_entries):
            if entry["entry_id"] == document["entry_id"]:
                self.position_entries[index] = dict(document)
                return document
        self.position_entries.append(dict(document))
        return document

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

    def replace_entry_slices_for_entry(self, entry_id, slices):
        self.entry_slices = [
            item for item in self.entry_slices if item["entry_id"] != entry_id
        ]
        self.entry_slices.extend(dict(item) for item in slices)
        return slices

    def list_trade_facts(self, symbol):
        return [dict(item) for item in self.trade_facts if item.get("symbol") == symbol]

    def list_exit_allocations_for_request(
        self, *, request_id=None, internal_order_id=None
    ):
        return []

    def sum_exit_allocations_for_request(
        self, *, request_id=None, internal_order_id=None
    ):
        return {"by_slice": {}, "by_entry": {}, "total": 0}


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
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )


def test_ingest_trade_report_emits_runtime_events(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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


def test_duplicate_trade_report_is_silent_in_runtime_observability(monkeypatch):
    _stub_ingest_side_effects(monkeypatch)
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_xt_dup_1",
            "request_id": "req_xt_dup_1",
            "trace_id": "trc_xt_dup_1",
            "intent_id": "int_xt_dup_1",
        }
    )
    repository.update_order(
        "ord_xt_dup_1",
        {"broker_order_id": "90003", "state": "SUBMITTED"},
    )
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )
    report = {
        "internal_order_id": "ord_xt_dup_1",
        "broker_order_id": "90003",
        "broker_trade_id": "T-90003",
        "symbol": "000001",
        "side": "buy",
        "quantity": 300,
        "price": 10.0,
        "trade_time": 1710000000,
        "date": 20240102,
        "time": "09:31:00",
        "source": "xt_trade_callback",
        "trace_id": "trc_xt_dup_1",
        "intent_id": "int_xt_dup_1",
        "request_id": "req_xt_dup_1",
    }

    service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )
    first_event_count = len(runtime_logger.events)
    service.ingest_trade_report(
        report,
        lot_amount=3000,
        grid_interval_lookup=lambda _symbol, _trade_fact: 1.03,
    )

    assert first_event_count == 2
    assert len(runtime_logger.events) == first_event_count


def test_ingest_order_report_emits_runtime_events():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
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
    correlation_token = repository.find_order("ord_xt_2")["broker_correlation_token"]
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
            "order_remark": correlation_token,
        }
    )

    assert [event["node"] for event in runtime_logger.events] == [
        "report_receive",
        "order_match",
    ]
    assert runtime_logger.events[0]["request_id"] == "req_xt_2"
    assert runtime_logger.events[1]["internal_order_id"] == "ord_xt_2"


def test_duplicate_order_snapshot_is_silent_in_runtime_observability():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_xt_dup_order_1",
            "request_id": "req_xt_dup_order_1",
            "trace_id": "trc_xt_dup_order_1",
            "intent_id": "int_xt_dup_order_1",
        }
    )
    repository.update_order(
        "ord_xt_dup_order_1",
        {"broker_order_id": "90012", "state": "SUBMITTED"},
    )
    correlation_token = repository.find_order("ord_xt_dup_order_1")[
        "broker_correlation_token"
    ]
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )
    report = {
        "order_id": 90012,
        "stock_code": "000001.SZ",
        "order_time": 1710000000,
        "order_status": 54,
        "order_remark": correlation_token,
    }

    service.ingest_order_report(report)
    first_event_count = len(runtime_logger.events)
    service.ingest_order_report(report)

    assert first_event_count == 2
    assert len(runtime_logger.events) == first_event_count


def test_unknown_order_snapshot_is_ignored_in_runtime_observability():
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=OrderTrackingService(repository=repository),
        runtime_logger=runtime_logger,
    )

    result = service.ingest_order_report(
        {
            "order_id": 99901,
            "stock_code": "000001.SZ",
            "order_time": 1710000000,
            "order_status": 54,
        }
    )

    assert result is None
    assert runtime_logger.events == []


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


def test_order_match_emits_ladder_terminal_reopen_result(monkeypatch):
    """#549 runtime：order_match 携带阶梯零成交终态重开结果与幂等键。"""

    ladder_calls = []

    class _FakeLadder:
        def on_buy_zero_fill_terminal(self, *, code, level_index, event_key):
            ladder_calls.append((code, level_index, event_key))
            return True

        def on_takeprofit_zero_fill_terminal(self, *, code, level, event_key):
            ladder_calls.append((code, level, event_key))
            return True

        def on_takeprofit_fill(self, *, code, level, event_key):
            return True

        def on_buy_line_trigger(self, *, code, level_index, event_key):
            return True

    monkeypatch.setattr(
        xt_reports_module,
        "_get_ladder_state",
        lambda: _FakeLadder(),
        raising=False,
    )
    runtime_logger = FakeRuntimeLogger()
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "ledger_intent": "base",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 300,
            "source": "strategy",
            "internal_order_id": "ord_xt_ladder_1",
            "request_id": "req_xt_ladder_1",
            "trace_id": "trc_xt_ladder_1",
            "intent_id": "int_xt_ladder_1",
            "strategy_context": {
                "guardian_buy_grid": {"path": "base_line", "grid_level": "BUY-2"},
            },
        }
    )
    service = OrderManagementXtIngestService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )

    service.ingest_order_report(
        {
            "internal_order_id": "ord_xt_ladder_1",
            "broker_order_id": 90010,
            "symbol": "000001",
            "side": "buy",
            "order_type": 23,
            "order_volume": 300,
            "order_price": 9.0,
            "order_status": 57,
            "order_time": 1710000600,
        }
    )

    order_match = next(
        event for event in runtime_logger.events if event["node"] == "order_match"
    )
    assert order_match["payload"]["state"] == "FAILED"
    ladder_payload = order_match["payload"]["ladder"]
    assert ladder_payload["processed"] is True
    assert ladder_payload["kind"] == "buy_line_reopen"
    assert ladder_payload["level_index"] == 1
    assert ladder_payload["event_key"] == "ladder_terminal:ord_xt_ladder_1"
    assert ladder_payload["result"]["ok"] is True
    assert ladder_payload["result"]["operation"] == "buy_zero_fill_terminal"
    assert ladder_calls == [("000001", 1, "ladder_terminal:ord_xt_ladder_1")]
