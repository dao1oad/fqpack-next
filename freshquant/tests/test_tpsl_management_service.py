import json

from bson import ObjectId

from freshquant.tpsl.management_service import TpslManagementService


class InMemoryTpslRepository:
    def __init__(self):
        self.profiles = {}
        self.states = {}
        self.events = []

    def find_takeprofit_profile(self, symbol):
        return self.profiles.get(symbol)

    def upsert_takeprofit_profile(self, document):
        self.profiles[document["symbol"]] = document
        return document

    def find_takeprofit_state(self, symbol):
        return self.states.get(symbol)

    def upsert_takeprofit_state(self, document):
        self.states[document["symbol"]] = document
        return document

    def list_takeprofit_profiles(self):
        return list(self.profiles.values())

    def list_exit_trigger_events(
        self,
        *,
        symbol=None,
        batch_id=None,
        kind=None,
        limit=50,
    ):
        rows = list(self.events)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if batch_id is not None:
            rows = [item for item in rows if item.get("batch_id") == batch_id]
        if kind is not None:
            rows = [item for item in rows if item.get("kind") == kind]
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        if limit is None:
            return rows
        return rows[: int(limit)]

    def list_latest_exit_trigger_events_by_symbol(self, *, symbols=None):
        allowed = None if symbols is None else set(symbols)
        latest = {}
        rows = list(self.events)
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        for item in rows:
            symbol = item.get("symbol")
            if not symbol:
                continue
            if allowed is not None and symbol not in allowed:
                continue
            if symbol in latest:
                continue
            latest[symbol] = item
        return list(latest.values())


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.position_entries = []
        self.entry_stoploss_bindings = []
        self.entry_slices = []
        self.reconciliation_gaps = []
        self.reconciliation_resolutions = []
        self.buy_lots = []
        self.stoploss_bindings = []
        self.order_requests = []
        self.orders = []
        self.order_events = []
        self.trade_facts = []

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

    def list_buy_lots(self, symbol=None, buy_lot_ids=None):
        rows = list(self.buy_lots)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item.get("buy_lot_id") in allowed]
        return rows

    def list_entry_stoploss_bindings(self, symbol=None, enabled=None):
        rows = list(self.entry_stoploss_bindings)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if enabled is not None:
            rows = [item for item in rows if bool(item.get("enabled")) == bool(enabled)]
        return rows

    def list_stoploss_bindings(self, symbol=None, enabled=None):
        rows = list(self.stoploss_bindings)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if enabled is not None:
            rows = [item for item in rows if bool(item.get("enabled")) == bool(enabled)]
        return rows

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
        return rows

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
            allowed_states = set(states)
            rows = [item for item in rows if item.get("state") in allowed_states]
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
            allowed = set(internal_order_ids)
            rows = [item for item in rows if item.get("internal_order_id") in allowed]
        return rows

    def list_trade_facts(self, symbol=None, internal_order_ids=None):
        rows = list(self.trade_facts)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if internal_order_ids is not None:
            allowed = set(internal_order_ids)
            rows = [item for item in rows if item.get("internal_order_id") in allowed]
        return rows

    def list_reconciliation_gaps(self, *, symbol=None, state=None):
        rows = list(self.reconciliation_gaps)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if state is not None:
            rows = [item for item in rows if item.get("state") == state]
        return rows

    def list_reconciliation_resolutions(self, *, gap_ids=None):
        rows = list(self.reconciliation_resolutions)
        if gap_ids is not None:
            allowed = set(gap_ids)
            rows = [item for item in rows if item.get("gap_id") in allowed]
        return rows


def test_management_overview_unions_holdings_and_configured_symbols():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.2, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
            {"level": 3, "price": 11.5, "manual_enabled": False},
        ],
    }
    tpsl_repository.profiles["000001"] = {
        "symbol": "000001",
        "tiers": [{"level": 1, "price": 11.2, "manual_enabled": True}],
    }
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_stop_1",
                "event_type": "stoploss_hit",
                "kind": "stoploss",
                "symbol": "600000",
                "batch_id": "sl_batch_1",
                "created_at": "2026-03-13T09:00:00+00:00",
            },
            {
                "event_id": "evt_tp_1",
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "000001",
                "batch_id": "tp_batch_1",
                "created_at": "2026-03-13T08:00:00+00:00",
            },
        ]
    )

    order_repository = InMemoryOrderManagementRepository()
    order_repository.entry_stoploss_bindings.extend(
        [
            {
                "entry_id": "lot_1",
                "symbol": "600000",
                "stop_price": 9.2,
                "enabled": True,
            },
            {
                "entry_id": "lot_2",
                "symbol": "000001",
                "stop_price": 8.8,
                "enabled": False,
            },
        ]
    )
    order_repository.stoploss_bindings.extend(
        [
            {
                "buy_lot_id": "lot_1",
                "symbol": "600000",
                "stop_price": 9.2,
                "enabled": True,
            },
            {
                "buy_lot_id": "lot_2",
                "symbol": "000001",
                "stop_price": 8.8,
                "enabled": False,
            },
        ]
    )

    service = TpslManagementService(
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount_adjusted": -5300.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        stock_fills_loader=lambda symbol: [],
    )

    rows = service.get_overview()
    rows_by_symbol = {item["symbol"]: item for item in rows}

    assert set(rows_by_symbol) == {"600000", "000001"}
    assert rows_by_symbol["600000"]["name"] == "浦发银行"
    assert rows_by_symbol["600000"]["position_quantity"] == 500
    assert rows_by_symbol["600000"]["takeprofit_configured"] is True
    assert rows_by_symbol["600000"]["takeprofit_tiers"] == [
        {"level": 1, "price": 10.2, "manual_enabled": True},
        {"level": 2, "price": 10.8, "manual_enabled": True},
        {"level": 3, "price": 11.5, "manual_enabled": False},
    ]
    assert rows_by_symbol["600000"]["active_stoploss_entry_count"] == 1
    assert rows_by_symbol["600000"]["open_entry_count"] == 0
    assert rows_by_symbol["600000"]["last_trigger"]["kind"] == "stoploss"
    assert rows_by_symbol["000001"]["position_quantity"] == 0
    assert rows_by_symbol["000001"]["takeprofit_configured"] is True
    assert rows_by_symbol["000001"]["has_active_stoploss"] is False


def test_management_overview_prefers_symbol_snapshot_market_value():
    service = TpslManagementService(
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount_adjusted": -5300.0,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 123456.0,
            "market_value_source": "bar_close_x_quantity",
        },
    )

    rows = service.get_overview()

    assert rows[0]["symbol"] == "600000"
    assert rows[0]["position_amount"] == 123456.0


def test_management_overview_prefers_v2_entry_bindings_without_legacy_stoploss_rows():
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "entry_id": "entry_v2_1",
            "symbol": "600000",
            "name": "浦发银行",
            "date": 20260313,
            "time": "09:30:00",
            "trade_time": 1773355800,
            "entry_price": 10.0,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "status": "OPEN",
        }
    )
    order_repository.entry_stoploss_bindings.append(
        {
            "entry_id": "entry_v2_1",
            "symbol": "600000",
            "stop_price": 9.2,
            "enabled": True,
        }
    )
    order_repository.stoploss_bindings.append(
        {
            "buy_lot_id": "legacy_lot_1",
            "symbol": "600000",
            "stop_price": 8.8,
            "enabled": True,
        }
    )

    service = TpslManagementService(
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 200,
                "amount_adjusted": -2000.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        stock_fills_loader=lambda symbol: [],
    )

    rows = service.get_overview()

    assert rows == [
        {
            "symbol": "600000",
            "name": "浦发银行",
            "position_quantity": 200,
            "position_amount": -2000.0,
            "takeprofit_configured": False,
            "takeprofit_tiers": [],
            "has_active_stoploss": True,
            "active_stoploss_entry_count": 1,
            "open_entry_count": 1,
            "last_trigger": None,
        }
    ]


def test_management_overview_uses_latest_event_query_instead_of_full_scan():
    class OverviewAwareTpslRepository(InMemoryTpslRepository):
        def __init__(self):
            super().__init__()
            self.latest_query_symbols = []

        def list_exit_trigger_events(
            self,
            *,
            symbol=None,
            batch_id=None,
            kind=None,
            limit=50,
        ):
            if symbol is None and batch_id is None and kind is None and limit is None:
                raise AssertionError("overview should not scan the full event stream")
            return super().list_exit_trigger_events(
                symbol=symbol,
                batch_id=batch_id,
                kind=kind,
                limit=limit,
            )

        def list_latest_exit_trigger_events_by_symbol(self, *, symbols=None):
            self.latest_query_symbols.append(set(symbols or []))
            return super().list_latest_exit_trigger_events_by_symbol(symbols=symbols)

    tpsl_repository = OverviewAwareTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [{"level": 1, "price": 10.8, "manual_enabled": True}],
    }
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_hist_only",
                "event_type": "stoploss_hit",
                "kind": "stoploss",
                "symbol": "300001",
                "batch_id": "sl_batch_hist",
                "created_at": "2026-03-13T11:00:00+00:00",
            },
            {
                "event_id": "evt_live",
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "created_at": "2026-03-13T10:00:00+00:00",
            },
        ]
    )

    service = TpslManagementService(
        tpsl_repository=tpsl_repository,
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount_adjusted": -5300.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
    )

    rows = service.get_overview()

    assert [item["symbol"] for item in rows] == ["600000"]
    assert rows[0]["last_trigger"]["event_id"] == "evt_live"
    assert tpsl_repository.latest_query_symbols == [{"600000"}]


def test_management_history_ignores_blank_optional_filters():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.events.append(
        {
            "event_id": "evt_tp_1",
            "event_type": "takeprofit_hit",
            "kind": "takeprofit",
            "symbol": "600000",
            "batch_id": "tp_batch_1",
            "buy_lot_ids": ["lot_open_1"],
            "created_at": "2026-03-13T09:59:00+00:00",
        }
    )

    service = TpslManagementService(
        tpsl_repository=tpsl_repository,
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [],
        symbol_position_loader=lambda symbol: None,
    )

    rows = service.list_history(
        symbol="600000",
        kind=" ",
        batch_id="",
        limit=20,
    )

    assert [item["event_id"] for item in rows] == ["evt_tp_1"]


def test_management_detail_assembles_entries_and_order_timeline():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.2, "manual_enabled": True},
            {"level": 2, "price": 10.8, "manual_enabled": True},
        ],
    }
    tpsl_repository.states["600000"] = {
        "symbol": "600000",
        "armed_levels": {1: False, 2: True},
        "last_triggered_level": 1,
    }
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_stop_1",
                "event_type": "stoploss_hit",
                "kind": "stoploss",
                "symbol": "600000",
                "batch_id": "sl_batch_1",
                "buy_lot_ids": ["lot_open_1"],
                "buy_lot_details": [
                    {"buy_lot_id": "lot_open_1", "stop_price": 9.2, "quantity": 200}
                ],
                "trigger_price": 9.1,
                "created_at": "2026-03-13T10:01:00+00:00",
            },
            {
                "event_id": "evt_tp_1",
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "level": 2,
                "buy_lot_ids": ["lot_open_1"],
                "buy_lot_details": [{"buy_lot_id": "lot_open_1", "quantity": 300}],
                "trigger_price": 10.8,
                "created_at": "2026-03-13T09:59:00+00:00",
            },
        ]
    )

    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.extend(
        [
            {
                "entry_id": "lot_open_1",
                "symbol": "600000",
                "name": "浦发银行",
                "date": 20260313,
                "time": "09:30:00",
                "trade_time": 1710000000,
                "entry_price": 10.0,
                "original_quantity": 300,
                "remaining_quantity": 200,
                "sell_history": [{"allocated_quantity": 100}],
                "status": "PARTIALLY_EXITED",
            },
            {
                "entry_id": "lot_closed_1",
                "symbol": "600000",
                "name": "浦发银行",
                "date": 20260312,
                "time": "09:30:00",
                "trade_time": 1709913600,
                "entry_price": 9.8,
                "original_quantity": 100,
                "remaining_quantity": 0,
                "sell_history": [{"allocated_quantity": 100}],
                "status": "CLOSED",
            },
        ]
    )
    order_repository.buy_lots.extend(
        [
            {
                "buy_lot_id": "lot_open_1",
                "symbol": "600000",
                "name": "浦发银行",
                "date": 20260313,
                "time": "09:30:00",
                "buy_price_real": 10.0,
                "original_quantity": 300,
                "remaining_quantity": 200,
                "sell_history": [{"allocated_quantity": 100}],
                "status": "partial",
            },
            {
                "buy_lot_id": "lot_closed_1",
                "symbol": "600000",
                "name": "浦发银行",
                "buy_price_real": 9.8,
                "original_quantity": 100,
                "remaining_quantity": 0,
                "sell_history": [{"allocated_quantity": 100}],
                "status": "closed",
            },
        ]
    )
    order_repository.entry_stoploss_bindings.append(
        {
            "binding_id": "bind_1",
            "entry_id": "lot_open_1",
            "symbol": "600000",
            "stop_price": 9.2,
            "enabled": True,
            "state": "active",
        }
    )
    order_repository.stoploss_bindings.append(
        {
            "binding_id": "bind_1",
            "buy_lot_id": "lot_open_1",
            "symbol": "600000",
            "stop_price": 9.2,
            "enabled": True,
            "state": "active",
        }
    )
    order_repository.order_requests.extend(
        [
            {
                "request_id": "req_stop_1",
                "symbol": "600000",
                "scope_type": "stoploss_batch",
                "scope_ref_id": "sl_batch_1",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T10:01:01+00:00",
            },
            {
                "request_id": "req_tp_1",
                "symbol": "600000",
                "scope_type": "takeprofit_batch",
                "scope_ref_id": "tp_batch_1",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T09:59:01+00:00",
            },
        ]
    )
    order_repository.orders.extend(
        [
            {
                "internal_order_id": "ord_stop_1",
                "request_id": "req_stop_1",
                "symbol": "600000",
                "state": "FILLED",
                "broker_order_id": "BRK-1",
                "submitted_at": "2026-03-13T10:01:02+00:00",
            },
            {
                "internal_order_id": "ord_tp_1",
                "request_id": "req_tp_1",
                "symbol": "600000",
                "state": "QUEUED",
                "broker_order_id": None,
                "submitted_at": None,
            },
        ]
    )
    order_repository.order_events.extend(
        [
            {
                "event_id": "oe_stop_1",
                "internal_order_id": "ord_stop_1",
                "event_type": "accepted",
                "state": "ACCEPTED",
                "created_at": "2026-03-13T10:01:01+00:00",
            },
            {
                "event_id": "oe_stop_2",
                "internal_order_id": "ord_stop_1",
                "event_type": "trade_reported",
                "state": "FILLED",
                "created_at": "2026-03-13T10:01:05+00:00",
            },
        ]
    )
    order_repository.trade_facts.append(
        {
            "trade_fact_id": "trade_stop_1",
            "internal_order_id": "ord_stop_1",
            "symbol": "600000",
            "quantity": 200,
            "price": 9.1,
            "trade_time": 1710000000,
        }
    )

    service = TpslManagementService(
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 200,
                "amount_adjusted": -2000.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        stock_fills_loader=lambda symbol: [],
    )

    detail = service.get_symbol_detail("sh600000", history_limit=10)

    assert detail["symbol"] == "600000"
    assert detail["name"] == "浦发银行"
    assert detail["position"]["quantity"] == 200
    assert detail["takeprofit"]["state"]["armed_levels"] == {1: False, 2: True}
    assert len(detail["entries"]) == 1
    assert detail["entries"][0]["entry_id"] == "lot_open_1"
    assert "buy_lots" not in detail
    assert detail["entries"][0]["stoploss"]["stop_price"] == 9.2
    assert len(detail["entry_slices"]) == 0
    assert detail["reconciliation"]["state"] == "aligned"
    assert detail["history"][0]["kind"] == "stoploss"
    assert detail["history"][0]["entry_ids"] == ["lot_open_1"]
    assert "buy_lot_ids" not in detail["history"][0]
    assert detail["history"][0]["order_requests"][0]["request_id"] == "req_stop_1"
    assert detail["history"][0]["orders"][0]["internal_order_id"] == "ord_stop_1"
    assert detail["history"][0]["trades"][0]["trade_fact_id"] == "trade_stop_1"
    assert detail["history"][1]["kind"] == "takeprofit"


def test_management_detail_prefers_symbol_snapshot_market_value():
    service = TpslManagementService(
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
                "amount_adjusted": 4800.0,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 234567.0,
            "market_value_source": "bar_close_x_quantity",
        },
        stock_fills_loader=lambda symbol: [],
    )

    detail = service.get_symbol_detail("600000")

    assert detail["position"]["quantity"] == 500
    assert detail["position"]["amount"] == 234567.0


def test_management_detail_exposes_entry_slices_and_reconciliation_summary():
    service = TpslManagementService(
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
                "amount_adjusted": 4800.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
    )

    detail = service.get_symbol_detail("600000")

    assert detail["entry_slices"] == []
    assert detail["reconciliation"]["broker_quantity"] == 500
    assert detail["reconciliation"]["ledger_quantity"] == 0
    assert detail["reconciliation"]["signed_gap_quantity"] == 500
    assert detail["reconciliation"]["state"] == "drift"


def test_management_detail_is_json_serializable_with_mongo_object_ids():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.events.append(
        {
            "_id": ObjectId(),
            "event_id": "evt_stop_1",
            "event_type": "stoploss_hit",
            "kind": "stoploss",
            "symbol": "600000",
            "batch_id": "sl_batch_1",
            "buy_lot_ids": ["lot_open_1"],
            "buy_lot_details": [
                {
                    "_id": ObjectId(),
                    "buy_lot_id": "lot_open_1",
                    "stop_price": 9.2,
                    "quantity": 200,
                }
            ],
            "trigger_price": 9.1,
            "created_at": "2026-03-13T10:01:00+00:00",
        }
    )

    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "_id": ObjectId(),
            "entry_id": "lot_open_1",
            "symbol": "600000",
            "name": "浦发银行",
            "date": 20260313,
            "time": "09:30:00",
            "trade_time": 1710000000,
            "entry_price": 10.0,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "sell_history": [{"_id": ObjectId(), "allocated_quantity": 100}],
            "status": "PARTIALLY_EXITED",
        }
    )
    order_repository.buy_lots.append(
        {
            "_id": ObjectId(),
            "buy_lot_id": "lot_open_1",
            "symbol": "600000",
            "name": "浦发银行",
            "date": 20260313,
            "time": "09:30:00",
            "buy_price_real": 10.0,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "sell_history": [{"_id": ObjectId(), "allocated_quantity": 100}],
            "status": "partial",
        }
    )
    order_repository.entry_stoploss_bindings.append(
        {
            "_id": ObjectId(),
            "binding_id": "bind_1",
            "entry_id": "lot_open_1",
            "symbol": "600000",
            "stop_price": 9.2,
            "enabled": True,
            "state": "active",
        }
    )
    order_repository.stoploss_bindings.append(
        {
            "_id": ObjectId(),
            "binding_id": "bind_1",
            "buy_lot_id": "lot_open_1",
            "symbol": "600000",
            "stop_price": 9.2,
            "enabled": True,
            "state": "active",
        }
    )
    order_repository.order_requests.append(
        {
            "_id": ObjectId(),
            "request_id": "req_stop_1",
            "symbol": "600000",
            "scope_type": "stoploss_batch",
            "scope_ref_id": "sl_batch_1",
            "state": "ACCEPTED",
            "created_at": "2026-03-13T10:01:01+00:00",
        }
    )
    order_repository.orders.append(
        {
            "_id": ObjectId(),
            "internal_order_id": "ord_stop_1",
            "request_id": "req_stop_1",
            "symbol": "600000",
            "state": "FILLED",
            "broker_order_id": "BRK-1",
            "submitted_at": "2026-03-13T10:01:02+00:00",
        }
    )
    order_repository.order_events.append(
        {
            "_id": ObjectId(),
            "event_id": "oe_stop_1",
            "internal_order_id": "ord_stop_1",
            "event_type": "accepted",
            "state": "ACCEPTED",
            "created_at": "2026-03-13T10:01:03+00:00",
        }
    )
    order_repository.trade_facts.append(
        {
            "_id": ObjectId(),
            "trade_fact_id": "trade_stop_1",
            "internal_order_id": "ord_stop_1",
            "symbol": "600000",
            "quantity": 200,
            "price": 9.1,
            "trade_time": 1710000000,
        }
    )

    service = TpslManagementService(
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "sh600000",
                "stock_code": "600000.SH",
                "name": "浦发银行",
                "quantity": 200,
                "amount_adjusted": -2000.0,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        stock_fills_loader=lambda symbol: [],
    )

    detail = service.get_symbol_detail("sh600000", history_limit=10)
    payload = json.loads(json.dumps(detail))

    assert payload["entries"][0]["entry_id"] == "lot_open_1"
    assert payload["entries"][0]["stoploss"]["stop_price"] == 9.2
    assert payload["history"][0]["order_requests"][0]["request_id"] == "req_stop_1"
