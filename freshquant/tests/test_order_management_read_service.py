# -*- coding: utf-8 -*-

import pytest
from bson import ObjectId

from freshquant.order_management.read_service import OrderManagementReadService


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.order_requests = []
        self.orders = []
        self.order_events = []
        self.trade_facts = []

    def find_order(self, internal_order_id):
        for item in self.orders:
            if item.get("internal_order_id") == internal_order_id:
                return item
        return None

    def find_order_request(self, request_id):
        for item in self.order_requests:
            if item.get("request_id") == request_id:
                return item
        return None

    def list_order_requests(
        self,
        *,
        symbol=None,
        scope_type=None,
        scope_ref_id=None,
        scope_ref_ids=None,
        request_ids=None,
    ):
        rows = list(self.order_requests)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if scope_type is not None:
            rows = [item for item in rows if item.get("scope_type") == scope_type]
        if scope_ref_id is not None:
            rows = [item for item in rows if item.get("scope_ref_id") == scope_ref_id]
        if scope_ref_ids is not None:
            allowed_scope_ids = set(scope_ref_ids)
            rows = [
                item for item in rows if item.get("scope_ref_id") in allowed_scope_ids
            ]
        if request_ids is not None:
            allowed_request_ids = set(request_ids)
            rows = [
                item for item in rows if item.get("request_id") in allowed_request_ids
            ]
        return rows

    def list_orders(
        self,
        symbol=None,
        states=None,
        missing_broker_only=False,
        request_ids=None,
        internal_order_ids=None,
    ):
        rows = list(self.orders)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if states is not None:
            allowed_states = {str(item).strip().upper() for item in states}
            rows = [
                item
                for item in rows
                if str(item.get("state") or "").strip().upper() in allowed_states
            ]
        if missing_broker_only:
            rows = [item for item in rows if item.get("broker_order_id") in (None, "")]
        if request_ids is not None:
            allowed_request_ids = set(request_ids)
            rows = [
                item for item in rows if item.get("request_id") in allowed_request_ids
            ]
        if internal_order_ids is not None:
            allowed_order_ids = set(internal_order_ids)
            rows = [
                item
                for item in rows
                if item.get("internal_order_id") in allowed_order_ids
            ]
        return rows

    def list_order_events(self, *, internal_order_ids=None):
        rows = list(self.order_events)
        if internal_order_ids is not None:
            allowed_order_ids = set(internal_order_ids)
            rows = [
                item
                for item in rows
                if item.get("internal_order_id") in allowed_order_ids
            ]
        return rows

    def list_trade_facts(self, symbol=None, internal_order_ids=None):
        rows = list(self.trade_facts)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if internal_order_ids is not None:
            allowed_order_ids = set(internal_order_ids)
            rows = [
                item
                for item in rows
                if item.get("internal_order_id") in allowed_order_ids
            ]
        return rows


def _build_repository():
    repository = InMemoryOrderManagementRepository()
    repository.order_requests.extend(
        [
            {
                "request_id": "req_fill_1",
                "action": "buy",
                "source": "strategy",
                "trace_id": "trc_fill_1",
                "intent_id": "int_fill_1",
                "account_type": "STOCK",
                "symbol": "600000",
                "price": 10.1,
                "quantity": 100,
                "strategy_name": "Guardian",
                "remark": "buy-on-signal",
                "scope_type": "signal",
                "scope_ref_id": "sig_1",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T09:00:00+00:00",
            },
            {
                "request_id": "req_queue_1",
                "action": "sell",
                "source": "web",
                "trace_id": "trc_queue_1",
                "intent_id": "int_queue_1",
                "account_type": "CREDIT",
                "symbol": "600000",
                "price": 10.8,
                "quantity": 200,
                "strategy_name": "ManualDesk",
                "remark": "manual-takeprofit",
                "scope_type": "manual",
                "scope_ref_id": "manual_1",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T10:00:00+00:00",
            },
            {
                "request_id": "req_cancel_1",
                "action": "sell",
                "source": "api",
                "trace_id": "trc_cancel_1",
                "intent_id": "int_cancel_1",
                "account_type": "STOCK",
                "symbol": "000001",
                "price": 12.2,
                "quantity": 300,
                "strategy_name": "DeskApi",
                "remark": "manual-cancel",
                "scope_type": "manual",
                "scope_ref_id": "manual_2",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T11:00:00+00:00",
            },
        ]
    )
    repository.orders.extend(
        [
            {
                "internal_order_id": "ord_fill_1",
                "request_id": "req_fill_1",
                "broker_order_id": "BRK-1",
                "account_type": "STOCK",
                "trace_id": "trc_fill_1",
                "intent_id": "int_fill_1",
                "symbol": "600000",
                "side": "buy",
                "state": "FILLED",
                "source_type": "strategy",
                "submitted_at": "2026-03-13T09:01:00+00:00",
                "filled_quantity": 100,
                "avg_filled_price": 10.1,
                "updated_at": "2026-03-13T09:05:00+00:00",
            },
            {
                "internal_order_id": "ord_queue_1",
                "request_id": "req_queue_1",
                "broker_order_id": "",
                "account_type": "CREDIT",
                "trace_id": "trc_queue_1",
                "intent_id": "int_queue_1",
                "symbol": "600000",
                "side": "sell",
                "state": "QUEUED",
                "source_type": "web",
                "submitted_at": None,
                "filled_quantity": 0,
                "avg_filled_price": None,
                "updated_at": "2026-03-13T10:05:00+00:00",
            },
            {
                "internal_order_id": "ord_cancel_1",
                "request_id": "req_cancel_1",
                "broker_order_id": "BRK-3",
                "account_type": "STOCK",
                "trace_id": "trc_cancel_1",
                "intent_id": "int_cancel_1",
                "symbol": "000001",
                "side": "sell",
                "state": "CANCELLED",
                "source_type": "api",
                "submitted_at": "2026-03-13T11:01:00+00:00",
                "filled_quantity": 0,
                "avg_filled_price": None,
                "updated_at": "2026-03-13T11:06:00+00:00",
            },
        ]
    )
    repository.order_events.extend(
        [
            {
                "event_id": "evt_fill_1",
                "request_id": "req_fill_1",
                "internal_order_id": "ord_fill_1",
                "event_type": "accepted",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T09:00:00+00:00",
            },
            {
                "event_id": "evt_fill_2",
                "request_id": "req_fill_1",
                "internal_order_id": "ord_fill_1",
                "event_type": "trade_reported",
                "state": "FILLED",
                "created_at": "2026-03-13T09:05:00+00:00",
            },
            {
                "event_id": "evt_queue_1",
                "request_id": "req_queue_1",
                "internal_order_id": "ord_queue_1",
                "event_type": "queued",
                "state": "QUEUED",
                "created_at": "2026-03-13T10:05:00+00:00",
            },
        ]
    )
    repository.trade_facts.extend(
        [
            {
                "trade_fact_id": "trade_fill_1",
                "internal_order_id": "ord_fill_1",
                "symbol": "600000",
                "side": "buy",
                "quantity": 100,
                "price": 10.1,
                "trade_time": 1710311100,
                "source": "xt_report",
            },
            {
                "trade_fact_id": "trade_other_1",
                "internal_order_id": "ord_other_1",
                "symbol": "300001",
                "side": "buy",
                "quantity": 100,
                "price": 9.9,
                "trade_time": 1710311000,
                "source": "xt_report",
            },
        ]
    )
    return repository


def test_list_orders_filters_and_paginates_order_rows():
    repository = _build_repository()
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(
        symbol="600000",
        strategy_name="Guardian",
        state="FILLED",
        time_field="updated_at",
        date_from="2026-03-13T09:00:00+00:00",
        date_to="2026-03-13T09:10:00+00:00",
        page=1,
        size=10,
    )

    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["size"] == 10
    assert payload["rows"][0]["internal_order_id"] == "ord_fill_1"
    assert payload["rows"][0]["strategy_name"] == "Guardian"
    assert payload["rows"][0]["source"] == "strategy"
    assert payload["rows"][0]["created_at"] == "2026-03-13T09:00:00+00:00"
    assert payload["rows"][0]["trace_id"] == "trc_fill_1"


def test_get_order_detail_assembles_request_events_and_trades():
    repository = _build_repository()
    service = OrderManagementReadService(repository=repository)

    detail = service.get_order_detail("ord_fill_1")

    assert detail["order"]["internal_order_id"] == "ord_fill_1"
    assert detail["request"]["request_id"] == "req_fill_1"
    assert detail["request"]["scope_ref_id"] == "sig_1"
    assert [item["event_type"] for item in detail["events"]] == [
        "accepted",
        "trade_reported",
    ]
    assert detail["trades"][0]["trade_fact_id"] == "trade_fill_1"
    assert detail["identifiers"] == {
        "trace_id": "trc_fill_1",
        "intent_id": "int_fill_1",
        "request_id": "req_fill_1",
        "internal_order_id": "ord_fill_1",
        "broker_order_id": "BRK-1",
    }


def test_get_stats_aggregates_side_state_and_missing_broker_counts():
    repository = _build_repository()
    service = OrderManagementReadService(repository=repository)

    stats = service.get_stats(symbol="600000")

    assert stats["total"] == 2
    assert stats["side_distribution"] == {"buy": 1, "sell": 1}
    assert stats["state_distribution"] == {"FILLED": 1, "QUEUED": 1}
    assert stats["missing_broker_order_count"] == 1
    assert stats["latest_updated_at"] == "2026-03-13T10:05:00+00:00"
    assert stats["filled_count"] == 1
    assert stats["partial_filled_count"] == 0
    assert stats["canceled_count"] == 0
    assert stats["failed_count"] == 0


def test_list_orders_rejects_unknown_time_field():
    repository = _build_repository()
    service = OrderManagementReadService(repository=repository)

    with pytest.raises(ValueError, match="invalid time_field"):
        service.list_orders(time_field="trade_time")


def test_read_service_removes_mongo_ids_from_list_and_detail_payloads():
    repository = _build_repository()
    repository.orders[0]["_id"] = ObjectId()
    repository.order_requests[0]["_id"] = ObjectId()
    repository.order_events[0]["_id"] = ObjectId()
    repository.trade_facts[0]["_id"] = ObjectId()
    service = OrderManagementReadService(repository=repository)

    orders_payload = service.list_orders(symbol="600000", state="FILLED")
    detail_payload = service.get_order_detail("ord_fill_1")

    assert "_id" not in orders_payload["rows"][0]
    assert "_id" not in detail_payload["order"]
    assert "_id" not in detail_payload["request"]
    assert "_id" not in detail_payload["events"][0]
    assert "_id" not in detail_payload["trades"][0]
