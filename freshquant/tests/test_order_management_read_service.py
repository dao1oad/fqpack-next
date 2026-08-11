# -*- coding: utf-8 -*-

import sys
import types
from datetime import datetime, timezone

import pytest

_original_instrument_general = sys.modules.get("freshquant.instrument.general")
_original_util_code = sys.modules.get("freshquant.util.code")

instrument_general_stub = types.ModuleType("freshquant.instrument.general")
setattr(instrument_general_stub, "query_instrument_info", lambda symbol: None)
sys.modules.setdefault("freshquant.instrument.general", instrument_general_stub)

code_stub = types.ModuleType("freshquant.util.code")


def _normalize_to_base_code(value):
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text[-6:] if len(text) >= 6 else text


setattr(code_stub, "normalize_to_base_code", _normalize_to_base_code)
setattr(
    code_stub,
    "fq_util_code_append_market_code",
    lambda value: str(value or "").strip(),
)
setattr(
    code_stub,
    "fq_util_code_append_market_code_suffix",
    lambda value: str(value or "").strip(),
)
sys.modules.setdefault("freshquant.util.code", code_stub)

try:
    from freshquant.order_management.read_service import (
        OrderManagementReadService,
        _parse_filter_datetime,
    )
finally:
    if _original_instrument_general is None:
        sys.modules.pop("freshquant.instrument.general", None)
    else:
        sys.modules["freshquant.instrument.general"] = _original_instrument_general

    if _original_util_code is None:
        sys.modules.pop("freshquant.util.code", None)
    else:
        sys.modules["freshquant.util.code"] = _original_util_code


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.order_requests = []
        self.broker_orders = []
        self.order_events = []
        self.execution_fills = []
        self.exit_allocations = []

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

    def list_execution_fills(
        self, symbol=None, broker_order_keys=None, execution_fill_ids=None
    ):
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

    def list_exit_allocations_for_request(
        self,
        *,
        request_id=None,
        internal_order_id=None,
    ):
        rows = list(self.exit_allocations)
        if request_id not in {None, ""}:
            rows = [item for item in rows if item.get("request_id") == request_id]
        if internal_order_id not in {None, ""}:
            rows = [
                item
                for item in rows
                if item.get("internal_order_id") == internal_order_id
            ]
        return rows

    def list_exit_allocations_for_requests(
        self,
        request_ids=None,
        internal_order_ids=None,
    ):
        normalized_requests = {
            str(item) for item in list(request_ids or []) if str(item)
        }
        normalized_orders = {
            str(item) for item in list(internal_order_ids or []) if str(item)
        }
        return [
            item
            for item in self.exit_allocations
            if str(item.get("request_id") or "") in normalized_requests
            or str(item.get("internal_order_id") or "") in normalized_orders
        ]


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


def test_list_orders_derives_timestamp_fields_for_broker_only_rebuild_rows():
    repository = InMemoryOrderManagementRepository()
    repository.broker_orders.append(
        {
            "broker_order_key": "403701761",
            "broker_order_id": "403701761",
            "symbol": "600104",
            "side": "sell",
            "state": "FILLED",
            "source_type": "broker_rebuild",
            "first_fill_time": 1775007300,
            "last_fill_time": 1775007366,
            "requested_quantity": 200,
            "filled_quantity": 200,
            "avg_filled_price": 19.88,
        }
    )
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(symbol="600104")
    stats = service.get_stats(symbol="600104")

    expected_updated_at = datetime.fromtimestamp(
        1775007366,
        tz=timezone.utc,
    ).isoformat()
    expected_submitted_at = datetime.fromtimestamp(
        1775007300,
        tz=timezone.utc,
    ).isoformat()

    assert payload["rows"][0]["broker_order_id"] == "403701761"
    assert payload["rows"][0]["updated_at"] == expected_updated_at
    assert payload["rows"][0]["submitted_at"] == expected_submitted_at
    assert stats["latest_updated_at"] == expected_updated_at


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


def _build_ledger_repository():
    repository = InMemoryOrderManagementRepository()
    repository.order_requests.extend(
        [
            {
                "request_id": "req_ledger_base_line",
                "action": "buy",
                "source": "strategy",
                "symbol": "600000",
                "price": 9.5,
                "quantity": 100,
                "scope_type": "takeprofit_batch",
                "ledger_intent": "base",
                "strategy_context": {
                    "guardian_buy_grid": {"path": "base_line", "grid_level": "BUY-2"},
                },
            },
            {
                "request_id": "req_ledger_t_buy",
                "action": "buy",
                "source": "strategy",
                "symbol": "600000",
                "price": 9.6,
                "quantity": 200,
                "scope_type": "signal",
                "ledger_intent": "t",
                "strategy_context": {
                    "guardian_buy_grid": {
                        "path": "holding_add",
                        "grid_level": "BUY-3",
                        "hit_levels": ["BUY-3"],
                    }
                },
            },
            {
                "request_id": "req_ledger_manual",
                "action": "buy",
                "source": "manual_import",
                "symbol": "600000",
                "price": 9.7,
                "quantity": 300,
                "scope_type": "manual",
                "ledger_intent": "base",
            },
            {
                "request_id": "req_ledger_tp_sell",
                "action": "sell",
                "source": "tpsl_takeprofit",
                "symbol": "600000",
                "price": 10.8,
                "quantity": 100,
                "scope_type": "takeprofit_batch",
                "ledger_intent": "base",
                "strategy_context": {
                    "guardian_sell_sources": {
                        "allocation_policy": "takeprofit_ratio_v1",
                        "level": 1,
                    }
                },
            },
            {
                "request_id": "req_ledger_stoploss",
                "action": "sell",
                "source": "tpsl_symbol_stoploss",
                "symbol": "600000",
                "price": 9.0,
                "quantity": 500,
                "scope_type": "symbol_stoploss_batch",
                "ledger_intent": "-",
            },
        ]
    )
    for index, request in enumerate(repository.order_requests):
        repository.broker_orders.append(
            {
                "broker_order_key": f"ord_ledger_{index}",
                "internal_order_id": f"ord_ledger_{index}",
                "request_id": request["request_id"],
                "broker_order_id": f"BRK-ledger-{index}",
                "symbol": request["symbol"],
                "side": request["action"],
                "state": "FILLED",
                "requested_quantity": request["quantity"],
                "created_at": "2026-08-11T09:00:00+00:00",
                "updated_at": "2026-08-11T09:00:00+00:00",
            }
        )
    return repository


def test_list_orders_derives_dual_ledger_for_buy_orders():
    repository = _build_ledger_repository()
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(symbol="600000", state="FILLED")
    by_request = {row["request_id"]: row for row in payload["rows"]}

    # 买入线补仓（ledger_intent=base + path=base_line）→ base
    assert by_request["req_ledger_base_line"]["ledger"] == "base"
    assert by_request["req_ledger_base_line"]["position_type"] == "base"
    # Guardian 做T 买单（ledger_intent=t）→ t
    assert by_request["req_ledger_t_buy"]["ledger"] == "t"
    assert by_request["req_ledger_t_buy"]["position_type"] == "t"
    # 手动加仓/首开（ledger_intent=base）→ base
    assert by_request["req_ledger_manual"]["ledger"] == "base"


def test_list_orders_derives_dual_ledger_for_sell_orders():
    repository = _build_ledger_repository()
    service = OrderManagementReadService(repository=repository)

    payload = service.list_orders(symbol="600000", state="FILLED")
    by_request = {row["request_id"]: row for row in payload["rows"]}

    # TPSL 止盈卖单（ledger_intent=base，即使带 guardian_sell_sources 分配书签）→ base
    assert by_request["req_ledger_tp_sell"]["ledger"] == "base"
    assert by_request["req_ledger_tp_sell"]["position_type"] == "base"
    # 全仓止损（ledger_intent=-）→ -
    assert by_request["req_ledger_stoploss"]["ledger"] == "-"
    assert by_request["req_ledger_stoploss"]["position_type"] == ""


def test_list_orders_derives_dual_ledger_for_guardian_t_sell():
    repository = InMemoryOrderManagementRepository()
    repository.order_requests.append(
        {
            "request_id": "req_ledger_guardian_t_sell",
            "action": "sell",
            "source": "strategy",
            "strategy_name": "Guardian",
            "symbol": "600000",
            "price": 10.9,
            "quantity": 100,
            "ledger_intent": "t",
            "strategy_context": {
                "guardian_sell_sources": {
                    "version": 2,
                    "submit_quantity": 100,
                    "entries": [{"entry_id": "entry_t_1", "quantity": 100}],
                    "slices": [
                        {
                            "entry_id": "entry_t_1",
                            "entry_slice_id": "slice_t_1",
                            "quantity": 100,
                        }
                    ],
                }
            },
        }
    )
    repository.broker_orders.append(
        {
            "broker_order_key": "ord_ledger_guardian_t_sell",
            "internal_order_id": "ord_ledger_guardian_t_sell",
            "request_id": "req_ledger_guardian_t_sell",
            "broker_order_id": "BRK-guardian-t-sell",
            "symbol": "600000",
            "side": "sell",
            "state": "FILLED",
            "requested_quantity": 100,
            "created_at": "2026-08-11T09:00:00+00:00",
            "updated_at": "2026-08-11T09:00:00+00:00",
        }
    )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="600000", state="FILLED")
    by_request = {row["request_id"]: row for row in payload["rows"]}

    # Guardian 做T卖出（ledger_intent=t）→ t
    assert by_request["req_ledger_guardian_t_sell"]["ledger"] == "t"
    assert by_request["req_ledger_guardian_t_sell"]["position_type"] == "t"


def test_list_orders_sell_mixed_from_allocations():
    """#571 C1：分摊卖单（分配跨 base/t）订单级返回 mixed。"""

    repository = InMemoryOrderManagementRepository()
    repository.order_requests.append(
        {
            "request_id": "req_ledger_mixed_sell",
            "action": "sell",
            "source": "strategy",
            "symbol": "600000",
            "price": 10.5,
            "quantity": 200,
            "ledger_intent": "-",
        }
    )
    repository.broker_orders.append(
        {
            "broker_order_key": "ord_ledger_mixed_sell",
            "internal_order_id": "ord_ledger_mixed_sell",
            "request_id": "req_ledger_mixed_sell",
            "broker_order_id": "BRK-mixed-sell",
            "symbol": "600000",
            "side": "sell",
            "state": "FILLED",
            "requested_quantity": 200,
            "created_at": "2026-08-11T09:00:00+00:00",
            "updated_at": "2026-08-11T09:00:00+00:00",
        }
    )
    repository.exit_allocations.extend(
        [
            {
                "allocation_id": "alloc_mixed_base",
                "request_id": "req_ledger_mixed_sell",
                "internal_order_id": "ord_ledger_mixed_sell",
                "position_type": "base",
                "allocated_quantity": 100,
            },
            {
                "allocation_id": "alloc_mixed_t",
                "request_id": "req_ledger_mixed_sell",
                "internal_order_id": "ord_ledger_mixed_sell",
                "position_type": "t",
                "allocated_quantity": 100,
            },
        ]
    )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="600000", state="FILLED")
    row = payload["rows"][0]
    assert row["ledger"] == "mixed"
    assert row["position_type"] == "mixed"

    detail = service.get_order_detail("ord_ledger_mixed_sell")
    assert detail["order"]["ledger"] == "mixed"
    assert len(detail["exit_allocations"]) == 2


def test_list_orders_marks_ledger_intent_missing_without_guessing():
    """#571 C5：读侧不静默推断；缺失 intent 显式标记 ledger_intent_missing。"""

    repository = InMemoryOrderManagementRepository()
    repository.order_requests.append(
        {
            "request_id": "req_ledger_unbackfilled",
            "action": "buy",
            "source": "strategy",
            "symbol": "600000",
            "price": 9.5,
            "quantity": 100,
        }
    )
    repository.broker_orders.append(
        {
            "broker_order_key": "ord_ledger_unbackfilled",
            "internal_order_id": "ord_ledger_unbackfilled",
            "request_id": "req_ledger_unbackfilled",
            "broker_order_id": "BRK-unbackfilled",
            "symbol": "600000",
            "side": "buy",
            "state": "FILLED",
            "requested_quantity": 100,
            "created_at": "2026-08-11T09:00:00+00:00",
            "updated_at": "2026-08-11T09:00:00+00:00",
        }
    )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="600000", state="FILLED")
    row = payload["rows"][0]
    assert row["ledger"] == "-"
    assert row["ledger_intent_missing"] is True


def test_list_orders_broker_only_buy_is_base():
    """#571 A8：broker-only 手动买入显式 base，不依赖请求。"""

    repository = InMemoryOrderManagementRepository()
    repository.broker_orders.append(
        {
            "broker_order_key": "ord_ledger_broker_only",
            "internal_order_id": "ord_ledger_broker_only",
            "request_id": None,
            "source_type": "broker_only",
            "broker_order_id": "BRK-broker-only",
            "symbol": "600000",
            "side": "buy",
            "state": "FILLED",
            "requested_quantity": 300,
            "created_at": "2026-08-11T09:00:00+00:00",
            "updated_at": "2026-08-11T09:00:00+00:00",
        }
    )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="600000", state="FILLED")
    row = payload["rows"][0]
    assert row["ledger"] == "base"


def test_list_orders_broker_only_sell_ledger_from_internal_order_allocations():
    """#571 目标形态：broker-only 卖单（无 request、10 fills 全 base）→
    列表 ledger=base（allocations 按 internal_order_id 批量关联）。"""

    repository = InMemoryOrderManagementRepository()
    repository.broker_orders.append(
        {
            "broker_order_key": "k_broker_sell_1",
            "internal_order_id": "ord_broker_b859cfc3ee14f188fa92a0aa",
            "request_id": None,
            "source_type": "broker_only",
            "broker_order_id": "B-broker-sell-1",
            "symbol": "002262",
            "side": "sell",
            "state": "FILLED",
            "requested_quantity": 9000,
            "filled_quantity": 9000,
            "created_at": "2026-08-11T13:11:57+08:00",
            "updated_at": "2026-08-11T13:12:12+08:00",
        }
    )
    for index in range(10):
        repository.exit_allocations.append(
            {
                "allocation_id": f"alloc_broker_sell_{index}",
                "exit_trade_fact_id": f"fact_broker_sell_{index}",
                "internal_order_id": "ord_broker_b859cfc3ee14f188fa92a0aa",
                "request_id": None,
                "position_type": "base",
                "allocated_quantity": 900,
            }
        )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="002262")
    row = payload["rows"][0]
    assert row["ledger"] == "base"
    assert row["position_type"] == "base"

    detail = service.get_order_detail("ord_broker_b859cfc3ee14f188fa92a0aa")
    assert detail["order"]["ledger"] == "base"
    assert len(detail["exit_allocations"]) == 10


def test_list_orders_broker_only_sell_mixed_from_internal_order_allocations():
    """#571：broker-only 分摊卖单（分配跨 base/t）按 internal_order_id
    批量关联 → 订单级 mixed。"""

    repository = InMemoryOrderManagementRepository()
    repository.broker_orders.append(
        {
            "broker_order_key": "k_broker_sell_mixed",
            "internal_order_id": "ord_broker_mixed_sell_1",
            "request_id": None,
            "source_type": "broker_only",
            "broker_order_id": "B-broker-mixed-1",
            "symbol": "002262",
            "side": "sell",
            "state": "FILLED",
            "requested_quantity": 200,
            "filled_quantity": 200,
            "created_at": "2026-08-11T13:11:57+08:00",
            "updated_at": "2026-08-11T13:12:12+08:00",
        }
    )
    repository.exit_allocations.extend(
        [
            {
                "allocation_id": "alloc_mixed_b",
                "internal_order_id": "ord_broker_mixed_sell_1",
                "request_id": None,
                "position_type": "base",
                "allocated_quantity": 100,
            },
            {
                "allocation_id": "alloc_mixed_t",
                "internal_order_id": "ord_broker_mixed_sell_1",
                "request_id": None,
                "position_type": "t",
                "allocated_quantity": 100,
            },
        ]
    )
    service = OrderManagementReadService(repository=repository)
    payload = service.list_orders(symbol="002262")
    row = payload["rows"][0]
    assert row["ledger"] == "mixed"
