import importlib
import sys
import types

import pymongo


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, field_name, direction):
        reverse = direction == pymongo.DESCENDING
        self.docs = sorted(
            self.docs, key=lambda item: item.get(field_name), reverse=reverse
        )
        return self

    def skip(self, amount):
        self.docs = self.docs[amount:]
        return self

    def limit(self, amount):
        self.docs = self.docs[:amount]
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query):
        query = query or {}
        filtered = [
            dict(doc)
            for doc in self.docs
            if all(doc.get(key) == expected for key, expected in query.items())
        ]
        return FakeCursor(filtered)


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


def test_get_stock_pre_pools_list_without_category_returns_all(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "_id": "1",
                    "code": "000001",
                    "name": "alpha",
                    "category": "first",
                    "datetime": "2026-03-05 09:31:00",
                },
                {
                    "_id": "2",
                    "code": "000002",
                    "name": "beta",
                    "category": "second",
                    "datetime": "2026-03-05 14:08:00",
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

    assert [row["code"] for row in result] == ["000002", "000001"]
    assert [row["symbol"] for row in result] == ["sz000002", "sz000001"]


def test_get_stock_pre_pools_list_with_category_still_filters(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "_id": "1",
                    "code": "000001",
                    "name": "alpha",
                    "category": "first",
                    "datetime": "2026-03-05 09:31:00",
                },
                {
                    "_id": "2",
                    "code": "000002",
                    "name": "beta",
                    "category": "second",
                    "datetime": "2026-03-05 14:08:00",
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

    result = stock_service.get_stock_pre_pools_list(page=1, category="first")

    assert [row["code"] for row in result] == ["000001"]
