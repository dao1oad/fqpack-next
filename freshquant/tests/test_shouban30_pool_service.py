import importlib
import sys
import types
from datetime import datetime
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
        return FakeCursor([dict(doc) for doc in self.docs if _matches(doc, query)])

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


def test_replace_pre_pool_only_replaces_shouban30_workspace_category(
    monkeypatch, tmp_path
):
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
            "days": 60,
            "end_date": "2026-03-06",
            "selected_extra_filters": [],
            "plate_key": "11",
        },
    )

    saved_docs = list(fake_db["stock_pre_pools"].find({"category": "三十涨停Pro预选"}))
    assert [doc["extra"]["shouban30_order"] for doc in saved_docs] == [0, 1]
    assert saved_docs[0]["extra"]["shouban30_replace_scope"] == "single_plate"
    assert saved_docs[0]["extra"]["shouban30_days"] == 60
    assert saved_docs[0]["extra"]["shouban30_end_date"] == "2026-03-06"
    assert saved_docs[0]["extra"]["shouban30_stock_window_days"] == 60
    assert saved_docs[0]["extra"]["shouban30_as_of_date"] == "2026-03-06"


def test_append_pre_pool_appends_only_missing_codes_and_keeps_existing_order(
    monkeypatch,
):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                    },
                }
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.append_pre_pool(
        [
            {
                "code6": "600001",
                "name": "first-updated",
                "plate_key": "11",
                "plate_name": "robot",
                "provider": "xgb",
            },
            {
                "code6": "000333",
                "name": "second",
                "plate_key": "22",
                "plate_name": "chip",
                "provider": "jygs",
            },
        ],
        {
            "replace_scope": "single_plate",
            "days": 30,
            "end_date": "2026-03-06",
            "selected_extra_filters": [],
            "plate_key": "22",
        },
    )

    saved_docs = service.list_pre_pool()
    assert result == {
        "appended_count": 1,
        "skipped_count": 1,
        "category": "三十涨停Pro预选",
    }
    assert [doc["code6"] for doc in saved_docs] == ["600001", "000333"]
    assert saved_docs[0]["name"] == "first"
    assert saved_docs[1]["extra"]["shouban30_order"] == 1
    assert saved_docs[1]["extra"]["shouban30_plate_name"] == "chip"


def test_append_pre_pool_uses_next_order_after_existing_order_gap(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 0},
                },
                {
                    "code": "600002",
                    "name": "second",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 2},
                },
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.append_pre_pool(
        [{"code6": "000333", "name": "third", "provider": "xgb"}],
        {"replace_scope": "single_plate"},
    )

    saved_docs = service.list_pre_pool()
    assert result["appended_count"] == 1
    assert [doc["code6"] for doc in saved_docs] == ["600001", "600002", "000333"]
    assert saved_docs[2]["extra"]["shouban30_order"] == 3


def test_append_pre_pool_keeps_single_row_and_adds_membership(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "alpha",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                    "extra": {
                        "screening_branch": "clxs",
                        "screening_model_key": "CLXS_10001",
                    },
                }
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.append_pre_pool(
        [
            {
                "code6": "600001",
                "name": "alpha",
                "plate_key": "11",
                "plate_name": "robot",
                "provider": "xgb",
            }
        ],
        {
            "replace_scope": "single_plate",
            "days": 30,
            "end_date": "2026-03-06",
            "selected_extra_filters": [],
            "plate_key": "11",
        },
    )

    rows = service.list_pre_pool()

    assert result == {
        "appended_count": 1,
        "skipped_count": 0,
        "category": "三十涨停Pro预选",
    }
    assert len(fake_db["stock_pre_pools"].docs) == 1
    assert [row["code6"] for row in rows] == ["600001"]
    assert rows[0]["sources"] == ["daily-screening", "shouban30"]
    assert rows[0]["categories"] == ["CLXS_10001", "plate:11"]
    assert rows[0]["extra"]["shouban30_order"] == 0


def test_list_pre_pool_returns_unified_rows_not_category_subset_duplicates(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                    "extra": {"screening_branch": "clxs"},
                },
                {
                    "code": "000001",
                    "name": "alpha",
                    "category": "三十涨停Pro预选",
                    "datetime": datetime(2026, 3, 6, 9, 31),
                    "extra": {
                        "shouban30_order": 1,
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                        "shouban30_provider": "xgb",
                    },
                },
                {
                    "code": "000333",
                    "name": "beta",
                    "category": "三十涨停Pro预选",
                    "datetime": datetime(2026, 3, 6, 9, 32),
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_plate_key": "22",
                        "shouban30_plate_name": "chip",
                        "shouban30_provider": "jygs",
                    },
                },
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    rows = service.list_pre_pool()

    assert [row["code6"] for row in rows] == ["000333", "000001"]
    alpha = next(row for row in rows if row["code6"] == "000001")
    assert alpha["sources"] == ["daily-screening", "shouban30"]
    assert alpha["categories"] == ["CLXS_10001", "plate:11"]


def test_delete_pre_pool_item_deletes_entire_code_record(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                    "extra": {"screening_branch": "clxs"},
                },
                {
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
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.delete_pre_pool_item("000001")

    assert result["deleted"] is True
    assert service.list_pre_pool() == []
    assert fake_db["stock_pre_pools"].find_one({"code": "000001"}) is None


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


def test_sync_pre_pool_to_blk_falls_back_to_settings_tdx_home(monkeypatch, tmp_path):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 0},
                }
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.delenv("TDX_HOME", raising=False)
    monkeypatch.setattr(
        service,
        "bootstrap_config",
        types.SimpleNamespace(tdx=types.SimpleNamespace(home=str(tmp_path))),
        raising=False,
    )

    result = service.sync_pre_pool_to_blk()

    target = Path(tmp_path) / "T0002" / "blocknew" / "30RYZT.blk"
    assert result["file_path"] == str(target)
    assert target.read_text(encoding="gbk").splitlines() == ["1600001"]


def test_sync_stock_pool_to_blk_uses_explicit_workspace_order_when_present(
    monkeypatch, tmp_path
):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "second",
                    "category": "三十涨停Pro自选",
                    "datetime": datetime(2026, 3, 6, 9, 31),
                    "extra": {"shouban30_order": 1},
                },
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro自选",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                    "extra": {"shouban30_order": 0},
                },
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    result = service.sync_stock_pool_to_blk()

    target = Path(tmp_path) / "T0002" / "blocknew" / "30RYZT.blk"
    assert result["success"] is True
    assert result["count"] == 2
    assert result["file_path"] == str(target)
    assert target.read_text(encoding="gbk").splitlines() == ["1600001", "0000333"]


def test_list_stock_pool_falls_back_to_datetime_desc_when_order_missing(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "second",
                    "category": "三十涨停Pro自选",
                    "datetime": datetime(2026, 3, 5, 9, 31),
                },
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro自选",
                    "datetime": datetime(2026, 3, 6, 9, 31),
                },
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    items = service.list_stock_pool()

    assert [item["code6"] for item in items] == ["600001", "000333"]


def test_clear_pre_pool_removes_entire_unified_pool_and_syncs_blk(
    monkeypatch, tmp_path
):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 0},
                },
                {
                    "code": "000333",
                    "name": "second",
                    "category": "三十涨停Pro预选",
                    "extra": {"shouban30_order": 1},
                },
                {"code": "300001", "name": "legacy", "category": "其他策略"},
            ]
        ),
        stock_pools=FakeCollection(),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    result = service.clear_pre_pool()

    target = Path(tmp_path) / "T0002" / "blocknew" / "30RYZT.blk"
    assert result["deleted_count"] == 3
    assert result["category"] == "三十涨停Pro预选"
    assert result["blk_sync"] == {
        "success": True,
        "file_path": str(target),
        "count": 0,
    }
    assert fake_db["stock_pre_pools"].docs == []
    assert target.read_text(encoding="gbk").splitlines() == []


def test_clear_stock_pool_succeeds_for_empty_workspace_and_syncs_blk(
    monkeypatch, tmp_path
):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(
            [
                {"code": "600001", "name": "legacy", "category": "其他策略"},
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)
    monkeypatch.setenv("TDX_HOME", str(tmp_path))

    result = service.clear_stock_pool()

    target = Path(tmp_path) / "T0002" / "blocknew" / "30RYZT.blk"
    assert result["deleted_count"] == 0
    assert result["category"] == "三十涨停Pro自选"
    assert result["blk_sync"] == {
        "success": True,
        "file_path": str(target),
        "count": 0,
    }
    assert fake_db["stock_pools"].find_one({"category": "其他策略"}) == {
        "code": "600001",
        "name": "legacy",
        "category": "其他策略",
    }
    assert target.read_text(encoding="gbk").splitlines() == []


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


def test_add_pre_pool_item_to_stock_pool_skips_existing_without_overwrite(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "fresh-name",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                    },
                }
            ]
        ),
        stock_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "legacy-name",
                    "category": "三十涨停Pro自选",
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_source": "legacy",
                    },
                }
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.add_pre_pool_item_to_stock_pool("600001")

    assert result == "already_exists"
    assert fake_db["stock_pools"].find_one({"code": "600001"}) == {
        "code": "600001",
        "name": "legacy-name",
        "category": "三十涨停Pro自选",
        "extra": {
            "shouban30_order": 0,
            "shouban30_source": "legacy",
        },
    }


def test_add_pre_pool_item_to_stock_pool_appends_after_existing_order_gap(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "third",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                    },
                }
            ]
        ),
        stock_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 0},
                },
                {
                    "code": "600002",
                    "name": "second",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 2},
                },
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.add_pre_pool_item_to_stock_pool("000333")

    assert result == "created"
    saved_docs = service.list_stock_pool()
    assert [doc["code6"] for doc in saved_docs] == ["600001", "600002", "000333"]
    assert saved_docs[2]["extra"]["shouban30_order"] == 3


def test_sync_pre_pool_to_stock_pool_appends_missing_codes_in_pre_pool_order(
    monkeypatch,
):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                    },
                },
                {
                    "code": "900001",
                    "name": "exists",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 1,
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "12",
                        "shouban30_plate_name": "bank",
                    },
                },
                {
                    "code": "000333",
                    "name": "third",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 2,
                        "shouban30_provider": "jygs",
                        "shouban30_plate_key": "13",
                        "shouban30_plate_name": "chip",
                    },
                },
            ]
        ),
        stock_pools=FakeCollection(
            [
                {
                    "code": "900001",
                    "name": "exists",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 0},
                }
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.sync_pre_pool_to_stock_pool()

    assert result == {
        "appended_count": 2,
        "skipped_count": 1,
        "category": "三十涨停Pro自选",
    }
    assert [item["code6"] for item in service.list_stock_pool()] == [
        "900001",
        "600001",
        "000333",
    ]
    saved_docs = list(fake_db["stock_pools"].find({"category": "三十涨停Pro自选"}))
    by_code = {doc["code"]: doc for doc in saved_docs}
    assert by_code["600001"]["extra"]["shouban30_order"] == 1
    assert by_code["000333"]["extra"]["shouban30_order"] == 2
    assert by_code["000333"]["extra"]["shouban30_plate_name"] == "chip"


def test_sync_pre_pool_to_stock_pool_appends_after_existing_order_gap(monkeypatch):
    service, _ = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "third",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 0,
                        "shouban30_provider": "xgb",
                        "shouban30_plate_key": "11",
                        "shouban30_plate_name": "robot",
                    },
                },
                {
                    "code": "300001",
                    "name": "fourth",
                    "category": "三十涨停Pro预选",
                    "extra": {
                        "shouban30_order": 1,
                        "shouban30_provider": "jygs",
                        "shouban30_plate_key": "12",
                        "shouban30_plate_name": "chip",
                    },
                },
            ]
        ),
        stock_pools=FakeCollection(
            [
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 0},
                },
                {
                    "code": "600002",
                    "name": "second",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 2},
                },
            ]
        ),
        must_pool=FakeCollection(),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.sync_pre_pool_to_stock_pool()

    assert result["appended_count"] == 2
    saved_docs = service.list_stock_pool()
    assert [doc["code6"] for doc in saved_docs] == [
        "600001",
        "600002",
        "000333",
        "300001",
    ]
    assert saved_docs[2]["extra"]["shouban30_order"] == 3
    assert saved_docs[3]["extra"]["shouban30_order"] == 4


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
    assert called["must_pool"] == [("600001", "三十涨停Pro", 0.1, 50000, 50000, True)]


def test_add_stock_pool_item_to_must_pool_returns_updated_when_existing(monkeypatch):
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
        must_pool=FakeCollection([{"code": "600001", "category": "已有分类"}]),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    result = service.add_stock_pool_item_to_must_pool("600001")

    assert result == "updated"
    assert called["must_pool"] == [("600001", "三十涨停Pro", 0.1, 50000, 50000, True)]


def test_sync_stock_pool_to_must_pool_uses_stock_pool_order_and_returns_counts(
    monkeypatch,
):
    service, called = _import_service_with_stubs(monkeypatch)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(),
        stock_pools=FakeCollection(
            [
                {
                    "code": "000333",
                    "name": "second",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 1},
                },
                {
                    "code": "600001",
                    "name": "first",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 0},
                },
                {
                    "code": "300001",
                    "name": "third",
                    "category": "三十涨停Pro自选",
                    "extra": {"shouban30_order": 2},
                },
            ]
        ),
        must_pool=FakeCollection(
            [
                {"code": "600001", "category": "三十涨停Pro"},
                {"code": "300001", "category": "三十涨停Pro"},
            ]
        ),
    )
    monkeypatch.setattr(service, "DBfreshquant", fake_db)

    before_codes = [item["code6"] for item in service.list_stock_pool()]
    result = service.sync_stock_pool_to_must_pool()
    after_codes = [item["code6"] for item in service.list_stock_pool()]

    assert result == {
        "created_count": 1,
        "updated_count": 2,
        "total_count": 3,
        "category": "三十涨停Pro",
    }
    assert before_codes == ["600001", "000333", "300001"]
    assert after_codes == before_codes
    assert called["must_pool"] == [
        ("600001", "三十涨停Pro", 0.1, 50000, 50000, True),
        ("000333", "三十涨停Pro", 0.1, 50000, 50000, True),
        ("300001", "三十涨停Pro", 0.1, 50000, 50000, True),
    ]
