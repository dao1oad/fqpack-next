from __future__ import annotations


class _FakeCollection:
    def __init__(self, documents=None):
        self.documents = list(documents or [])

    def find_one(self, query):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None


class _FakeDatabase:
    def __init__(self, collections=None):
        self.collections = {
            name: _FakeCollection(documents)
            for name, documents in (collections or {}).items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


def test_get_trade_amount_falls_back_to_50000_when_all_sources_missing(monkeypatch):
    import freshquant.strategy.common as common_module

    monkeypatch.setattr(common_module, "DBfreshquant", _FakeDatabase(), raising=False)
    assert common_module.get_trade_amount("999999.SH") == 50000
