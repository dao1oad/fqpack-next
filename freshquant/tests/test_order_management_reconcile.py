from freshquant.order_management.reconcile.service import ExternalOrderReconcileService
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
        self.external_candidates = []

    @property
    def external_candidates_collection(self):
        return self.external_candidates

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

    def insert_external_candidate(self, document):
        self.external_candidates.append(document)
        return document

    def list_external_candidates(self, state=None):
        if state is None:
            return list(self.external_candidates)
        return [item for item in self.external_candidates if item["state"] == state]

    def update_external_candidate(self, candidate_id, updates):
        for item in self.external_candidates:
            if item["candidate_id"] == candidate_id:
                item.update(updates)
                return item
        return None


def _build_service():
    repository = InMemoryRepository()
    tracking_service = OrderTrackingService(repository=repository)
    service = ExternalOrderReconcileService(
        repository=repository,
        tracking_service=tracking_service,
        external_confirm_seconds=120,
    )
    return repository, service


def test_detect_external_candidates_from_position_delta():
    repository, service = _build_service()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.0,
            "quantity": 100,
            "source": "strategy",
            "internal_order_id": "ord_existing_1",
        }
    )
    repository.insert_buy_lot(
        {
            "buy_lot_id": "lot_existing_1",
            "origin_trade_fact_id": "trade_existing_1",
            "symbol": "000001",
            "account_id": "acct",
            "buy_price_real": 10.0,
            "original_quantity": 100,
            "remaining_quantity": 100,
            "amount_adjust": 1.0,
            "source": "strategy",
            "status": "open",
            "arrange_mode": "runtime_grid",
        }
    )

    candidates = service.detect_external_candidates(
        positions=[
            {"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.5},
        ],
        detected_at=1_000,
    )

    assert len(candidates) == 1
    assert candidates[0]["side"] == "buy"
    assert candidates[0]["quantity_delta"] == 200
    assert candidates[0]["pending_until"] == 1_120


def test_reconcile_matches_external_trade_report_to_existing_candidate():
    repository, service = _build_service()
    candidate = service.detect_external_candidates(
        positions=[
            {"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5},
        ],
        detected_at=1_000,
    )[0]

    results = service.reconcile_trade_reports(
        [
            {
                "order_id": 90001,
                "traded_id": "T90001",
                "stock_code": "000001.SZ",
                "order_type": 23,
                "traded_volume": 200,
                "traded_price": 10.5,
                "traded_time": 1_030,
            }
        ]
    )

    assert len(results) == 1
    assert (
        repository.external_candidates[0]["candidate_id"] == candidate["candidate_id"]
    )
    assert repository.external_candidates[0]["state"] == "MATCHED"
    assert repository.external_candidates[0]["matched_order_id"]
    assert len(repository.buy_lots) == 1
    assert repository.orders[0]["source_type"] == "external_reported"


def test_reconcile_matches_inflight_internal_order_before_creating_external_order():
    repository, service = _build_service()
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.5,
            "quantity": 200,
            "source": "strategy",
            "internal_order_id": "ord_internal_1",
        }
    )
    tracking_service.mark_order_queued("ord_internal_1")
    tracking_service.ingest_order_report(
        {
            "internal_order_id": "ord_internal_1",
            "state": "SUBMITTING",
            "event_type": "submit_started",
            "broker_order_id": None,
        }
    )

    results = service.reconcile_trade_reports(
        [
            {
                "order_id": 90002,
                "traded_id": "T90002",
                "stock_code": "000001.SZ",
                "order_type": 23,
                "traded_volume": 200,
                "traded_price": 10.5,
                "traded_time": 1_030,
            }
        ]
    )

    assert len(results) == 1
    assert len(repository.orders) == 1
    assert repository.orders[0]["internal_order_id"] == "ord_internal_1"
    assert repository.orders[0]["source_type"] == "strategy"
    assert results[0]["trade_fact"]["internal_order_id"] == "ord_internal_1"
    assert repository.trade_facts[0]["internal_order_id"] == "ord_internal_1"


def test_inferred_pending_auto_confirms_after_120_seconds():
    repository, service = _build_service()
    candidate = service.detect_external_candidates(
        positions=[
            {"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5},
        ],
        detected_at=1_000,
    )[0]

    confirmed = service.confirm_expired_candidates(now=1_121)

    assert len(confirmed) == 1
    assert confirmed[0]["candidate_id"] == candidate["candidate_id"]
    assert repository.external_candidates[0]["state"] == "INFERRED_CONFIRMED"
    assert repository.orders[0]["state"] == "INFERRED_CONFIRMED"
    assert repository.trade_facts[0]["provisional"] is True
    assert len(repository.buy_lots) == 1
