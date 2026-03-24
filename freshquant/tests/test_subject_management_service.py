import json

from bson import ObjectId

from freshquant.subject_management.dashboard_service import (
    SubjectManagementDashboardService,
)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query=None):
        query = dict(query or {})
        rows = []
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                rows.append(dict(doc))
        return rows

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None


class FakeDatabase(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


class InMemoryTpslRepository:
    def __init__(self):
        self.profiles = {}
        self.states = {}
        self.events = []

    def find_takeprofit_profile(self, symbol):
        return self.profiles.get(symbol)

    def find_takeprofit_state(self, symbol):
        return self.states.get(symbol)

    def upsert_takeprofit_profile(self, document):
        self.profiles[document["symbol"]] = dict(document)
        return dict(document)

    def upsert_takeprofit_state(self, document):
        self.states[document["symbol"]] = dict(document)
        return dict(document)

    def list_takeprofit_profiles(self):
        return list(self.profiles.values())

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
            latest[symbol] = dict(item)
        return list(latest.values())


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.buy_lots = []
        self.stoploss_bindings = []

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


def test_subject_management_overview_aggregates_subject_configs_and_runtime():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "category": "银行",
                        "stop_loss_price": 9.2,
                        "initial_lot_amount": 80000,
                        "lot_amount": 50000,
                        "forever": True,
                    }
                ]
            ),
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "600000",
                        "BUY-1": 10.2,
                        "BUY-2": 9.9,
                        "BUY-3": 9.5,
                        "buy_enabled": [True, False, True],
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [
                    {
                        "code": "600000",
                        "buy_active": [True, False, True],
                        "last_hit_level": "BUY-2",
                        "last_hit_price": 9.88,
                        "last_hit_signal_time": "2026-03-16T10:30:00+08:00",
                    }
                ]
            ),
        }
    )
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.8, "manual_enabled": True},
            {"level": 2, "price": 11.3, "manual_enabled": False},
            {"level": 3, "price": 11.8, "manual_enabled": True},
        ],
    }
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_1",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "created_at": "2026-03-16T10:40:00+08:00",
            }
        ]
    )
    order_repository = InMemoryOrderManagementRepository()
    order_repository.buy_lots.extend(
        [
            {
                "buy_lot_id": "lot_1",
                "symbol": "600000",
                "remaining_quantity": 200,
            },
            {
                "buy_lot_id": "lot_2",
                "symbol": "600000",
                "remaining_quantity": 0,
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
                "symbol": "600000",
                "stop_price": 9.0,
                "enabled": False,
            },
        ]
    )

    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {
            "effective_state": "HOLDING_ONLY",
            "allow_open_min_bail": 800000.0,
            "holding_only_min_bail": 100000.0,
        },
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": 500000.0,
            "effective_limit": 500000.0,
            "using_override": True,
            "blocked": False,
        },
    )

    rows = service.get_overview()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000"
    assert rows[0]["must_pool"]["stop_loss_price"] == 9.2
    assert rows[0]["must_pool"]["initial_lot_amount"] == 80000
    assert rows[0]["guardian"]["enabled"] is True
    assert rows[0]["guardian"]["buy_1"] == 10.2
    assert rows[0]["guardian"]["buy_enabled"] == [True, False, True]
    assert rows[0]["guardian"]["last_hit_level"] == "BUY-2"
    assert rows[0]["takeprofit"]["tiers"][0]["level"] == 1
    assert rows[0]["takeprofit"]["tiers"][1]["enabled"] is False
    assert rows[0]["stoploss"]["active_count"] == 1
    assert rows[0]["stoploss"]["open_buy_lot_count"] == 1
    assert rows[0]["runtime"]["position_quantity"] == 500
    assert rows[0]["runtime"]["position_amount"] == 0.0
    assert rows[0]["runtime"]["last_trigger_time"] == "2026-03-16T10:40:00+08:00"
    assert rows[0]["position_limit_summary"]["effective_limit"] == 500000.0
    assert rows[0]["position_limit_summary"]["using_override"] is True


def test_subject_management_overview_prefers_symbol_snapshot_market_value():
    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 123456.0,
            "market_value_source": "bar_close_x_quantity",
        },
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        },
    )

    rows = service.get_overview()

    assert rows[0]["runtime"]["position_quantity"] == 500
    assert rows[0]["runtime"]["position_amount"] == 123456.0


def test_subject_management_overview_normalizes_must_pool_codes_before_grouping():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600000.SH",
                        "name": "浦发银行",
                        "category": "银行",
                        "stop_loss_price": 9.2,
                        "initial_lot_amount": 80000,
                        "lot_amount": 50000,
                        "forever": True,
                    }
                ]
            ),
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "600000",
                        "BUY-1": 10.2,
                        "BUY-2": 9.9,
                        "BUY-3": 9.5,
                        "buy_enabled": [True, False, True],
                        "enabled": True,
                    }
                ]
            ),
        }
    )

    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        },
    )

    rows = service.get_overview()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "600000"
    assert rows[0]["must_pool"]["symbol"] == "600000"
    assert rows[0]["must_pool"]["stop_loss_price"] == 9.2


def test_subject_management_detail_returns_must_pool_guardian_takeprofit_buy_lots_and_pm_summary():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "category": "银行",
                        "stop_loss_price": 9.2,
                        "initial_lot_amount": 80000,
                        "lot_amount": 50000,
                        "forever": True,
                    }
                ]
            ),
            "guardian_buy_grid_configs": FakeCollection(
                [
                    {
                        "code": "600000",
                        "BUY-1": 10.2,
                        "BUY-2": 9.9,
                        "BUY-3": 9.5,
                        "buy_enabled": [True, False, True],
                        "enabled": True,
                    }
                ]
            ),
            "guardian_buy_grid_states": FakeCollection(
                [
                    {
                        "code": "600000",
                        "buy_active": [True, False, True],
                        "last_hit_level": "BUY-2",
                        "last_hit_price": 9.88,
                        "last_hit_signal_time": "2026-03-16T10:30:00+08:00",
                    }
                ]
            ),
        }
    )
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.8, "manual_enabled": True},
            {"level": 2, "price": 11.3, "manual_enabled": False},
            {"level": 3, "price": 11.8, "manual_enabled": True},
        ],
    }
    tpsl_repository.states["600000"] = {
        "symbol": "600000",
        "armed_levels": {1: True, 2: False, 3: True},
    }
    order_repository = InMemoryOrderManagementRepository()
    order_repository.buy_lots.extend(
        [
            {
                "buy_lot_id": "lot_1",
                "symbol": "600000",
                "date": 20260316,
                "time": "10:31:00",
                "buy_price_real": 10.02,
                "original_quantity": 300,
                "remaining_quantity": 200,
            }
        ]
    )
    order_repository.stoploss_bindings.extend(
        [
            {
                "buy_lot_id": "lot_1",
                "symbol": "600000",
                "stop_price": 9.2,
                "enabled": True,
            }
        ]
    )

    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
                "avg_price": 10.023,
            }
        ],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {
            "effective_state": "HOLDING_ONLY",
            "allow_open_min_bail": 800000.0,
            "holding_only_min_bail": 100000.0,
        },
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": 500000.0,
            "effective_limit": 500000.0,
            "using_override": True,
            "blocked": True,
        },
    )

    detail = service.get_detail("600000.SH")

    assert detail["subject"]["symbol"] == "600000"
    assert detail["must_pool"]["lot_amount"] == 50000
    assert detail["guardian_buy_grid_config"]["buy_3"] == 9.5
    assert detail["guardian_buy_grid_config"]["buy_enabled"] == [True, False, True]
    assert detail["guardian_buy_grid_state"]["last_hit_level"] == "BUY-2"
    assert detail["takeprofit"]["tiers"][2]["level"] == 3
    assert detail["takeprofit"]["state"]["armed_levels"][2] is False
    assert len(detail["buy_lots"]) == 1
    assert detail["buy_lots"][0]["stoploss"]["stop_price"] == 9.2
    assert detail["runtime_summary"]["position_quantity"] == 500
    assert detail["runtime_summary"]["avg_price"] == 10.023
    assert detail["position_management_summary"]["effective_state"] == "HOLDING_ONLY"
    assert detail["position_limit_summary"]["effective_limit"] == 500000.0
    assert detail["position_limit_summary"]["blocked"] is True


def test_subject_management_detail_prefers_symbol_snapshot_market_value():
    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 234567.0,
            "market_value_source": "bar_close_x_quantity",
        },
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        },
    )

    detail = service.get_detail("600000")

    assert detail["runtime_summary"]["position_quantity"] == 500
    assert detail["runtime_summary"]["position_amount"] == 234567.0


def test_subject_management_detail_strips_mongo_ids_from_nested_documents():
    database = FakeDatabase()
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.states["002262"] = {
        "_id": ObjectId(),
        "symbol": "002262",
        "armed_levels": {1: True},
    }
    order_repository = InMemoryOrderManagementRepository()
    order_repository.buy_lots.extend(
        [
            {
                "_id": ObjectId(),
                "buy_lot_id": "lot_1",
                "symbol": "002262",
                "date": 20260316,
                "time": "10:31:00",
                "remaining_quantity": 200,
            }
        ]
    )
    order_repository.stoploss_bindings.extend(
        [
            {
                "_id": ObjectId(),
                "buy_lot_id": "lot_1",
                "symbol": "002262",
                "stop_price": 18.6,
                "enabled": True,
            }
        ]
    )

    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=tpsl_repository,
        order_repository=order_repository,
        position_loader=lambda: [],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        },
    )

    detail = service.get_detail("002262")

    json.dumps(detail)
    assert "_id" not in detail["takeprofit"]["state"]
    assert "_id" not in detail["buy_lots"][0]
    assert "_id" not in detail["buy_lots"][0]["stoploss"]


def test_subject_management_uses_default_position_loader_when_not_injected(monkeypatch):
    import freshquant.subject_management.dashboard_service as dashboard_service_module

    monkeypatch.setattr(
        dashboard_service_module,
        "_default_position_loader",
        lambda: [
            {
                "symbol": "002262.SZ",
                "name": "恩华药业",
                "quantity": 500,
                "amount": 12345.0,
            }
        ],
        raising=False,
    )

    service = dashboard_service_module.SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        },
    )

    rows = service.get_overview()
    detail = service.get_detail("002262")

    assert rows[0]["symbol"] == "002262"
    assert rows[0]["runtime"]["position_quantity"] == 500
    assert detail["runtime_summary"]["position_quantity"] == 500
    assert detail["runtime_summary"]["position_amount"] == 12345.0
