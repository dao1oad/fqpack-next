# -*- coding: utf-8 -*-

import sys
import types

import pytest

instrument_general_stub = types.ModuleType("freshquant.instrument.general")
setattr(instrument_general_stub, "query_instrument_info", lambda symbol: None)
sys.modules.setdefault("freshquant.instrument.general", instrument_general_stub)

code_stub = types.ModuleType("freshquant.util.code")


def _normalize_to_base_code(value):
    text = str(value or "").strip()
    return text[-6:] if len(text) >= 6 else text


setattr(code_stub, "normalize_to_base_code", _normalize_to_base_code)
sys.modules.setdefault("freshquant.util.code", code_stub)

from freshquant.order_management.read_service import (
    OrderManagementReadService,
    _parse_filter_datetime,
)


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.order_requests = []
        self.broker_orders = []
        self.order_events = []
        self.execution_fills = []

    def find_broker_order(self, broker_order_key):
        for item in self.broker_orders:
            if item.get("broker_order_key") == broker_order_key:
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
        rows = list(self.broker_orders)
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

    def list_broker_orders(
        self,
        *,
        symbol=None,
        states=None,
        broker_order_keys=None,
    ):
        rows = list(self.broker_orders)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if states is not None:
            allowed_states = {str(item).strip().upper() for item in states}
            rows = [
                item
                for item in rows
                if str(item.get("state") or "").strip().upper() in allowed_states
            ]
        if broker_order_keys is not None:
            allowed_keys = set(broker_order_keys)
            rows = [
                item for item in rows if item.get("broker_order_key") in allowed_keys
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

    def list_execution_fills(self, symbol=None, broker_order_keys=None, execution_fill_ids=None):
        rows = list(self.execution_fills)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if broker_order_keys is not None:
            allowed_order_ids = set(broker_order_keys)
            rows = [
                item
                for item in rows
                if item.get("broker_order_key") in allowed_order_ids
            ]
        if execution_fill_ids is not None:
            allowed_fill_ids = set(execution_fill_ids)
            rows = [
                item
                for item in rows
                if item.get("execution_fill_id") in allowed_fill_ids
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
    repository.broker_orders.extend(
        [
            {
                "broker_order_key": "ord_fill_1",
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
                "requested_quantity": 100,
                "filled_quantity": 100,
                "avg_filled_price": 10.1,
                "fill_count": 1,
                "first_fill_time": 1710311100,
                "last_fill_time": 1710311100,
                "updated_at": "2026-03-13T09:05:00+00:00",
            },
            {
                "broker_order_key": "ord_queue_1",
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
                "requested_quantity": 200,
                "filled_quantity": 0,
                "avg_filled_price": None,
                "fill_count": 0,
                "first_fill_time": None,
                "last_fill_time": None,
                "updated_at": "2026-03-13T10:05:00+00:00",
            },
            {
                "broker_order_key": "ord_cancel_1",
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
                "requested_quantity": 300,
                "filled_quantity": 0,
                "avg_filled_price": None,
                "fill_count": 0,
                "first_fill_time": None,
                "last_fill_time": None,
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
    repository.execution_fills.extend(
        [
            {
                "execution_fill_id": "fill_1",
                "broker_order_key": "ord_fill_1",
                "broker_order_id": "BRK-1",
                "internal_order_id": "ord_fill_1",
                "symbol": "600000",
                "side": "buy",
                "quantity": 100,
                "price": 10.1,
                "trade_time": 1710311100,
                "source": "xt_report",
            },
            {
                "execution_fill_id": "fill_other_1",
                "broker_order_key": "ord_other_1",
                "broker_order_id": "BRK-other-1",
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


def test_parse_filter_datetime_uses_beijing_for_naive_inputs():
    lower_bound = _parse_filter_datetime("2026-03-25", upper_bound=False)
    upper_bound = _parse_filter_datetime("2026-03-25 13:46:10", upper_bound=True)

    assert lower_bound.isoformat() == "2026-03-25T00:00:00+08:00"
    assert upper_bound.isoformat() == "2026-03-25T13:46:10+08:00"


def test_list_orders_includes_instrument_name(monkeypatch):
    repository = _build_repository()
    monkeypatch.setattr(
        "freshquant.order_management.read_service.query_instrument_info",
        lambda symbol: {"name": "浦发银行"} if symbol == "600000" else None,
    )
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(symbol="600000", state="FILLED")

    assert payload["rows"][0]["name"] == "浦发银行"


def test_list_orders_tolerates_instrument_lookup_failures(monkeypatch):
    repository = _build_repository()
    monkeypatch.setattr(
        "freshquant.order_management.read_service.query_instrument_info",
        lambda _symbol: (_ for _ in ()).throw(RuntimeError("instrument lookup failed")),
    )
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(symbol="600000", state="FILLED")

    assert payload["rows"][0]["internal_order_id"] == "ord_fill_1"
    assert payload["rows"][0]["name"] is None


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
    assert detail["broker_order"]["broker_order_key"] == "ord_fill_1"
    assert detail["fills"][0]["execution_fill_id"] == "fill_1"
    assert detail["trades"][0]["execution_fill_id"] == "fill_1"
    assert detail["identifiers"] == {
        "trace_id": "trc_fill_1",
        "intent_id": "int_fill_1",
        "request_id": "req_fill_1",
        "internal_order_id": "ord_fill_1",
        "broker_order_id": "BRK-1",
    }


def test_get_order_detail_uses_broker_order_key_to_load_execution_fills():
    repository = _build_repository()
    repository.broker_orders[0]["broker_order_key"] = "border_fill_1"
    repository.execution_fills[0]["broker_order_key"] = "border_fill_1"
    service = OrderManagementReadService(repository=repository)

    detail = service.get_order_detail("ord_fill_1")

    assert detail["broker_order"]["broker_order_key"] == "border_fill_1"
    assert [item["execution_fill_id"] for item in detail["fills"]] == ["fill_1"]


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
    repository.broker_orders[0]["_id"] = object()
    repository.order_requests[0]["_id"] = object()
    repository.order_events[0]["_id"] = object()
    repository.execution_fills[0]["_id"] = object()
    service = OrderManagementReadService(repository=repository)

    orders_payload = service.list_orders(symbol="600000", state="FILLED")
    detail_payload = service.get_order_detail("ord_fill_1")

    assert "_id" not in orders_payload["rows"][0]
    assert "_id" not in detail_payload["order"]
    assert "_id" not in detail_payload["request"]
    assert "_id" not in detail_payload["events"][0]
    assert "_id" not in detail_payload["fills"][0]
