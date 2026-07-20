"""fqdagster 行情数据新鲜度校验的单元测试。

直接从源码文件加载 ``market_data_freshness`` 模块, 避免 import
``fqdagster.defs.assets`` 包时拖入 QUANTAXIS / dagster 等重依赖。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "morningglory"
    / "fqdagster"
    / "src"
    / "fqdagster"
    / "defs"
    / "assets"
    / "market_data_freshness.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "market_data_freshness_under_test", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDayCollection:
    def __init__(self, latest_by_code: dict[str, str], day_docs: int):
        self.latest_by_code = latest_by_code
        self.day_docs = day_docs
        self.created_indexes: list = []

    def find_one(self, query, sort=None):
        code = query.get("code")
        latest = self.latest_by_code.get(code)
        if latest is None:
            return None
        return {"code": code, "date": latest}

    def create_index(self, keys, **kwargs):
        self.created_indexes.append(keys)
        return keys

    def count_documents(self, query):
        return self.day_docs


class FakeMinCollection:
    def __init__(self, latest_by_code: dict[str, str]):
        self.latest_by_code = latest_by_code
        self.seen_queries: list[dict] = []

    def find_one(self, query, sort=None):
        self.seen_queries.append(dict(query))
        code = query.get("code")
        latest = self.latest_by_code.get(code)
        if latest is None:
            return None
        return {"code": code, "type": query.get("type"), "datetime": latest}


def test_stock_day_fresh_passes():
    module = _load_module()
    collection = FakeDayCollection(
        {"000001": "2026-07-20", "600000": "2026-07-20", "600519": "2026-07-20"},
        day_docs=5187,
    )
    result = module.assert_stock_day_fresh(collection, expected_trade_date="2026-07-20")
    assert result["expected_trade_date"] == "2026-07-20"
    assert result["day_docs"] == 5187


def test_stock_day_all_samples_stale_raises():
    module = _load_module()
    collection = FakeDayCollection(
        {"000001": "2026-07-07", "600000": "2026-07-07", "600519": "2026-07-07"},
        day_docs=0,
    )
    with pytest.raises(RuntimeError, match="stock_day is stale"):
        module.assert_stock_day_fresh(collection, expected_trade_date="2026-07-20")


def test_stock_day_single_stale_sample_allows_suspension():
    module = _load_module()
    collection = FakeDayCollection(
        {"000001": "2026-07-20", "600000": "2026-07-10", "600519": "2026-07-20"},
        day_docs=5100,
    )
    result = module.assert_stock_day_fresh(collection, expected_trade_date="2026-07-20")
    assert result["sample_latest"]["600000"] == "2026-07-10"


def test_stock_day_low_doc_count_raises():
    module = _load_module()
    collection = FakeDayCollection(
        {"000001": "2026-07-20", "600000": "2026-07-20", "600519": "2026-07-20"},
        day_docs=120,
    )
    with pytest.raises(RuntimeError, match="stock_day incomplete"):
        module.assert_stock_day_fresh(collection, expected_trade_date="2026-07-20")


def test_stock_day_missing_sample_docs_counts_as_stale():
    module = _load_module()
    collection = FakeDayCollection({}, day_docs=0)
    with pytest.raises(RuntimeError, match="stock_day is stale"):
        module.assert_stock_day_fresh(collection, expected_trade_date="2026-07-20")


def test_stock_min_fresh_passes_and_filters_by_frequence():
    module = _load_module()
    collection = FakeMinCollection(
        {
            "000001": "2026-07-20 15:00:00",
            "600000": "2026-07-20 15:00:00",
            "600519": "2026-07-20 15:00:00",
        }
    )
    result = module.assert_stock_min_fresh(collection, expected_trade_date="2026-07-20")
    assert result["expected_trade_date"] == "2026-07-20"
    assert all(query.get("type") == "1min" for query in collection.seen_queries)


def test_stock_min_all_samples_stale_raises():
    module = _load_module()
    collection = FakeMinCollection(
        {
            "000001": "2026-07-07 15:00:00",
            "600000": "2026-07-07 15:00:00",
            "600519": "2026-07-07 15:00:00",
        }
    )
    with pytest.raises(RuntimeError, match="stock_min\\(1min\\) is stale"):
        module.assert_stock_min_fresh(collection, expected_trade_date="2026-07-20")
