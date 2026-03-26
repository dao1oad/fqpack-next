from __future__ import annotations

import sys
import types


class _ObjectId:
    pass


class _OrderManagementRepository:
    def list_buy_lots(self, symbol=None, buy_lot_ids=None):
        return []

    def list_stoploss_bindings(self, symbol=None, enabled=None):
        return []


class _TpslRepository:
    def find_takeprofit_profile(self, symbol):
        return None

    def find_takeprofit_state(self, symbol):
        return None

    def list_takeprofit_profiles(self):
        return []

    def list_latest_exit_trigger_events_by_symbol(self, *, symbols=None):
        return []


bson_module = types.ModuleType("bson")
bson_module.ObjectId = _ObjectId
sys.modules.setdefault("bson", bson_module)

order_repository_module = types.ModuleType("freshquant.order_management.repository")
order_repository_module.OrderManagementRepository = _OrderManagementRepository
sys.modules.setdefault(
    "freshquant.order_management.repository",
    order_repository_module,
)

tpsl_repository_module = types.ModuleType("freshquant.tpsl.repository")
tpsl_repository_module.TpslRepository = _TpslRepository
sys.modules.setdefault("freshquant.tpsl.repository", tpsl_repository_module)

code_module = types.ModuleType("freshquant.util.code")
code_module.normalize_to_base_code = lambda value: str(value or "").split(".")[0]
sys.modules.setdefault("freshquant.util.code", code_module)

from freshquant.subject_management.dashboard_service import (  # noqa: E402
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


class InMemoryTpslRepository(_TpslRepository):
    pass


class InMemoryOrderManagementRepository(_OrderManagementRepository):
    pass


def _build_service(database):
    return SubjectManagementDashboardService(
        database=database,
        tpsl_repository=InMemoryTpslRepository(),
        order_repository=InMemoryOrderManagementRepository(),
        position_loader=lambda: [],
        symbol_position_loader=lambda symbol: None,
        pm_summary_loader=lambda: {},
        symbol_limit_loader=lambda symbol: {},
    )


def test_overview_ignores_symbol_sourced_only_from_guardian_state():
    service = _build_service(
        FakeDatabase(
            {
                "guardian_buy_grid_states": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "buy_active": [True, True, True],
                            "last_reset_reason": "sell_trade_fact",
                        }
                    ]
                )
            }
        )
    )

    rows = service.get_overview()

    assert rows == []


def test_overview_keeps_guardian_state_for_symbol_present_in_guardian_config():
    service = _build_service(
        FakeDatabase(
            {
                "guardian_buy_grid_configs": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "BUY-1": 10.2,
                            "BUY-2": 9.9,
                            "BUY-3": 9.5,
                            "buy_enabled": [True, True, True],
                            "enabled": True,
                        }
                    ]
                ),
                "guardian_buy_grid_states": FakeCollection(
                    [
                        {
                            "code": "000001",
                            "buy_active": [False, True, True],
                            "last_hit_level": "BUY-1",
                            "last_hit_price": 10.18,
                        }
                    ]
                ),
            }
        )
    )

    rows = service.get_overview()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "000001"
    assert rows[0]["guardian"]["last_hit_level"] == "BUY-1"
    assert rows[0]["guardian"]["last_hit_price"] == 10.18
