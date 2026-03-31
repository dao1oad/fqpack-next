import freshquant.order_management.ingest.xt_reports as xt_reports_module
import freshquant.order_management.reconcile.service as reconcile_service_module
from freshquant.order_management.reconcile.service import ExternalOrderReconcileService
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
        self.reconciliation_gaps = []
        self.reconciliation_resolutions = []
        self.position_entries = []
        self.entry_slices = []
        self.exit_allocations = []

    def insert_order_request(self, document):
        self.order_requests.append(document)
        return document

    def find_order_request(self, request_id):
        for request in self.order_requests:
            if request["request_id"] == request_id:
                return request
        return None

    def insert_order(self, document):
        self.orders.append(document)
        return document

    def insert_order_event(self, document):
        self.order_events.append(document)
        return document

    def upsert_broker_order(self, document, unique_keys):
        for existing in self.broker_orders:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                existing.update(document)
                return existing, False
        self.broker_orders.append(dict(document))
        return document, True

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
        self.execution_fills.append(dict(document))
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

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
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

    def replace_buy_lot(self, document):
        for index, buy_lot in enumerate(self.buy_lots):
            if buy_lot["buy_lot_id"] == document["buy_lot_id"]:
                self.buy_lots[index] = document
                return document
        self.buy_lots.append(document)
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(slices)
        return slices

    def replace_open_slices(self, slices):
        slice_ids = {item["lot_slice_id"] for item in slices}
        self.lot_slices = [
            item for item in self.lot_slices if item["lot_slice_id"] not in slice_ids
        ]
        self.lot_slices.extend(slices)
        return slices

    def insert_sell_allocations(self, allocations):
        self.sell_allocations.extend(allocations)
        return allocations

    def list_buy_lots(self, symbol=None):
        if symbol is None:
            return list(self.buy_lots)
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def list_orders(self, symbol=None, states=None, missing_broker_only=False):
        records = list(self.orders)
        if symbol is not None:
            records = [item for item in records if item.get("symbol") == symbol]
        if states is not None:
            allowed = set(states)
            records = [item for item in records if item.get("state") in allowed]
        if missing_broker_only:
            records = [item for item in records if not item.get("broker_order_id")]
        return records

    def list_open_slices(self, symbol=None):
        records = [item for item in self.lot_slices if item["remaining_quantity"] > 0]
        if symbol is None:
            return records
        return [item for item in records if item["symbol"] == symbol]

    def insert_reconciliation_gap(self, document):
        self.reconciliation_gaps.append(dict(document))
        return document

    def list_reconciliation_gaps(self, *, symbol=None, state=None):
        rows = list(self.reconciliation_gaps)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if state is not None:
            rows = [item for item in rows if item.get("state") == state]
        return rows

    def update_reconciliation_gap(self, gap_id, updates):
        for item in self.reconciliation_gaps:
            if item["gap_id"] == gap_id:
                item.update(updates)
                return item
        return None

    def insert_reconciliation_resolution(self, document):
        self.reconciliation_resolutions.append(dict(document))
        return document

    def replace_position_entry(self, document):
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


def test_reconcile_trade_reports_emits_runtime_events(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_safe_resolve_lot_amount",
        lambda _symbol: 3000,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_safe_grid_interval_lookup",
        lambda _symbol, _trade_fact: 1.03,
        raising=False,
    )
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.5,
            "quantity": 200,
            "source": "strategy",
            "internal_order_id": "ord_recon_1",
            "request_id": "req_recon_1",
            "trace_id": "trc_recon_1",
            "intent_id": "int_recon_1",
        }
    )
    tracking_service.mark_order_queued("ord_recon_1")
    tracking_service.ingest_order_report(
        {
            "internal_order_id": "ord_recon_1",
            "state": "SUBMITTING",
            "event_type": "submit_started",
            "broker_order_id": None,
        }
    )
    runtime_logger = FakeRuntimeLogger()
    service = ExternalOrderReconcileService(
        repository=repository,
        tracking_service=tracking_service,
        runtime_logger=runtime_logger,
    )

    service.reconcile_trade_reports(
        [
            {
                "order_id": 90002,
                "traded_id": "T90002",
                "stock_code": "000001.SZ",
                "order_type": 23,
                "traded_volume": 200,
                "traded_price": 10.5,
                "traded_time": 1030,
            }
        ]
    )

    assert [event["node"] for event in runtime_logger.events] == [
        "internal_match",
        "projection_update",
    ]
    assert runtime_logger.events[0]["trace_id"] == "trc_recon_1"
    assert runtime_logger.events[1]["internal_order_id"] == "ord_recon_1"


def test_confirm_expired_candidates_emits_reconciliation_event(monkeypatch):
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_safe_resolve_lot_amount",
        lambda _symbol: 3000,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_safe_grid_interval_lookup",
        lambda _symbol, _trade_fact: 1.03,
        raising=False,
    )
    repository = InMemoryRepository()
    runtime_logger = FakeRuntimeLogger()
    service = ExternalOrderReconcileService(
        repository=repository,
        tracking_service=OrderTrackingService(repository=repository),
        runtime_logger=runtime_logger,
        external_confirm_interval_seconds=15,
        external_confirm_observations=3,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1000,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1030,
    )

    service.confirm_expired_candidates(now=1030)

    assert [event["node"] for event in runtime_logger.events] == [
        "reconciliation",
    ]
    assert runtime_logger.events[0]["symbol"] == "000001"
