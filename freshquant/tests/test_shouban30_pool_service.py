import importlib
import sys
import types
from pathlib import Path


class FakeResult:
    def __init__(self, acknowledged=True, deleted_count=0):
        self.acknowledged = acknowledged
        self.deleted_count = deleted_count


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, field_name, direction):
        reverse = direction < 0
        self.docs = sorted(
            self.docs,
            key=lambda item: _nested_get(item, field_name),
            reverse=reverse,
        )
        return self

    def __iter__(self):
        return iter(self.docs)


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(doc) for doc in (docs or [])]

    def find(self, query=None):
        query = query or {}
        return FakeCursor(
            [dict(doc) for doc in self.docs if _matches(doc, query)]
        )

    def find_one(self, query=None):
        query = query or {}
        for doc in self.docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return FakeResult()

    def update_one(self, query, update, upsert=False):
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs[index] = _apply_update(doc, update)
                return FakeResult()
        if upsert:
            created = dict(query)
            created = _apply_update(created, update)
            self.docs.append(created)
        return FakeResult()

    def delete_many(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, query)]
        return FakeResult(deleted_count=before - len(self.docs))

    def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs.pop(index)
                return FakeResult(deleted_count=1)
        return FakeResult(deleted_count=0)


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _nested_get(doc, dotted_key):
    current = doc
    for part in str(dotted_key).split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _matches(doc, query):
    for key, expected in (query or {}).items():
        actual = _nested_get(doc, key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _apply_update(doc, update):
    next_doc = dict(doc)
    for operator, payload in (update or {}).items():
        if operator == "$set":
            for key, value in payload.items():
                _nested_set(next_doc, key, value)
        elif operator == "$setOnInsert":
            for key, value in payload.items():
                if _nested_get(next_doc, key) is None:
                    _nested_set(next_doc, key, value)
    return next_doc


def _nested_set(doc, dotted_key, value):
    current = doc
    parts = str(dotted_key).split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _import_service_with_stubs(monkeypatch):
    called = {"must_pool": []}

    must_pool_module = types.ModuleType("freshquant.data.astock.must_pool")
    must_pool_module.import_pool = lambda *args: called["must_pool"].append(args)

    monkeypatch.setitem(
        sys.modules, "freshquant.data.astock.must_pool", must_pool_module
    )

    import freshquant.shouban30_pool_service as service

    service = importlib.reload(service)
    return service, called


def test_replace_pre_pool_only_replaces_shouban30_workspace_category(monkeypatch, tmp_path):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {"code": "000001", "name": "legacy", "category": "其他策略"},
                {
                    "code": "000002",
                    "name": "old",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 0},
                },
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    result = service.replace_pre_pool(
        [
            {
                "code6": "600001",
                "name": "new-one",
                "plate_key": "11",
                "plate_name": "robot",
                "provider": "xgb",
                "hit_count_window": 3,
                "latest_trade_date": "2026-03-05",
            },
            {
                "code6": "000333",
                "name": "new-two",
                "plate_key": "22",
                "plate_name": "chip",
                "provider": "xgb",
                "hit_count_window": 2,
                "latest_trade_date": "2026-03-06",
            },
        ],
        {
            "replace_scope": "current_filter",
            "stock_window_days": 30,
            "as_of_date": "2026-03-06",
            "selected_extra_filters": ["chanlun_passed"],
        },
    )

    saved_docs = list(fake_db["stock_pre_pools"].find({"category": "三十涨停Pro预选"}))
    assert result["saved_count"] == 2
    assert result["deleted_count"] == 1
    assert [doc["code"] for doc in saved_docs] == ["600001", "000333"]
    assert fake_db["stock_pre_pools"].find_one({"category": "其他策略"}) == {
        "code": "000001",
        "name": "legacy",
        "category": "其他策略",
    }


def test_replace_pre_pool_persists_workspace_order_in_extra(monkeypatch, tmp_path):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    service.replace_pre_pool(
        [
            {
                "code6": "600001",
                "name": "first",
                "plate_key": "11",
                "plate_name": "robot",
                "provider": "xgb",
            },
            {
                "code6": "000333",
                "name": "second",
                "plate_key": "11",
                "plate_name": "robot",
                "provider": "xgb",
            },
        ],
        {
            "replace_scope": "single_plate",
            "stock_window_days": 60,
            "as_of_date": "2026-03-06",
            "selected_extra_filters": [],
            "plate_key": "11",
        },
    )

    saved_docs = list(fake_db["stock_pre_pools"].find({"category": "三十涨停Pro预选"}))
    assert [doc["extra"]["shouban30_order"] for doc in saved_docs] == [0, 1]
    assert saved_docs[0]["extra"]["shouban30_replace_scope"] == "single_plate"
    assert saved_docs[0]["extra"]["shouban30_stock_window_days"] == 60


def test_sync_pre_pool_to_blk_keeps_workspace_order(monkeypatch, tmp_path):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "second",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 1},
                },
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 0},
                },
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    result = service.sync_pre_pool_to_blk()

    target = Path(tmp_path) / "T0002" / "blocknew" / "30RYZT.blk"
    assert result["success"] is True
    assert result["count"] == 2
    assert result["file_path"] == str(target)
    assert target.read_text(encoding="gbk").splitlines() == ["1600001", "0000333"]


def test_add_pre_pool_item_to_stock_pool_writes_shouban30_stock_category(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "alpha",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                    },
                }
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.add_pre_pool_item_to_stock_pool("600001")

    saved = fake_db["stock_pools"].find_one({"code": "600001"})
    assert result == "created"
    assert saved["category"] == "三十涨停Pro自选"
    assert saved["extra"]["shouban30_source"] == "pre_pool"
    assert saved["extra"]["shouban30_from_category"] == "三十涨停Pro预选"


def test_add_stock_pool_item_to_must_pool_uses_default_arguments(monkeypatch):
    service, called = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "alpha",
                    "category": "三十涨停Pro自选",
                }
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.add_stock_pool_item_to_must_pool("600001")

    assert result == "created"
    assert called["must_pool"] == [
        ("600001", "三十涨停Pro", 0.1, 50000, 50000, True)
    ]
