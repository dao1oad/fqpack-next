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
        buy_lot_id=None,
        limit=50,
    ):
        rows = list(self.events)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if batch_id is not None:
            rows = [item for item in rows if item.get("batch_id") == batch_id]
        if kind is not None:
            rows = [item for item in rows if item.get("kind") == kind]
        if buy_lot_id is not None:
            rows = [
                item
                for item in rows
                if buy_lot_id in list(item.get("buy_lot_ids") or [])
            ]
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        if limit is None:
            return rows
        return rows[: int(limit)]


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.buy_lots = []
        self.stoploss_bindings = []
        self.order_requests = []
        self.orders = []
        self.order_events = []
        self.trade_facts = []

    def list_buy_lots(self, symbol=None, buy_lot_ids=None):
        rows = list(self.buy_lots)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if buy_lot_ids is not None:
            allowed = set(buy_lot_ids)
            rows = [item for item in rows if item.get("buy_lot_id") in allowed]
        return rows

    def list_stoploss_bindings(self, symbol=None, enabled=None):
        rows = list(self.stoploss_bindings)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if enabled is not None:
            rows = [item for item in rows if bool(item.get("enabled")) == bool(enabled)]
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


def test_management_overview_unions_holdings_and_configured_symbols():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [{"level": 1, "price": 10.8, "manual_enabled": True}],
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
    )

    rows = service.get_overview()
    rows_by_symbol = {item["symbol"]: item for item in rows}

    assert set(rows_by_symbol) == {"600000", "000001"}
    assert rows_by_symbol["600000"]["name"] == "浦发银行"
    assert rows_by_symbol["600000"]["position_quantity"] == 500
    assert rows_by_symbol["600000"]["takeprofit_configured"] is True
    assert rows_by_symbol["600000"]["active_stoploss_buy_lot_count"] == 1
    assert rows_by_symbol["600000"]["last_trigger"]["kind"] == "stoploss"
    assert rows_by_symbol["000001"]["position_quantity"] == 0
    assert rows_by_symbol["000001"]["takeprofit_configured"] is True
    assert rows_by_symbol["000001"]["has_active_stoploss"] is False


def test_management_detail_assembles_buy_lots_and_order_timeline():
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
    )

    detail = service.get_symbol_detail("sh600000", history_limit=10)

    assert detail["symbol"] == "600000"
    assert detail["name"] == "浦发银行"
    assert detail["position"]["quantity"] == 200
    assert detail["takeprofit"]["state"]["armed_levels"] == {1: False, 2: True}
    assert len(detail["buy_lots"]) == 1
    assert detail["buy_lots"][0]["buy_lot_id"] == "lot_open_1"
    assert detail["buy_lots"][0]["stoploss"]["stop_price"] == 9.2
    assert detail["history"][0]["kind"] == "stoploss"
    assert detail["history"][0]["order_requests"][0]["request_id"] == "req_stop_1"
    assert detail["history"][0]["orders"][0]["internal_order_id"] == "ord_stop_1"
    assert detail["history"][0]["trades"][0]["trade_fact_id"] == "trade_stop_1"
    assert detail["history"][1]["kind"] == "takeprofit"
