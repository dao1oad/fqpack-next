import importlib.util
from pathlib import Path


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.delete_queries = []

    def find(self, query=None):
        return list(self.docs)

    def delete_many(self, query):
        self.delete_queries.append(dict(query))


class FakeDatabase(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def load_pool_general_module():
    module_path = Path(__file__).resolve().parents[1] / "pool" / "general.py"
    spec = importlib.util.spec_from_file_location(
        "_freshquant_pool_general_under_test", module_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_clean_must_pool_does_not_filter_by_forever(monkeypatch):
    pool_general = load_pool_general_module()

    fake_db = FakeDatabase(
        {
            "xt_positions": FakeCollection(
                [
                    {"stock_code": "600000.SH"},
                    {"stock_code": "000001.SZ"},
                ]
            ),
            "must_pool": FakeCollection(),
        }
    )
    monkeypatch.setattr(pool_general, "DBfreshquant", fake_db, raising=False)

    pool_general.cleanMustPool()

    assert fake_db["must_pool"].delete_queries == [
        {"code": {"$in": ["600000", "000001"]}}
    ]
