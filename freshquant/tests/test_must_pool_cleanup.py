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
    pool_general = importlib.import_module("freshquant.pool.general")

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
    monkeypatch.setattr(pool_general, "DBfreshquant", fake_db)
    pool_general = importlib.reload(pool_general)
    monkeypatch.setattr(pool_general, "DBfreshquant", fake_db)

    pool_general.cleanMustPool()

    assert fake_db["must_pool"].delete_queries == [
        {"code": {"$in": ["600000", "000001"]}}
    ]
