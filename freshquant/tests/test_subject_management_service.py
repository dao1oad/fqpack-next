import importlib
import json
import sys
import types
from typing import Any

import pytest
from bson import ObjectId

import freshquant.instrument as instrument_package

dashboard_service_module = None
SubjectManagementDashboardService = None


class FakeMongoClient(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = {}
        return dict.__getitem__(self, name)


@pytest.fixture(autouse=True)
def _install_dashboard_service_stubs(monkeypatch):
    global dashboard_service_module, SubjectManagementDashboardService

    code_module: Any = types.ModuleType("freshquant.util.code")
    code_module.normalize_to_base_code = (
        lambda value: str(value or "").strip().split(".")[0]
    )
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_module)

    db_module: Any = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = {}
    db_module.MongoClient = FakeMongoClient()
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)

    strategy_common_module: Any = types.ModuleType("freshquant.strategy.common")
    strategy_common_module.get_trade_amount = lambda code: 50000
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.common", strategy_common_module
    )

    instrument_module: Any = types.ModuleType("freshquant.instrument.general")
    instrument_module.query_instrument_info = lambda symbol: None
    monkeypatch.setitem(sys.modules, "freshquant.instrument.general", instrument_module)
    monkeypatch.setattr(instrument_package, "general", instrument_module, raising=False)

    order_repository_module: Any = types.ModuleType(
        "freshquant.order_management.repository"
    )

    class OrderManagementRepository:
        def list_buy_lots(self, symbol=None, buy_lot_ids=None):
            return []

        def list_stoploss_bindings(self, symbol=None, enabled=None):
            return []

    order_repository_module.OrderManagementRepository = OrderManagementRepository
    monkeypatch.setitem(
        sys.modules, "freshquant.order_management.repository", order_repository_module
    )

    tpsl_repository_module: Any = types.ModuleType("freshquant.tpsl.repository")

    class TpslRepository:
        def find_takeprofit_profile(self, symbol):
            return None

        def find_takeprofit_state(self, symbol):
            return None

        def list_takeprofit_profiles(self):
            return []

        def list_latest_exit_trigger_events_by_symbol(self, *, symbols=None):
            return []

    tpsl_repository_module.TpslRepository = TpslRepository
    monkeypatch.setitem(
        sys.modules, "freshquant.tpsl.repository", tpsl_repository_module
    )

    monkeypatch.delitem(sys.modules, "freshquant.data.astock.must_pool", raising=False)
    monkeypatch.delitem(
        sys.modules,
        "freshquant.subject_management.dashboard_service",
        raising=False,
    )

    import freshquant.subject_management.dashboard_service as _dashboard_service_module

    dashboard_service_module = importlib.reload(_dashboard_service_module)
    SubjectManagementDashboardService = (
        dashboard_service_module.SubjectManagementDashboardService
    )
    yield


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

    def list_exit_trigger_events(self, *, symbol=None, batch_id=None, limit=50):
        rows = list(self.events)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if batch_id is not None:
            rows = [item for item in rows if item.get("batch_id") == batch_id]
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        if limit is not None:
            rows = rows[: max(int(limit), 0)]
        return [dict(item) for item in rows]

    def list_latest_exit_trigger_events_by_symbol(self, *, symbols=None, event_types=None):
        allowed = None if symbols is None else set(symbols)
        allowed_event_types = (
            None
            if event_types is None
            else {str(item).strip() for item in event_types if str(item).strip()}
        )
        latest = {}
        rows = list(self.events)
        rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        for item in rows:
            symbol = item.get("symbol")
            if not symbol:
                continue
            if allowed is not None and symbol not in allowed:
                continue
            if (
                allowed_event_types is not None
                and str(item.get("event_type") or "").strip() not in allowed_event_types
            ):
                continue
            if symbol in latest:
                continue
            latest[symbol] = dict(item)
        return list(latest.values())


class InMemoryOrderManagementRepository:
    def __init__(self):
        self.position_entries = []
        self.entry_stoploss_bindings = []
        self.open_entry_slices = []
        self.buy_lots = []
        self.stoploss_bindings = []

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

    def list_open_entry_slices(self, *, symbol=None, entry_ids=None):
        rows = list(self.open_entry_slices)
        if symbol is not None:
            rows = [item for item in rows if item.get("symbol") == symbol]
        if entry_ids is not None:
            allowed = set(entry_ids)
            rows = [item for item in rows if item.get("entry_id") in allowed]
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
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "level": 2,
                "created_at": "2026-03-16T10:40:00+08:00",
            },
            {
                "event_id": "evt_2",
                "event_type": "entry_stoploss_hit",
                "kind": "stoploss",
                "symbol": "600000",
                "batch_id": "sl_batch_1",
                "created_at": "2026-03-16T10:42:00+08:00",
            }
        ]
    )
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.extend(
        [
            {
                "entry_id": "lot_1",
                "symbol": "600000",
                "date": 20260316,
                "time": "10:31:00",
                "trade_time": 1773628260,
                "entry_price": 10.02,
                "original_quantity": 300,
                "remaining_quantity": 200,
                "status": "OPEN",
            },
            {
                "entry_id": "lot_2",
                "symbol": "600000",
                "date": 20260315,
                "time": "09:30:00",
                "trade_time": 1773547800,
                "entry_price": 9.88,
                "original_quantity": 200,
                "remaining_quantity": 0,
                "status": "CLOSED",
            },
        ]
    )
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
                "symbol": "600000",
                "stop_price": 9.0,
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
    assert rows[0]["stoploss"]["active_stoploss_entry_count"] == 1
    assert rows[0]["stoploss"]["open_entry_count"] == 1
    assert rows[0]["runtime"]["position_quantity"] == 500
    assert rows[0]["runtime"]["position_amount"] == 0.0
    assert rows[0]["runtime"]["last_trigger_kind"] == "stoploss"
    assert rows[0]["runtime"]["last_trigger_level"] is None
    assert rows[0]["runtime"]["last_trigger_time"] == "2026-03-16T10:42:00+08:00"
    assert rows[0]["runtime"]["last_takeprofit_trigger_level"] == 2
    assert (
        rows[0]["runtime"]["last_takeprofit_trigger_time"]
        == "2026-03-16T10:40:00+08:00"
    )
    assert (
        rows[0]["runtime"]["last_entry_stoploss_trigger_time"]
        == "2026-03-16T10:42:00+08:00"
    )
    assert rows[0]["position_limit_summary"]["effective_limit"] == 500000.0
    assert rows[0]["position_limit_summary"]["using_override"] is True


def test_subject_management_overview_clears_recent_trigger_after_auto_rearm():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.8, "manual_enabled": True},
            {"level": 2, "price": 11.3, "manual_enabled": True},
            {"level": 3, "price": 11.8, "manual_enabled": False},
        ],
    }
    tpsl_repository.states["600000"] = {
        "symbol": "600000",
        "armed_levels": {1: True, 2: True, 3: False},
        "last_rearm_reason": "new_buy_below_lowest_tier",
        "last_rearmed_at": "2026-03-16T10:45:00+00:00",
    }
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_1",
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "created_at": "2026-03-16T10:40:00+00:00",
            },
            {
                "event_id": "evt_2",
                "event_type": "entry_stoploss_hit",
                "kind": "stoploss",
                "symbol": "600000",
                "batch_id": "sl_batch_1",
                "created_at": "2026-03-16T10:41:00+00:00",
            }
        ]
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=tpsl_repository,
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

    assert rows[0]["takeprofit"]["state"]["armed_levels"] == {
        1: True,
        2: True,
        3: False,
    }
    assert rows[0]["runtime"]["last_trigger_kind"] == "stoploss"
    assert rows[0]["runtime"]["last_trigger_level"] is None
    assert rows[0]["runtime"]["last_trigger_time"] == "2026-03-16T10:41:00+00:00"
    assert rows[0]["runtime"]["last_takeprofit_trigger_level"] is None
    assert rows[0]["runtime"]["last_takeprofit_trigger_time"] is None
    assert (
        rows[0]["runtime"]["last_entry_stoploss_trigger_time"]
        == "2026-03-16T10:41:00+00:00"
    )


def test_subject_management_overview_falls_back_to_guardian_state_updated_at_when_hit_time_missing():
    database = FakeDatabase(
        {
            "guardian_buy_grid_states": FakeCollection(
                [
                    {
                        "code": "600271",
                        "buy_active": [False, True, True],
                        "last_hit_level": "BUY-2",
                        "last_hit_price": 8.38,
                        "last_hit_signal_time": None,
                        "updated_at": "2026-04-04T09:30:00+08:00",
                    }
                ]
            )
        }
    )

    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600271.SH",
                "name": "航天信息",
                "quantity": 100,
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

    assert rows[0]["guardian"]["last_hit_level"] == "BUY-2"
    assert rows[0]["guardian"]["last_hit_signal_time"] == "2026-04-04T09:30:00+08:00"


def test_subject_management_detail_exposes_split_takeprofit_and_entry_stoploss_triggers():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.events.extend(
        [
            {
                "event_id": "evt_takeprofit",
                "event_type": "takeprofit_hit",
                "kind": "takeprofit",
                "symbol": "600000",
                "batch_id": "tp_batch_1",
                "level": 3,
                "created_at": "2026-03-18T09:50:00+08:00",
            },
            {
                "event_id": "evt_stoploss",
                "event_type": "entry_stoploss_hit",
                "kind": "stoploss",
                "symbol": "600000",
                "batch_id": "sl_batch_1",
                "created_at": "2026-03-18T09:55:00+08:00",
            },
        ]
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=tpsl_repository,
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "avg_price": 10.023,
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

    detail = service.get_detail("600000")

    assert detail["runtime_summary"]["last_trigger_kind"] == "stoploss"
    assert detail["runtime_summary"]["last_trigger_level"] is None
    assert (
        detail["runtime_summary"]["last_trigger_time"]
        == "2026-03-18T09:55:00+08:00"
    )
    assert detail["runtime_summary"]["last_takeprofit_trigger_level"] == 3
    assert (
        detail["runtime_summary"]["last_takeprofit_trigger_time"]
        == "2026-03-18T09:50:00+08:00"
    )
    assert (
        detail["runtime_summary"]["last_entry_stoploss_trigger_time"]
        == "2026-03-18T09:55:00+08:00"
    )


def test_subject_management_overview_strips_mongo_id_from_takeprofit_state():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["600000"] = {
        "symbol": "600000",
        "tiers": [
            {"level": 1, "price": 10.8, "manual_enabled": True},
        ],
    }
    tpsl_repository.states["600000"] = {
        "_id": ObjectId(),
        "symbol": "600000",
        "armed_levels": {1: True},
    }

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=tpsl_repository,
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 100,
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

    assert "_id" not in rows[0]["takeprofit"]["state"]
    assert rows[0]["takeprofit"]["state"]["armed_levels"] == {1: True}


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


def test_subject_management_overview_uses_default_symbol_limit_batch_loader_once(
    monkeypatch,
):
    import freshquant.subject_management.dashboard_service as sm_dashboard_module

    call_counts = {"dashboard": 0, "symbol": 0}

    def fake_symbol_limit_map_loader():
        call_counts["dashboard"] += 1
        return {
            "600000": {
                "symbol": "600000",
                "default_limit": 800000.0,
                "override_limit": 500000.0,
                "effective_limit": 500000.0,
                "using_override": True,
                "blocked": False,
            },
            "000001": {
                "symbol": "000001",
                "default_limit": 800000.0,
                "override_limit": None,
                "effective_limit": 800000.0,
                "using_override": False,
                "blocked": False,
            },
        }

    def fake_symbol_limit_loader(symbol):
        call_counts["symbol"] += 1
        return {
            "symbol": symbol,
            "default_limit": 800000.0,
            "override_limit": None,
            "effective_limit": 800000.0,
            "using_override": False,
            "blocked": False,
        }

    monkeypatch.setattr(
        sm_dashboard_module,
        "_default_symbol_limit_map_loader",
        fake_symbol_limit_map_loader,
    )
    monkeypatch.setattr(
        sm_dashboard_module,
        "_default_symbol_limit_loader",
        fake_symbol_limit_loader,
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {"symbol": "600000.SH", "name": "浦发银行", "quantity": 500},
            {"symbol": "000001.SZ", "name": "平安银行", "quantity": 300},
        ],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
    )

    rows = service.get_overview()

    assert len(rows) == 2
    assert call_counts == {"dashboard": 1, "symbol": 0}
    assert rows[0]["position_limit_summary"]["effective_limit"] in {500000.0, 800000.0}


def test_subject_management_overview_keeps_rows_when_symbol_limit_loader_rejects_untracked_symbol():
    service = SubjectManagementDashboardService(
        database=FakeDatabase(
            {
                "must_pool": FakeCollection(
                    [
                        {
                            "code": "512000",
                            "name": "中证全指证券公司ETF",
                        }
                    ]
                )
            }
        ),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: (_ for _ in ()).throw(
            ValueError("symbol is not tracked by holdings or pools")
        ),
    )

    rows = service.get_overview()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "512000"
    assert rows[0]["position_limit_summary"]["available"] is False
    assert (
        rows[0]["position_limit_summary"]["error"]
        == "symbol is not tracked by holdings or pools"
    )
    assert rows[0]["position_limit_summary"]["using_override"] is False


def test_subject_management_overview_excludes_symbols_without_holdings_or_must_pool():
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.profiles["002594"] = {
        "symbol": "002594",
        "tiers": [
            {"level": 1, "price": 110.98, "manual_enabled": True},
            {"level": 2, "price": 116.19, "manual_enabled": True},
            {"level": 3, "price": 127.49, "manual_enabled": True},
        ],
    }

    service = SubjectManagementDashboardService(
        database=FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(
                    [
                        {
                            "code": "002594",
                            "BUY-1": 98.21,
                            "BUY-2": 93.66,
                            "BUY-3": 89.21,
                            "buy_enabled": [True, True, True],
                            "enabled": True,
                        }
                    ]
                ),
                "guardian_buy_grid_states": FakeCollection(
                    [
                        {
                            "code": "002594",
                            "buy_active": [True, True, True],
                            "last_reset_reason": "sell_trade_fact",
                        }
                    ]
                ),
            }
        ),
        tpsl_repository=tpsl_repository,
        order_repository=InMemoryOrderManagementRepository(),
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

    rows = service.get_overview()

    assert rows == []


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


def test_subject_management_detail_returns_must_pool_guardian_takeprofit_entries_and_pm_summary():
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
    order_repository.position_entries.extend(
        [
            {
                "entry_id": "lot_1",
                "symbol": "600000",
                "date": 20260316,
                "time": "10:31:00",
                "trade_time": 1773628260,
                "entry_price": 10.02,
                "original_quantity": 300,
                "remaining_quantity": 200,
                "name": "浦发银行",
                "status": "OPEN",
            }
        ]
    )
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
    order_repository.entry_stoploss_bindings.extend(
        [
            {
                "entry_id": "lot_1",
                "symbol": "600000",
                "stop_price": 9.2,
                "enabled": True,
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
    assert len(detail["entries"]) == 1
    assert detail["entries"][0]["entry_id"] == "lot_1"
    assert "buy_lots" not in detail
    assert detail["entries"][0]["stoploss"]["stop_price"] == 9.2
    assert detail["runtime_summary"]["position_quantity"] == 500
    assert detail["runtime_summary"]["avg_price"] == 10.023
    assert detail["position_management_summary"]["effective_state"] == "HOLDING_ONLY"
    assert detail["position_limit_summary"]["effective_limit"] == 500000.0
    assert detail["position_limit_summary"]["blocked"] is True


def test_subject_management_detail_exposes_entry_slices_and_latest_price_remaining_market_value():
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "entry_id": "entry_cluster_1",
            "symbol": "600104",
            "date": 20260331,
            "time": "10:31:00",
            "trade_time": 1774924260,
            "entry_price": 10.02,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "status": "OPEN",
            "aggregation_members": [
                {
                    "broker_order_key": "buy_ord_a",
                    "trade_fact_id": "tf_a",
                    "quantity": 100,
                    "entry_price": 10.0,
                    "trade_time": 1774924260,
                    "date": 20260331,
                    "time": "10:31:00",
                    "trading_day": 20260331,
                },
                {
                    "broker_order_key": "buy_ord_b",
                    "trade_fact_id": "tf_b",
                    "quantity": 200,
                    "entry_price": 10.03,
                    "trade_time": 1774924380,
                    "date": 20260331,
                    "time": "10:33:00",
                    "trading_day": 20260331,
                },
            ],
            "aggregation_window": {
                "start_trade_time": 1774924260,
                "end_trade_time": 1774924380,
                "trading_day": 20260331,
                "member_count": 2,
            },
        }
    )
    order_repository.entry_stoploss_bindings.append(
        {
            "entry_id": "entry_cluster_1",
            "symbol": "600104",
            "stop_price": 9.5,
            "enabled": True,
        }
    )
    order_repository.open_entry_slices.extend(
        [
            {
                "entry_slice_id": "slice_1",
                "entry_id": "entry_cluster_1",
                "symbol": "600104",
                "slice_seq": 1,
                "guardian_price": 9.8,
                "original_quantity": 100,
                "remaining_quantity": 80,
                "remaining_amount": 784.0,
                "status": "OPEN",
            },
            {
                "entry_slice_id": "slice_2",
                "entry_id": "entry_cluster_1",
                "symbol": "600104",
                "slice_seq": 2,
                "guardian_price": 9.6,
                "original_quantity": 200,
                "remaining_quantity": 120,
                "remaining_amount": 1152.0,
                "status": "OPEN",
            },
        ]
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600104.SH",
                "name": "上汽集团",
                "quantity": 200,
                "avg_price": 10.023,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "close_price": 10.88,
            "price_source": "xt_positions_last_price",
            "market_value": 2176.0,
            "market_value_source": "xt_positions_market_value",
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

    detail = service.get_detail("600104")

    assert len(detail["entries"]) == 1
    entry = detail["entries"][0]
    assert entry["aggregation_members"][0]["broker_order_key"] == "buy_ord_a"
    assert entry["aggregation_members"][1]["broker_order_key"] == "buy_ord_b"
    assert entry["aggregation_window"]["member_count"] == 2
    assert [item["entry_slice_id"] for item in entry["entry_slices"]] == [
        "slice_1",
        "slice_2",
    ]
    assert entry["latest_price"] == 10.88
    assert entry["latest_price_source"] == "xt_positions_last_price"
    assert entry["remaining_market_value"] == 2176.0
    assert entry["remaining_market_value_source"] == "latest_price_x_remaining_quantity"


def test_subject_management_detail_remaining_market_value_falls_back_to_avg_price_without_latest_price():
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "entry_id": "entry_cluster_fallback",
            "symbol": "600104",
            "date": 20260331,
            "time": "10:31:00",
            "trade_time": 1774924260,
            "entry_price": 10.02,
            "original_quantity": 300,
            "remaining_quantity": 200,
            "status": "OPEN",
        }
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600104.SH",
                "name": "上汽集团",
                "quantity": 200,
                "avg_price": 10.023,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 2004.6,
            "market_value_source": "xt_positions_market_value",
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

    detail = service.get_detail("600104")

    entry = detail["entries"][0]
    assert entry["latest_price"] is None
    assert entry["remaining_market_value"] == 2004.6
    assert entry["remaining_market_value_source"] == "avg_price_x_remaining_quantity"


def test_subject_management_detail_derives_latest_price_from_market_value_when_close_price_is_zero():
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "entry_id": "entry_cluster_zero_price",
            "symbol": "600104",
            "date": 20260331,
            "time": "10:31:00",
            "trade_time": 1774924260,
            "entry_price": 10.02,
            "original_quantity": 300,
            "remaining_quantity": 50,
            "status": "OPEN",
        }
    )

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600104.SH",
                "name": "上汽集团",
                "quantity": 200,
                "avg_price": 10.023,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "close_price": 0.0,
            "price_source": "xt_positions_last_price",
            "quantity": 200,
            "market_value": 2176.0,
            "market_value_source": "xt_positions_market_value",
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

    detail = service.get_detail("600104")

    entry = detail["entries"][0]
    assert entry["latest_price"] == 10.88
    assert entry["latest_price_source"] == "xt_positions_market_value_div_quantity"
    assert entry["remaining_market_value"] == 544.0
    assert entry["remaining_market_value_source"] == "latest_price_x_remaining_quantity"


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


def test_subject_management_detail_returns_base_config_summary_defaults_when_must_pool_missing():
    database = FakeDatabase(
        {
            "params": FakeCollection(
                [
                    {
                        "code": "guardian",
                        "value": {
                            "stock": {
                                "lot_amount": 50000,
                            }
                        },
                    }
                ]
            )
        }
    )
    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [
            {
                "symbol": "600271.SH",
                "name": "航天信息",
                "quantity": 44600,
                "amount": 384006.0,
            }
        ],
        symbol_position_loader=lambda symbol: {
            "symbol": symbol,
            "market_value": 384006.0,
            "market_value_source": "xt_positions_market_value",
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

    detail = service.get_detail("600271")
    summary = detail["base_config_summary"]

    assert summary["category"]["configured"] is False
    assert summary["category"]["effective_value"] is None
    assert summary["category"]["effective_source"] == "unconfigured"
    assert summary["stop_loss_price"]["configured"] is False
    assert summary["stop_loss_price"]["effective_value"] is None
    assert summary["stop_loss_price"]["effective_source"] == "unconfigured"
    assert summary["initial_lot_amount"]["configured"] is False
    assert summary["initial_lot_amount"]["effective_value"] == 100000
    assert (
        summary["initial_lot_amount"]["effective_source"]
        == "default_initial_lot_amount"
    )
    assert summary["lot_amount"]["configured"] is False
    assert summary["lot_amount"]["effective_value"] == 50000
    assert summary["lot_amount"]["effective_source"] == "guardian.stock.lot_amount"


def test_subject_management_detail_ignores_exchange_suffix_in_instrument_strategy_lot_amount():
    database = FakeDatabase(
        {
            "params": FakeCollection(
                [
                    {
                        "code": "guardian",
                        "value": {
                            "stock": {
                                "lot_amount": 50000,
                            }
                        },
                    }
                ]
            ),
            "instrument_strategy": FakeCollection(
                [
                    {
                        "instrument_code": "600271.SH",
                        "lot_amount": 90000,
                    }
                ]
            ),
        }
    )
    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
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

    detail = service.get_detail("600271")
    summary = detail["base_config_summary"]

    assert summary["lot_amount"]["configured"] is False
    assert summary["lot_amount"]["effective_value"] == 50000
    assert summary["lot_amount"]["effective_source"] == "guardian.stock.lot_amount"


def test_subject_management_detail_marks_provenance_category_as_unconfigured():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600271",
                        "name": "航天信息",
                        "category": "",
                        "manual_category": "",
                        "sources": ["shouban30"],
                        "categories": ["plate:11"],
                        "memberships": [
                            {
                                "source": "shouban30",
                                "category": "plate:11",
                                "added_at": "2026-03-20T09:35:00+08:00",
                                "expire_at": None,
                                "extra": {"shouban30_plate_key": "11"},
                            }
                        ],
                    }
                ]
            )
        }
    )
    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
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

    detail = service.get_detail("600271")
    summary = detail["base_config_summary"]

    assert detail["must_pool"]["category"] == "plate:11"
    assert summary["category"]["configured"] is False
    assert summary["category"]["configured_value"] is None
    assert summary["category"]["effective_value"] == "plate:11"
    assert summary["category"]["effective_source"] == "must_pool.provenance"


def test_subject_management_detail_reads_v2_entries_without_legacy_buy_lots():
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.append(
        {
            "entry_id": "entry_v2_1",
            "symbol": "600000",
            "name": "浦发银行",
            "date": 20260316,
            "time": "10:31:00",
            "trade_time": 1773618660,
            "entry_price": 10.02,
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

    service = SubjectManagementDashboardService(
        database=FakeDatabase(),
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=order_repository,
        position_loader=lambda: [
            {
                "symbol": "600000.SH",
                "name": "浦发银行",
                "quantity": 500,
                "amount": 5010.0,
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

    detail = service.get_detail("600000")

    assert len(detail["entries"]) == 1
    assert detail["entries"][0]["entry_id"] == "entry_v2_1"
    assert detail["entries"][0]["stoploss"]["stop_price"] == 9.2
    assert "buy_lots" not in detail


def test_subject_management_detail_strips_mongo_ids_from_nested_documents():
    database = FakeDatabase()
    tpsl_repository = InMemoryTpslRepository()
    tpsl_repository.states["002262"] = {
        "_id": ObjectId(),
        "symbol": "002262",
        "armed_levels": {1: True},
    }
    order_repository = InMemoryOrderManagementRepository()
    order_repository.position_entries.extend(
        [
            {
                "_id": ObjectId(),
                "entry_id": "lot_1",
                "symbol": "002262",
                "date": 20260316,
                "time": "10:31:00",
                "trade_time": 1773628260,
                "entry_price": 18.88,
                "original_quantity": 200,
                "remaining_quantity": 200,
                "status": "OPEN",
            }
        ]
    )
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
    order_repository.entry_stoploss_bindings.extend(
        [
            {
                "_id": ObjectId(),
                "entry_id": "lot_1",
                "symbol": "002262",
                "stop_price": 18.6,
                "enabled": True,
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
    assert "_id" not in detail["entries"][0]
    assert "_id" not in detail["entries"][0]["stoploss"]


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


def test_subject_management_detail_exposes_must_pool_provenance():
    database = FakeDatabase(
        {
            "must_pool": FakeCollection(
                [
                    {
                        "code": "600000",
                        "name": "浦发银行",
                        "category": "银行",
                        "manual_category": "银行",
                        "stop_loss_price": 9.2,
                        "initial_lot_amount": 80000,
                        "lot_amount": 50000,
                        "forever": True,
                        "sources": ["daily-screening", "shouban30"],
                        "categories": ["CLXS_10008", "plate:11"],
                        "memberships": [
                            {
                                "source": "daily-screening",
                                "category": "CLXS_10008",
                                "added_at": "2026-03-20T09:31:00+08:00",
                                "expire_at": None,
                                "extra": {"screening_run_id": "run-1"},
                            },
                            {
                                "source": "shouban30",
                                "category": "plate:11",
                                "added_at": "2026-03-20T09:35:00+08:00",
                                "expire_at": None,
                                "extra": {"shouban30_plate_key": "11"},
                            },
                        ],
                        "workspace_order_hint": 7,
                    }
                ]
            )
        }
    )
    service = SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
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

    detail = service.get_detail("600000.SH")

    assert detail["must_pool"]["manual_category"] == "银行"
    assert detail["must_pool"]["sources"] == ["daily-screening", "shouban30"]
    assert detail["must_pool"]["categories"] == ["CLXS_10008", "plate:11"]
    assert detail["must_pool"]["memberships"][1]["category"] == "plate:11"
    assert detail["must_pool"]["workspace_order_hint"] == 7


def test_default_symbol_limit_map_loader_reads_symbol_position_limit_rows(monkeypatch):
    import freshquant.subject_management.dashboard_service as sm_dashboard_module

    pm_module = types.ModuleType("freshquant.position_management.dashboard_service")

    class PositionManagementDashboardService:
        def get_dashboard(self):
            return {
                "symbol_position_limits": {
                    "rows": [
                        {
                            "symbol": "600271",
                            "default_limit": 800000.0,
                            "override_limit": None,
                            "effective_limit": 800000.0,
                            "using_override": False,
                            "blocked": False,
                            "blocked_reason": "buy_allowed",
                            "market_value": 384006.0,
                            "market_value_source": "xt_positions_market_value",
                        }
                    ]
                }
            }

    pm_module.PositionManagementDashboardService = PositionManagementDashboardService
    monkeypatch.setitem(
        sys.modules,
        "freshquant.position_management.dashboard_service",
        pm_module,
    )

    rows = sm_dashboard_module._default_symbol_limit_map_loader()

    assert rows["600271"]["effective_limit"] == 800000.0
    assert rows["600271"]["market_value"] == 384006.0
