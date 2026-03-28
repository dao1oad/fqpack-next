import pytest

import freshquant.order_management.ingest.xt_reports as xt_reports_module
import freshquant.order_management.reconcile.service as reconcile_service_module
from freshquant.order_management.guardian.arranger import (
    arrange_buy_lot,
    build_buy_lot_from_trade_fact,
)
from freshquant.order_management.reconcile.service import ExternalOrderReconcileService
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
        self.reconciliation_gaps = []
        self.reconciliation_resolutions = []
        self.position_entries = []
        self.entry_slices = []
        self.exit_allocations = []

    def insert_order_request(self, document):
        self.order_requests.append(dict(document))
        return document

    def find_order_request(self, request_id):
        for request in self.order_requests:
            if request["request_id"] == request_id:
                return request
        return None

    def insert_order(self, document):
        self.orders.append(dict(document))
        return document

    def insert_order_event(self, document):
        self.order_events.append(dict(document))
        return document

    def upsert_broker_order(self, document, unique_keys):
        for existing in self.broker_orders:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                existing.update(document)
                return existing, False
        saved = dict(document)
        self.broker_orders.append(saved)
        return saved, True

    def upsert_trade_fact(self, document, unique_keys):
        for existing in self.trade_facts:
            if all(existing.get(key) == document.get(key) for key in unique_keys):
                return existing, False
        saved = dict(document)
        self.trade_facts.append(saved)
        return saved, True

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

    def find_broker_order(self, broker_order_key):
        for order in self.broker_orders:
            if order["broker_order_key"] == broker_order_key:
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
        self.buy_lots.append(dict(document))
        return document

    def replace_buy_lot(self, document):
        for index, buy_lot in enumerate(self.buy_lots):
            if buy_lot["buy_lot_id"] == document["buy_lot_id"]:
                self.buy_lots[index] = dict(document)
                return document
        self.buy_lots.append(dict(document))
        return document

    def replace_lot_slices_for_lot(self, buy_lot_id, slices):
        self.lot_slices = [
            item for item in self.lot_slices if item["buy_lot_id"] != buy_lot_id
        ]
        self.lot_slices.extend(dict(item) for item in slices)
        return slices

    def replace_open_slices(self, slices):
        slice_ids = {item["lot_slice_id"] for item in slices}
        self.lot_slices = [
            item for item in self.lot_slices if item["lot_slice_id"] not in slice_ids
        ]
        self.lot_slices.extend(dict(item) for item in slices)
        return slices

    def insert_sell_allocations(self, allocations):
        self.sell_allocations.extend(dict(item) for item in allocations)
        return allocations

    def list_buy_lots(self, symbol=None):
        if symbol is None:
            return list(self.buy_lots)
        return [item for item in self.buy_lots if item["symbol"] == symbol]

    def list_orders(
        self,
        symbol=None,
        states=None,
        missing_broker_only=False,
        request_ids=None,
        internal_order_ids=None,
    ):
        records = list(self.orders)
        if symbol is not None:
            records = [item for item in records if item.get("symbol") == symbol]
        if states is not None:
            allowed = set(states)
            records = [item for item in records if item.get("state") in allowed]
        if missing_broker_only:
            records = [item for item in records if not item.get("broker_order_id")]
        if request_ids is not None:
            allowed = set(request_ids)
            records = [item for item in records if item.get("request_id") in allowed]
        if internal_order_ids is not None:
            allowed = set(internal_order_ids)
            records = [
                item for item in records if item.get("internal_order_id") in allowed
            ]
        return records

    def list_open_slices(self, symbol=None):
        records = [item for item in self.lot_slices if item["remaining_quantity"] > 0]
        if symbol is None:
            return [dict(item) for item in records]
        return [dict(item) for item in records if item["symbol"] == symbol]

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
                item.update(dict(updates))
                return item
        return None

    def insert_reconciliation_resolution(self, document):
        self.reconciliation_resolutions.append(dict(document))
        return document

    def replace_position_entry(self, document):
        for index, entry in enumerate(self.position_entries):
            if entry["entry_id"] == document["entry_id"]:
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


def _stub_ingest_side_effects(monkeypatch, *, marks=None, mark_label="updated"):
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
            {"reset_after_sell_trade": lambda self, _symbol: None},
        )(),
        raising=False,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "mark_stock_holdings_projection_updated",
        (lambda: None) if marks is None else (lambda: marks.append(mark_label)),
        raising=False,
    )
    monkeypatch.setattr(
        xt_reports_module,
        "_sync_stock_fills_compat",
        lambda _symbol, repository=None: None,
        raising=False,
    )


def _build_service(monkeypatch=None, *, marks=None, mark_label="updated"):
    if monkeypatch is not None:
        _stub_ingest_side_effects(
            monkeypatch,
            marks=marks,
            mark_label=mark_label,
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
    service = ExternalOrderReconcileService(
        repository=repository,
        tracking_service=tracking_service,
        external_confirm_interval_seconds=15,
        external_confirm_observations=3,
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
            "buy_price_real": 10.0,
            "original_quantity": 100,
            "remaining_quantity": 100,
            "amount_adjust": 1.0,
            "source": "strategy",
            "status": "open",
            "arrange_mode": "runtime_grid",
            "sell_history": [],
        }
    )

    gaps = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 300, "avg_price": 10.5}],
        detected_at=1_000,
    )

    assert len(gaps) == 1
    assert gaps[0]["side"] == "buy"
    assert gaps[0]["quantity_delta"] == 200
    assert gaps[0]["observed_count"] == 1
    assert gaps[0]["state"] == "OPEN"
    assert repository.reconciliation_gaps[0]["pending_until"] == 1_030


def test_detect_external_candidates_prefers_snapshot_last_price_over_avg_price():
    repository, service = _build_service()

    candidates = service.detect_external_candidates(
        positions=[
            {
                "stock_code": "000001.SZ",
                "volume": 200,
                "avg_price": 10.5,
                "last_price": 10.82,
            },
        ],
        detected_at=1_000,
    )

    assert len(candidates) == 1
    assert candidates[0]["price_estimate"] == pytest.approx(10.82)
    assert candidates[0]["price_source"] == "position_last_price"
    assert candidates[0]["price_asof"] == 1_000


def test_candidate_observation_keeps_higher_quality_price_source():
    updates = reconcile_service_module._build_gap_observation_updates(
        {
            "candidate_id": "cand-1",
            "symbol": "000001",
            "side": "buy",
            "quantity_delta": 200,
            "price_estimate": 10.82,
            "price_source": "position_last_price",
            "price_asof": 1_000,
            "detected_at": 1_000,
            "first_detected_at": 1_000,
            "last_detected_at": 1_000,
            "observed_count": 1,
        },
        observed={
            "symbol": "000001",
            "side": "buy",
            "quantity_delta": 200,
            "price_estimate": 10.11,
            "price_source": "previous_close",
            "price_asof": 900,
        },
        detected_at=1_015,
        confirm_interval_seconds=15,
        confirm_observations=3,
    )

    assert updates["price_estimate"] == pytest.approx(10.82)
    assert updates["price_source"] == "position_last_price"
    assert updates["price_asof"] == 1_000


def test_resolve_inferred_price_falls_back_to_previous_close(monkeypatch):
    monkeypatch.setattr(
        reconcile_service_module,
        "_load_latest_realtime_price_snapshot",
        lambda _symbol, _position: None,
        raising=False,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_load_previous_close_price_snapshot",
        lambda _symbol, detected_at: {
            "price_estimate": 9.76,
            "price_source": "previous_close",
            "price_asof": int(detected_at) - 1,
        },
        raising=False,
    )

    resolved = reconcile_service_module._resolve_inferred_price_snapshot(
        "000001",
        {
            "stock_code": "000001.SZ",
            "volume": 200,
            "avg_price": None,
            "last_price": None,
            "open_price": None,
        },
        detected_at=1_000,
    )

    assert resolved["price_estimate"] == pytest.approx(9.76)
    assert resolved["price_source"] == "previous_close"
    assert resolved["price_asof"] == 999


def test_reconcile_matches_external_trade_report_to_existing_candidate(monkeypatch):
    marks = []
    repository, service = _build_service(monkeypatch, marks=marks, mark_label="matched")
    gap = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
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
    assert repository.reconciliation_gaps[0]["gap_id"] == gap["gap_id"]
    assert repository.reconciliation_gaps[0]["state"] == "MATCHED"
    assert len(repository.reconciliation_resolutions) == 1
    assert (
        repository.reconciliation_resolutions[0]["resolution_type"]
        == "matched_execution_fill"
    )
    assert len(repository.buy_lots) == 1
    assert repository.orders[0]["source_type"] == "external_reported"
    assert marks == ["matched"]


def test_reconcile_matches_inflight_internal_order_before_creating_external_order(
    monkeypatch,
):
    repository, service = _build_service(monkeypatch)
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


def test_reconcile_trade_report_marks_existing_internal_order_as_handled(monkeypatch):
    repository, service = _build_service(monkeypatch)
    tracking_service = OrderTrackingService(repository=repository)
    tracking_service.submit_order(
        {
            "action": "buy",
            "symbol": "000001",
            "price": 10.5,
            "quantity": 200,
            "source": "strategy",
            "internal_order_id": "ord_internal_known_1",
        }
    )
    repository.update_order(
        "ord_internal_known_1",
        {"broker_order_id": "90011", "state": "SUBMITTED"},
    )

    outcome = service.reconcile_trade_report(
        {
            "order_id": 90011,
            "traded_id": "T90011",
            "stock_code": "000001.SZ",
            "order_type": 23,
            "traded_volume": 200,
            "traded_price": 10.5,
            "traded_time": 1_030,
        }
    )

    assert outcome.handled is True
    assert outcome.action == "already_known_internal_order"
    assert outcome.result is None
    assert repository.trade_facts == []


def test_inferred_pending_auto_confirms_into_entry_without_fake_trade(monkeypatch):
    repository, service = _build_service(monkeypatch)
    gap = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_000,
    )[0]
    assert service.confirm_expired_candidates(now=1_015) == []
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_030,
    )

    confirmed = service.confirm_expired_candidates(now=1_030)

    assert len(confirmed) == 1
    assert confirmed[0]["gap_id"] == gap["gap_id"]
    assert repository.reconciliation_gaps[0]["state"] == "AUTO_OPENED"
    assert len(repository.reconciliation_resolutions) == 1
    assert (
        repository.reconciliation_resolutions[0]["resolution_type"] == "auto_open_entry"
    )
    assert len(repository.position_entries) == 1
    assert repository.position_entries[0]["entry_type"] == "auto_reconciled_open"
    assert repository.position_entries[0]["remaining_quantity"] == 200
    assert len(repository.entry_slices) > 0
    assert repository.orders == []
    assert repository.trade_facts == []
    assert repository.buy_lots == []


def test_confirmed_gap_is_not_recreated_for_same_position_delta(monkeypatch):
    repository, service = _build_service(monkeypatch)
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_000,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_030,
    )
    service.confirm_expired_candidates(now=1_030)

    recreated = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_045,
    )

    assert recreated == []
    assert len(repository.reconciliation_gaps) == 1
    assert len(repository.position_entries) == 1


def test_non_board_lot_gap_is_rejected_without_creating_entry(monkeypatch):
    repository, service = _build_service(monkeypatch)
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 150, "avg_price": 10.5}],
        detected_at=1_000,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 150, "avg_price": 10.5}],
        detected_at=1_015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 150, "avg_price": 10.5}],
        detected_at=1_030,
    )

    confirmed = service.confirm_expired_candidates(now=1_030)

    assert len(confirmed) == 1
    assert confirmed[0]["state"] == "REJECTED"
    assert repository.position_entries == []
    assert repository.entry_slices == []
    assert (
        repository.reconciliation_resolutions[0]["resolution_type"]
        == "board_lot_rejected"
    )
    recreated = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 150, "avg_price": 10.5}],
        detected_at=1_045,
    )
    assert recreated == []
    assert len(repository.reconciliation_gaps) == 1


def test_sell_side_non_board_lot_gap_is_rejected_without_reducing_holdings(monkeypatch):
    repository, service = _build_service(monkeypatch)
    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_seed_buy_sell_odd",
            "symbol": "000001",
            "side": "buy",
            "quantity": 200,
            "price": 10.0,
            "trade_time": 1_000,
            "date": 20240102,
            "time": "09:31:00",
        }
    )
    repository.insert_buy_lot(buy_lot)
    repository.replace_lot_slices_for_lot(
        buy_lot["buy_lot_id"],
        arrange_buy_lot(buy_lot, lot_amount=3000, grid_interval=1.03),
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 50, "avg_price": 10.5}],
        detected_at=1_000,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 50, "avg_price": 10.5}],
        detected_at=1_015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 50, "avg_price": 10.5}],
        detected_at=1_030,
    )

    confirmed = service.confirm_expired_candidates(now=1_030)

    assert len(confirmed) == 1
    assert confirmed[0]["state"] == "REJECTED"
    assert repository.buy_lots[0]["remaining_quantity"] == 200
    assert repository.sell_allocations == []
    assert repository.exit_allocations == []
    assert (
        repository.reconciliation_resolutions[0]["resolution_type"]
        == "board_lot_rejected"
    )


def test_partial_trade_shrinks_pending_gap_before_auto_close(monkeypatch):
    repository, service = _build_service(monkeypatch)
    buy_lot = build_buy_lot_from_trade_fact(
        {
            "trade_fact_id": "trade_seed_buy_1",
            "symbol": "000001",
            "side": "buy",
            "quantity": 900,
            "price": 10.0,
            "trade_time": 1_000,
            "date": 20240102,
            "time": "09:31:00",
        }
    )
    repository.insert_buy_lot(buy_lot)
    repository.replace_lot_slices_for_lot(
        buy_lot["buy_lot_id"],
        arrange_buy_lot(buy_lot, lot_amount=3000, grid_interval=1.03),
    )
    gap = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 400, "avg_price": 10.5}],
        detected_at=1_000,
    )[0]
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 400, "avg_price": 10.5}],
        detected_at=1_015,
    )

    results = service.reconcile_trade_reports(
        [
            {
                "order_id": 90003,
                "traded_id": "T90003",
                "stock_code": "000001.SZ",
                "order_type": 24,
                "traded_volume": 200,
                "traded_price": 10.5,
                "traded_time": 1_030,
            }
        ]
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 400, "avg_price": 10.5}],
        detected_at=1_030,
    )
    confirmed = service.confirm_expired_candidates(now=1_030)

    assert len(results) == 1
    assert repository.reconciliation_gaps[0]["gap_id"] == gap["gap_id"]
    assert repository.reconciliation_gaps[0]["state"] == "AUTO_CLOSED"
    assert repository.reconciliation_gaps[0]["quantity_delta"] == 300
    assert len(confirmed) == 1
    assert confirmed[0]["resolution_type"] == "auto_close_allocation"
    sell_trade_facts = [
        item for item in repository.trade_facts if item["side"] == "sell"
    ]
    assert [item["quantity"] for item in sell_trade_facts] == [200]
    assert len(repository.sell_allocations) > 0
    assert len(repository.reconciliation_resolutions) == 2


def test_pending_gap_is_dismissed_when_position_delta_resolves(monkeypatch):
    repository, service = _build_service(monkeypatch)
    gap = service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_000,
    )[0]

    redetected = service.detect_external_candidates(positions=[], detected_at=1_015)
    confirmed = service.confirm_expired_candidates(now=1_030)

    assert redetected == []
    assert confirmed == []
    assert repository.reconciliation_gaps[0]["gap_id"] == gap["gap_id"]
    assert repository.reconciliation_gaps[0]["state"] == "DISMISSED"


def test_confirm_expired_candidates_raises_when_grid_interval_resolution_fails(
    monkeypatch,
):
    repository, service = _build_service(monkeypatch)
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_000,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_015,
    )
    service.detect_external_candidates(
        positions=[{"stock_code": "000001.SZ", "volume": 200, "avg_price": 10.5}],
        detected_at=1_030,
    )
    monkeypatch.setattr(
        reconcile_service_module,
        "_safe_grid_interval_lookup",
        lambda _symbol, _trade_fact: (_ for _ in ()).throw(
            RuntimeError("grid interval unavailable")
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="grid interval unavailable"):
        service.confirm_expired_candidates(now=1_030)
