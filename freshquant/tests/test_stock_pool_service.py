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

    def update_one(self, query, update):
        query = query or {}
        update = update or {}
        self.last_query = query
        self.last_update = update
        for doc in self.docs:
            if _doc_matches_query(doc, query):
                doc.update(update.get("$set", {}))
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        return types.SimpleNamespace(matched_count=0, modified_count=0)


def _doc_matches_query(doc, query):
    for key, expected in query.items():
        value = doc.get(key)
        if isinstance(expected, dict):
            allowed_values = expected.get("$in")
            if allowed_values is None or value not in allowed_values:
                return False
            continue
        # Mongo 数组字段用字符串匹配即“包含该元素”（如 tags 数组）
        if isinstance(value, list) and not isinstance(expected, list):
            if expected not in value:
                return False
            continue
        if value != expected:
            return False
    return True


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def _import_stock_service_with_stubs(monkeypatch):
    db_module = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = {}
    db_module.MongoClient = object()
    db_module.DBQuantAxis = object()
    db_module.DBGantt = object()
    db_module.DBScreening = object()
    db_module.DBOrderManagement = object()
    db_module.DBQA = object()

    code_module = types.ModuleType("freshquant.util.code")
    code_module.fq_util_code_append_market_code = lambda code: code
    code_module.normalize_to_base_code = (
        lambda code: str(code or "")
        .replace(".SH", "")
        .replace(".SZ", "")
        .replace("sh", "")
        .replace("sz", "")[-6:]
        .zfill(6)
    )

    must_pool_module = types.ModuleType("freshquant.data.astock.must_pool")
    must_pool_module.import_pool = lambda *args, **kwargs: True

    signal_common_module = types.ModuleType("freshquant.signal.a_stock_common")
    signal_common_module.save_a_stock_pools = lambda *args, **kwargs: None

    strategy_module = types.ModuleType("freshquant.strategy")
    strategy_common_module = types.ModuleType("freshquant.strategy.common")
    strategy_common_module.get_trade_amount = lambda code=None: 100
    strategy_toolkit_module = types.ModuleType("freshquant.strategy.toolkit")
    strategy_grid_module = types.ModuleType("freshquant.strategy.toolkit.grid")
    strategy_grid_module.plan_grid_distribution = lambda *args, **kwargs: None
    # stock_service 模块级 import queryMustPoolCodes（pool.general）：
    # 必须一并 stub，否则 reload stock_service 会首次执行真实 pool.general，
    # 遇到被 stub 的 freshquant.util.code（缺 fq_util_code_append_market_code_suffix）
    # 抛 ImportError（shard 组合改变导入顺序时暴露）。
    pool_general_module = types.ModuleType("freshquant.pool.general")
    pool_general_module.queryMustPoolCodes = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "freshquant.pool.general", pool_general_module)

    monkeypatch.setitem(
        sys.modules, "freshquant.data.astock.must_pool", must_pool_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)
    monkeypatch.setitem(sys.modules, "freshquant.util.code", code_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.signal.a_stock_common", signal_common_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.strategy", strategy_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.common", strategy_common_module
    )
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

    def fake_save_a_stock_pools(**kwargs):
        captured.setdefault("kwargs", kwargs)
        fake_db["stock_pools"].docs.append(
            {"code": kwargs["code"], "category": kwargs["category"]}
        )

    monkeypatch.setattr(stock_service, "save_a_stock_pools", fake_save_a_stock_pools)

    result = stock_service.add_to_stock_pools_by_code("000001", days=20)

    assert result is True
    assert captured["kwargs"]["code"] == "000001"
    assert captured["kwargs"]["category"] == "CLXS_10008"
    assert captured["kwargs"]["sources"] == ["daily-screening", "shouban30"]
    assert captured["kwargs"]["categories"] == ["CLXS_10008", "plate:11"]
    assert {
        (item["source"], item["category"]) for item in captured["kwargs"]["memberships"]
    } == {
        ("daily-screening", "CLXS_10008"),
        ("shouban30", "plate:11"),
    }


def test_add_to_stock_pools_by_code_without_pre_pool_still_fails_by_default(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection([]),
        stock_pools=FakeCollection([]),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    captured = {}

    def save_stub(**kwargs):
        captured.setdefault("kwargs", kwargs)
        fake_db["stock_pools"].docs.append(
            {"code": kwargs["code"], "category": kwargs["category"]}
        )

    monkeypatch.setattr(stock_service, "save_a_stock_pools", save_stub)

    result = stock_service.add_to_stock_pools_by_code("000001", days=20)

    assert result is False
    assert captured == {}


def test_add_to_stock_pools_by_code_allow_direct_writes_clx_monitor_provenance(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection([]),
        stock_pools=FakeCollection([]),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    captured = {}

    def save_stub(**kwargs):
        captured.setdefault("kwargs", kwargs)
        fake_db["stock_pools"].docs.append(
            {"code": kwargs["code"], "category": kwargs["category"]}
        )

    monkeypatch.setattr(stock_service, "save_a_stock_pools", save_stub)

    result = stock_service.add_to_stock_pools_by_code(
        "000001",
        days=20,
        allow_direct=True,
        category="CLX15分钟监控",
        source="clx_signal_workbench",
        remark="clx15_monitor",
    )

    assert result is True
    kwargs = captured["kwargs"]
    assert kwargs["code"] == "000001"
    assert kwargs["category"] == "CLX15分钟监控"
    assert kwargs["stop_loss_price"] is None
    assert kwargs["sources"] == ["clx_signal_workbench"]
    assert kwargs["categories"] == ["CLX15分钟监控"]
    assert kwargs["expire_at"] > kwargs["dt"]
    assert kwargs["remark"] == "clx15_monitor"
    assert fake_db["stock_pools"].last_update == {
        "$set": {"expire_at": kwargs["expire_at"]}
    }
    assert kwargs["memberships"] == [
        {
            "source": "clx_signal_workbench",
            "category": "CLX15分钟监控",
            "added_at": kwargs["dt"],
            "expire_at": kwargs["expire_at"],
            "extra": {
                "entrypoint": "clx_signal_workbench",
                "remark": "clx15_monitor",
            },
        }
    ]


def test_add_to_stock_pools_by_code_allow_direct_reports_missing_write(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection([]),
        stock_pools=FakeCollection([]),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "save_a_stock_pools", lambda **kwargs: None)

    result = stock_service.add_to_stock_pools_by_code(
        "000001",
        days=20,
        allow_direct=True,
        category="CLX15分钟监控",
        source="clx_signal_workbench",
    )

    assert result is False
    assert "expire_at" in fake_db["stock_pools"].last_update["$set"]


def test_add_to_stock_pools_by_code_allow_direct_refreshes_existing_expire_at(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    expired_at = datetime(2024, 1, 1)
    fake_db = FakeDB(
        stock_pre_pools=FakeCollection([]),
        stock_pools=FakeCollection(
            [{"code": "000001", "category": "CLX15分钟监控", "expire_at": expired_at}]
        ),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    captured = {}
    monkeypatch.setattr(
        stock_service,
        "save_a_stock_pools",
        lambda **kwargs: captured.setdefault("kwargs", kwargs),
    )

    result = stock_service.add_to_stock_pools_by_code(
        "000001",
        days=20,
        allow_direct=True,
        category="CLX15分钟监控",
        source="clx_signal_workbench",
    )

    assert result is True
    new_expire_at = captured["kwargs"]["expire_at"]
    assert new_expire_at > captured["kwargs"]["dt"]
    assert fake_db["stock_pools"].docs[0]["expire_at"] == new_expire_at


def test_add_to_must_pool_merges_stock_pool_provenance(monkeypatch):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        must_pool=FakeCollection([]),
        stock_pools=FakeCollection(
            [
                {
                    "code": "000001",
                    "name": "alpha",
                    "category": "CLXS_10008",
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
                    "extra": {"shouban30_order": 7},
                }
            ]
        ),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    captured = {}
    monkeypatch.setattr(
        stock_service.must_pool,
        "build_stock_pool_provenance",
        lambda record: {
            "sources": list(record.get("sources") or []),
            "categories": list(record.get("categories") or []),
            "memberships": list(record.get("memberships") or []),
            "workspace_order_hint": record.get("extra", {}).get("shouban30_order"),
        },
        raising=False,
    )
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda *args, **kwargs: captured.setdefault(
            "call", {"args": args, "kwargs": kwargs}
        ),
    )

    result = stock_service.add_to_must_pool("000001", 9.2, 80000, 50000)

    assert result is True
    assert captured["call"]["args"] == ()
    assert captured["call"]["kwargs"]["code"] == "000001"
    assert captured["call"]["kwargs"]["category"] == "CLXS_10008"
    assert captured["call"]["kwargs"]["provenance"] == {
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
        "workspace_order_hint": 7,
    }


def test_get_stock_signal_list_for_must_pool_buys_filters_current_non_holding_must_pool(
    monkeypatch,
):
    stock_service = _import_stock_service_with_stubs(monkeypatch)

    fake_db = FakeDB(
        stock_signals=FakeCollection(
            [
                # 命中：5m + must_pool_5m_new_open tag + enabled 池代码 + 非持仓 BUY_LONG
                {
                    "_id": "1",
                    "symbol": "sz000001",
                    "code": "000001",
                    "name": "alpha",
                    "period": "5m",
                    "tags": ["must_pool_5m_new_open"],
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 31),
                    "price": 10.2,
                    "stop_lose_price": 9.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
                # 5m 无 tag：非监控产出，排除
                {
                    "_id": "2",
                    "symbol": "sz000002",
                    "code": "000002",
                    "name": "beta",
                    "period": "5m",
                    "tags": [],
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 32),
                    "price": 11.2,
                    "stop_lose_price": 10.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
                # 1m 带 tag：周期不符，排除
                {
                    "_id": "3",
                    "symbol": "sz000003",
                    "code": "000003",
                    "name": "gamma",
                    "period": "1m",
                    "tags": ["must_pool_5m_new_open"],
                    "remark": "回拉中枢上涨",
                    "fire_time": datetime(2026, 3, 15, 9, 33),
                    "price": 12.2,
                    "stop_lose_price": 11.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
                # 5m 带 tag 但代码不在 enabled 池（fund_cn / disabled）：排除
                {
                    "_id": "4",
                    "symbol": "sz000004",
                    "code": "000004",
                    "name": "delta",
                    "period": "5m",
                    "tags": ["must_pool_5m_new_open"],
                    "remark": "回拉中枢下跌",
                    "fire_time": datetime(2026, 3, 15, 9, 34),
                    "price": 13.2,
                    "stop_lose_price": 13.7,
                    "position": "BUY_LONG",
                    "is_holding": False,
                },
            ]
        ),
        must_pool=FakeCollection(
            [
                {"code": "000001", "instrument_type": "stock_cn"},
                {"code": "000002", "instrument_type": "stock_cn"},
                {"code": "000003", "instrument_type": "stock_cn"},
                {"code": "000004", "instrument_type": "fund_cn"},
                {"code": "000005", "instrument_type": "stock_cn", "disabled": True},
            ]
        ),
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    # 与 freshquant/pool/general.py::queryMustPoolCodes 同口径的假实现：
    # enabled + instrument_type ∈ {stock_cn, etf_cn}，禁用/基金代码被排除。
    def fake_query_must_pool_codes():
        return sorted(
            str(doc.get("code"))
            for doc in fake_db["must_pool"].docs
            if doc.get("code")
            and doc.get("instrument_type") in ("stock_cn", "etf_cn")
            and not doc.get("disabled")
        )

    monkeypatch.setattr(stock_service, "queryMustPoolCodes", fake_query_must_pool_codes)

    result = stock_service.get_stock_signal_list(
        page=1, size=1000, category="must_pool_buys"
    )

    assert [row["code"] for row in result] == ["000001"]
    assert fake_db["stock_signals"].last_query == {
        "is_holding": False,
        "position": "BUY_LONG",
        "period": "5m",
        "tags": "must_pool_5m_new_open",
        "code": {"$in": ["000001", "000002", "000003"]},
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
