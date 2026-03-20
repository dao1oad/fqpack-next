import importlib
import sys
import types
from datetime import datetime

import pymongo


class FakeCursor:
    def __init__(self, collection, docs):
        self.collection = collection
        self.docs = list(docs)

    def sort(self, field_name, direction=None):
        self.collection.last_sort = (field_name, direction)
        if isinstance(field_name, list):
            for item_field, item_direction in reversed(field_name):
                reverse = item_direction == pymongo.DESCENDING
                self.docs = sorted(
                    self.docs, key=lambda item: item.get(item_field), reverse=reverse
                )
            return self

        reverse = direction == pymongo.DESCENDING
        self.docs = sorted(
            self.docs, key=lambda item: item.get(field_name), reverse=reverse
        )
        return self

    def skip(self, amount):
        self.collection.last_skip = amount
        self.docs = self.docs[amount:]
        return self

    def limit(self, amount):
        self.collection.last_limit = amount
        self.docs = self.docs[:amount]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)
        self.last_query = None
        self.last_sort = None
        self.last_skip = None
        self.last_limit = None

    def find(self, query):
        query = query or {}
        self.last_query = query
        filtered = [dict(doc) for doc in self.docs if _doc_matches_query(doc, query)]
        return FakeCursor(self, filtered)

    def find_one(self, query):
        query = query or {}
        self.last_query = query
        for doc in self.docs:
            if _doc_matches_query(doc, query):
                return dict(doc)
        return None


def _doc_matches_query(doc, query):
    for key, expected in query.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            allowed_values = expected.get("$in")
            if allowed_values is None or value not in allowed_values:
                return False
            continue
        if value != expected:
            return False
    return True


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _import_stock_service_with_stubs(monkeypatch):
    must_pool_module = types.ModuleType("freshquant.data.astock.must_pool")
    must_pool_module.import_pool = lambda *args, **kwargs: None

    signal_common_module = types.ModuleType("freshquant.signal.a_stock_common")
    signal_common_module.save_a_stock_pools = lambda *args, **kwargs: None

    strategy_module = types.ModuleType("freshquant.strategy")
    strategy_toolkit_module = types.ModuleType("freshquant.strategy.toolkit")
    strategy_grid_module = types.ModuleType("freshquant.strategy.toolkit.grid")
    strategy_grid_module.plan_grid_distribution = lambda *args, **kwargs: None

    monkeypatch.setitem(
        sys.modules, "freshquant.data.astock.must_pool", must_pool_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.signal.a_stock_common", signal_common_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.strategy", strategy_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.toolkit", strategy_toolkit_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.toolkit.grid", strategy_grid_module
    )

    import freshquant.stock_service as stock_service

    return importlib.reload(stock_service)


def test_get_stock_pre_pools_list_without_category_returns_deduped_rows(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "_id": "1",
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                },
                {
                    "_id": "2",
                    "code": "000001",
                    "name": "alpha",
                    "category": "三十涨停Pro预选",
                    "datetime": datetime(2026, 3, 6, 9, 31),
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_plate_key": "11",
                        "shouban30_provider": "xgb",
                    },
                },
                {
                    "_id": "3",
                    "code": "000002",
                    "name": "beta",
                    "category": "CLXS_10004",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 6, 14, 8),
                },
            ]
        )
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(
        stock_service,
        "fq_util_code_append_market_code",
        lambda code: f"{'sh' if str(code).startswith('6') else 'sz'}{code}",
    )

    result = stock_service.get_stock_pre_pools_list(page=1, category="")

    assert [row["code"] for row in result] == ["000001", "000002"]
    assert result[0]["sources"] == ["daily-screening", "shouban30"]
    assert result[0]["categories"] == ["CLXS_10001", "plate:11"]
    assert [row["symbol"] for row in result] == ["sz000001", "sz000002"]


def test_get_stock_pre_pools_list_with_category_filters_unified_categories(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "_id": "1",
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                },
                {
                    "_id": "2",
                    "code": "000001",
                    "name": "alpha",
                    "category": "三十涨停Pro预选",
                    "datetime": datetime(2026, 3, 6, 9, 31),
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_plate_key": "11",
                        "shouban30_provider": "xgb",
                    },
                },
                {
                    "_id": "3",
                    "code": "000002",
                    "name": "beta",
                    "category": "CLXS_10004",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 6, 14, 8),
                },
            ]
        )
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(
        stock_service,
        "fq_util_code_append_market_code",
        lambda code: f"{'sh' if str(code).startswith('6') else 'sz'}{code}",
    )

    result = stock_service.get_stock_pre_pools_list(page=1, category="plate:11")

    assert [row["code"] for row in result] == ["000001"]


def test_add_to_stock_pools_by_code_uses_unified_pre_pool_provenance(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10008",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 20, 9, 31),
                    "stop_loss_price": 9.8,
                    "extra": {"screening_run_id": "run-1"},
                    "sources": ["daily-screening", "shouban30"],
                    "categories": ["CLXS_10008", "plate:11"],
                    "memberships": [
                        {
                            "source": "daily-screening",
                            "category": "CLXS_10008",
                            "added_at": datetime(2026, 3, 20, 9, 31),
                            "expire_at": datetime(2026, 6, 16, 0, 0),
                            "extra": {"screening_run_id": "run-1"},
                        },
                        {
                            "source": "shouban30",
                            "category": "plate:11",
                            "added_at": datetime(2026, 3, 20, 9, 35),
                            "expire_at": None,
                            "extra": {"shouban30_plate_key": "11"},
                        },
                    ],
                }
            ]
        ),
        stock_pools=FakeCollection([]),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    captured = {}
    monkeypatch.setattr(
        stock_service,
        "save_a_stock_pools",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    result = stock_service.add_to_stock_pools_by_code("000001", days=20)

    assert result is True
    assert captured["kwargs"]["code"] == "000001"
    assert captured["kwargs"]["category"] == "CLXS_10008"
    assert captured["kwargs"]["sources"] == ["daily-screening", "shouban30"]
    assert captured["kwargs"]["categories"] == ["CLXS_10008", "plate:11"]
    assert {
        (item["source"], item["category"])
        for item in captured["kwargs"]["memberships"]
    } == {
        ("daily-screening", "CLXS_10008"),
        ("shouban30", "plate:11"),
    }


def test_get_stock_signal_list_for_must_pool_buys_filters_current_non_holding_must_pool(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_signals=FakeCollection(
            [
                {
                    "_id": "1",
                    "symbol": "sz000001",
                    "code": "000001",
                    "name": "alpha",
                    "period": "1m",
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 31),
                    "price": 10.2,
                    "stop_lose_price": 9.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
                {
                    "_id": "2",
                    "symbol": "sz000002",
                    "code": "000002",
                    "name": "beta",
                    "period": "1m",
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 32),
                    "price": 11.2,
                    "stop_lose_price": 10.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
                {
                    "_id": "3",
                    "symbol": "sz000003",
                    "code": "000003",
                    "name": "gamma",
                    "period": "1m",
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 33),
                    "price": 12.2,
                    "stop_lose_price": 11.7,
                    "position": "BUY_LONG",
                    "is_holding": True,
                },
                {
                    "_id": "4",
                    "symbol": "sz000004",
                    "code": "000004",
                    "name": "delta",
                    "period": "1m",
                    "remark": "回拉中枢下跌",
                    "fire_time": datetime(2026, 3, 15, 9, 34),
                    "price": 13.2,
                    "stop_lose_price": 13.7,
                    "position": "SELL_SHORT",
                    "is_holding": False,
                },
            ]
        ),
        must_pool=FakeCollection(
            [
                {"code": "000001"},
                {"code": "000003"},
                {"code": "000004"},
            ]
        ),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.get_stock_signal_list(
        page=1, size=1000, category="must_pool_buys"
    )

    assert result == [
        {
            "symbol": "sz000001",
            "code": "000001",
            "name": "alpha",
            "period": "1m",
            "remark": "回拉中枢上涨",
            "fire_time": "2026-03-15 09:31",
            "created_at": "2026-03-15 09:31",
            "price": 10.2,
            "stop_lose_price": 9.7,
            "position": "BUY_LONG",
            "is_holding": False,
        }
    ]
    assert fake_db["stock_signals"].last_query == {
        "is_holding": False,
        "position": "BUY_LONG",
        "code": {"$in": ["000001", "000003", "000004"]},
    }
    assert fake_db["stock_signals"].last_skip == 0
    assert fake_db["stock_signals"].last_limit == 1000


def test_get_stock_signal_list_exposes_created_at_with_fire_time_fallback(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_signals=FakeCollection(
            [
                {
                    "_id": "1",
                    "symbol": "sz000001",
                    "code": "000001",
                    "name": "alpha",
                    "period": "30m",
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 31),
                    "price": 10.2,
                    "stop_lose_price": 9.7,
                    "position": "BUY_LONG",
                    "is_holding": True,
                }
            ]
        )
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.get_stock_signal_list(page=1, size=1000, category="holdings")

    assert result == [
        {
            "symbol": "sz000001",
            "code": "000001",
            "name": "alpha",
            "period": "30m",
            "remark": "回拉中枢上涨",
            "fire_time": "2026-03-15 09:31",
            "created_at": "2026-03-15 09:31",
            "price": 10.2,
            "stop_lose_price": 9.7,
            "position": "BUY_LONG",
            "is_holding": True,
        }
    ]


def test_get_stock_model_signal_list_returns_sorted_realtime_screen_docs(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        realtime_screen_multi_period=FakeCollection(
            [
                {
                    "_id": "1",
                    "datetime": datetime(2026, 3, 15, 10, 0),
                    "created_at": datetime(2026, 3, 15, 10, 0, 5),
                    "code": "000001",
                    "name": "alpha",
                    "period": "15min",
                    "model": "CLX10001",
                    "close": 10.1,
                    "stop_loss_price": 9.8,
                    "source": "XTData_Realtime",
                },
                {
                    "_id": "2",
                    "datetime": datetime(2026, 3, 15, 10, 30),
                    "created_at": datetime(2026, 3, 15, 10, 30, 7),
                    "code": "000002",
                    "name": "beta",
                    "period": "30min",
                    "model": "CLX10012",
                    "close": 20.2,
                    "stop_loss_price": 19.6,
                    "source": "XTData_Realtime",
                },
            ]
        )
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.get_stock_model_signal_list(page=1, size=1)

    assert result == [
        {
            "datetime": "2026-03-15 10:30",
            "created_at": "2026-03-15 10:30:07",
            "code": "000002",
            "name": "beta",
            "period": "30min",
            "model": "CLX10012",
            "close": 20.2,
            "stop_loss_price": 19.6,
            "source": "XTData_Realtime",
        }
    ]
    assert fake_db["realtime_screen_multi_period"].last_sort == (
        [("datetime", pymongo.DESCENDING), ("created_at", pymongo.DESCENDING)],
        None,
    )
    assert fake_db["realtime_screen_multi_period"].last_skip == 0
    assert fake_db["realtime_screen_multi_period"].last_limit == 1


def test_get_stock_model_signal_list_supports_second_page(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        realtime_screen_multi_period=FakeCollection(
            [
                {
                    "_id": "1",
                    "datetime": datetime(2026, 3, 15, 10, 0),
                    "created_at": datetime(2026, 3, 15, 10, 0, 5),
                    "code": "000001",
                    "name": "alpha",
                    "period": "15min",
                    "model": "CLX10001",
                    "close": 10.1,
                    "stop_loss_price": 9.8,
                    "source": "XTData_Realtime",
                },
                {
                    "_id": "2",
                    "datetime": datetime(2026, 3, 15, 10, 30),
                    "created_at": datetime(2026, 3, 15, 10, 30, 7),
                    "code": "000002",
                    "name": "beta",
                    "period": "30min",
                    "model": "CLX10012",
                    "close": 20.2,
                    "stop_loss_price": 19.6,
                    "source": "XTData_Realtime",
                },
            ]
        )
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.get_stock_model_signal_list(page=2, size=1)

    assert result == [
        {
            "datetime": "2026-03-15 10:00",
            "created_at": "2026-03-15 10:00:05",
            "code": "000001",
            "name": "alpha",
            "period": "15min",
            "model": "CLX10001",
            "close": 10.1,
            "stop_loss_price": 9.8,
            "source": "XTData_Realtime",
        }
    ]
    assert fake_db["realtime_screen_multi_period"].last_skip == 1
    assert fake_db["realtime_screen_multi_period"].last_limit == 1
