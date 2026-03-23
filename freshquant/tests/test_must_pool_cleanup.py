import importlib


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


def test_clean_must_pool_does_not_filter_by_forever(monkeypatch):
    freshquant_db = importlib.import_module("freshquant.db")

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
    monkeypatch.setattr(freshquant_db, "DBfreshquant", fake_db, raising=False)
    pool_general = importlib.reload(importlib.import_module("freshquant.pool.general"))

    pool_general.cleanMustPool()

    assert fake_db["must_pool"].delete_queries == [
        {"code": {"$in": ["600000", "000001"]}}
    ]
