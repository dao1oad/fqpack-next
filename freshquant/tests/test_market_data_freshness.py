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
    def __init__(
        self,
        latest_by_code: dict[str, str],
        day_docs: int,
        documents: list[dict] | None = None,
    ):
        self.latest_by_code = latest_by_code
        self.day_docs = day_docs
        self.documents = documents or []
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

    def find(self, query, projection=None):
        allowed_codes = set(query.get("code", {}).get("$in", []))
        return [
            doc
            for doc in self.documents
            if doc.get("date") == query.get("date")
            and (not allowed_codes or doc.get("code") in allowed_codes)
        ]


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


class FakeEtfMinCollection:
    def __init__(self, counts_by_code: dict[str, dict[str, int]]):
        self.counts_by_code = counts_by_code
        self.seen_queries: list[dict] = []

    def find(self, query, projection=None):
        self.seen_queries.append(dict(query))
        code_counts = self.counts_by_code.get(query.get("code"), {})
        return [
            {"type": frequence}
            for frequence, count in code_counts.items()
            for _ in range(count)
        ]


class FakeEtfListCollection:
    def __init__(self, codes: list[str]):
        self.codes = codes

    def find(self, query, projection=None):
        return [{"code": code} for code in self.codes]


def _etf_day_document(code: str, *, placeholder: bool = False) -> dict:
    if placeholder:
        return {
            "code": code,
            "date": "2026-07-20",
            "open": 1.0,
            "close": 1.0,
            "high": 1.0,
            "low": 1.0,
            "vol": 5.877471754e-39,
            "amount": 5.877471754e-39,
        }
    return {
        "code": code,
        "date": "2026-07-20",
        "open": 4.1,
        "close": 4.2,
        "high": 4.3,
        "low": 4.0,
        "vol": 1000,
        "amount": 4200,
    }


def _complete_etf_min_counts() -> dict[str, int]:
    return {"1min": 240, "5min": 48, "15min": 16, "30min": 8, "60min": 4}


class FakeIntegrityCollection:
    def __init__(self, *, distinct_values=None, aggregate_rows=None):
        self.distinct_values = distinct_values or {}
        self.aggregate_rows = list(aggregate_rows or [])
        self.aggregate_pipelines = []

    def distinct(self, field, query=None):
        key = (field, str((query or {}).get("date") or ""))
        return list(self.distinct_values.get(key, self.distinct_values.get(field, [])))

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_pipelines.append((pipeline, kwargs))
        selected_codes = set(pipeline[0]["$match"]["code"]["$in"])
        return [
            row
            for row in self.aggregate_rows
            if str(row["_id"]["code"]) in selected_codes
        ]


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


def test_etf_day_fresh_passes():
    module = _load_module()
    collection = FakeDayCollection(
        {},
        day_docs=2,
        documents=[_etf_day_document("510300"), _etf_day_document("159915")],
    )
    etf_list_collection = FakeEtfListCollection(["510300", "159915"])
    result = module.assert_etf_day_fresh(
        collection,
        etf_list_collection,
        expected_trade_date="2026-07-20",
        min_docs=2,
        min_universe_codes=2,
    )
    assert result == {
        "expected_trade_date": "2026-07-20",
        "universe_codes": 2,
        "day_docs": 2,
    }
    assert collection.created_indexes == ["date"]


def test_etf_day_low_doc_count_raises():
    module = _load_module()
    collection = FakeDayCollection(
        {},
        day_docs=2,
        documents=[_etf_day_document("510300"), _etf_day_document("000300")],
    )
    etf_list_collection = FakeEtfListCollection(["510300", "159915"])
    with pytest.raises(RuntimeError, match="only 1 unique ETF docs"):
        module.assert_etf_day_fresh(
            collection,
            etf_list_collection,
            expected_trade_date="2026-07-20",
            min_docs=2,
            min_universe_codes=2,
        )


def test_etf_day_low_universe_count_raises():
    module = _load_module()
    collection = FakeDayCollection(
        {}, day_docs=1, documents=[_etf_day_document("510300")]
    )
    with pytest.raises(RuntimeError, match="etf_list incomplete"):
        module.assert_etf_day_fresh(
            collection,
            FakeEtfListCollection(["510300"]),
            expected_trade_date="2026-07-20",
            min_docs=1,
            min_universe_codes=2,
        )


def test_etf_min_fresh_checks_all_frequencies_and_skips_placeholder():
    module = _load_module()
    day_collection = FakeDayCollection(
        {},
        day_docs=2,
        documents=[
            _etf_day_document("510300"),
            _etf_day_document("159079", placeholder=True),
            _etf_day_document("000300"),
        ],
    )
    min_collection = FakeEtfMinCollection({"510300": _complete_etf_min_counts()})
    etf_list_collection = FakeEtfListCollection(["510300", "159079"])

    result = module.assert_etf_min_fresh(
        day_collection,
        min_collection,
        etf_list_collection,
        expected_trade_date="2026-07-20",
        min_day_docs=2,
        min_real_codes=1,
        min_universe_codes=2,
    )

    assert result["universe_codes"] == 2
    assert result["day_docs"] == 2
    assert result["real_codes"] == 1
    assert result["placeholder_codes"] == 1
    assert result["checked_groups"] == 5
    assert [query["code"] for query in min_collection.seen_queries] == ["510300"]
    assert min_collection.seen_queries[0]["type"]["$in"] == [
        "1min",
        "5min",
        "15min",
        "30min",
        "60min",
    ]


def test_etf_min_missing_frequency_raises():
    module = _load_module()
    day_collection = FakeDayCollection(
        {}, day_docs=1, documents=[_etf_day_document("510300")]
    )
    counts = _complete_etf_min_counts()
    counts.pop("15min")
    min_collection = FakeEtfMinCollection({"510300": counts})

    with pytest.raises(RuntimeError, match="missing_groups=1"):
        module.assert_etf_min_fresh(
            day_collection,
            min_collection,
            FakeEtfListCollection(["510300"]),
            expected_trade_date="2026-07-20",
            min_day_docs=1,
            min_real_codes=1,
            min_universe_codes=1,
        )


def test_etf_min_invalid_bar_count_raises():
    module = _load_module()
    day_collection = FakeDayCollection(
        {}, day_docs=1, documents=[_etf_day_document("510300")]
    )
    counts = _complete_etf_min_counts()
    counts["1min"] = 12
    min_collection = FakeEtfMinCollection({"510300": counts})

    with pytest.raises(RuntimeError, match="invalid_bar_counts=1"):
        module.assert_etf_min_fresh(
            day_collection,
            min_collection,
            FakeEtfListCollection(["510300"]),
            expected_trade_date="2026-07-20",
            min_day_docs=1,
            min_real_codes=1,
            min_universe_codes=1,
        )


def test_stock_market_data_consistency_passes_for_all_frequencies():
    module = _load_module()
    dates = ["2026-07-17", "2026-07-20"]
    codes = ["000001", "600000"]
    day = FakeIntegrityCollection(
        distinct_values={
            "date": dates,
            ("code", "2026-07-17"): codes,
            ("code", "2026-07-20"): codes,
        }
    )
    stock_list = FakeIntegrityCollection(distinct_values={"code": codes})
    rows = []
    for date in dates:
        for code in codes:
            for frequence in module.STOCK_MIN_FREQUENCIES:
                rows.append({"_id": {"date": date, "code": code, "type": frequence}})
    minute = FakeIntegrityCollection(aggregate_rows=rows)

    result = module.assert_stock_market_data_consistent(
        day_collection=day,
        min_collection=minute,
        stock_list_collection=stock_list,
        expected_trade_date="2026-07-20",
        trade_dates_provider=lambda: dates,
    )

    assert result["audited_dates"] == dates
    assert result["day_codes"] == {"2026-07-17": 2, "2026-07-20": 2}
    assert minute.aggregate_pipelines


def test_stock_market_data_consistency_rejects_day_and_minute_holes():
    module = _load_module()
    date = "2026-07-20"
    day = FakeIntegrityCollection(
        distinct_values={"date": [date], ("code", date): ["000001", "600000"]}
    )
    stock_list = FakeIntegrityCollection(
        distinct_values={"code": ["000001", "600000", "600519"]}
    )
    rows = []
    for frequence in module.STOCK_MIN_FREQUENCIES:
        rows.append({"_id": {"date": date, "code": "000001", "type": frequence}})
        rows.append({"_id": {"date": date, "code": "600519", "type": frequence}})
    rows.append({"_id": {"date": date, "code": "600000", "type": "1min"}})
    minute = FakeIntegrityCollection(aggregate_rows=rows)

    with pytest.raises(RuntimeError, match="missing_day=1.*missing_min"):
        module.assert_stock_market_data_consistent(
            day_collection=day,
            min_collection=minute,
            stock_list_collection=stock_list,
            expected_trade_date=date,
            trade_dates_provider=lambda: [date],
        )


def test_stock_market_data_consistency_rejects_fully_missing_trade_date():
    module = _load_module()
    dates = ["2026-07-17", "2026-07-20"]
    codes = ["000001", "600000"]
    day = FakeIntegrityCollection(distinct_values={("code", "2026-07-20"): codes})
    stock_list = FakeIntegrityCollection(distinct_values={"code": codes})
    rows = [
        {"_id": {"date": "2026-07-20", "code": code, "type": frequence}}
        for code in codes
        for frequence in module.STOCK_MIN_FREQUENCIES
    ]
    minute = FakeIntegrityCollection(aggregate_rows=rows)

    with pytest.raises(RuntimeError, match="missing_market_days=1"):
        module.assert_stock_market_data_consistent(
            day_collection=day,
            min_collection=minute,
            stock_list_collection=stock_list,
            expected_trade_date="2026-07-20",
            trade_dates_provider=lambda: dates,
        )
