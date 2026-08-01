from __future__ import annotations

import pytest

from freshquant.clx_daily_selection.market_data import (
    AdjustmentCoverageError,
    MongoDailyMarketDataProvider,
)


class ListCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, _query, _projection):
        return list(self.rows)


class DayCollection:
    def __init__(self, current_codes):
        self.current_codes = current_codes
        self.query = None

    def distinct(self, field, query):
        self.query = (field, query)
        return list(self.current_codes)


class LatestDayCollection:
    def __init__(self, row):
        self.row = row
        self.query = None

    def find_one(self, query, projection, sort):
        self.query = (query, projection, sort)
        return self.row


class SortableCursor(list):
    def sort(self, key, direction):
        return SortableCursor(
            sorted(self, key=lambda row: row[key], reverse=direction < 0)
        )

    def limit(self, count):
        return SortableCursor(self[:count])


class DailyBarsCollection:
    def __init__(self, rows):
        self.rows = list(rows)

    def find(self, query, _projection):
        return SortableCursor(
            row
            for row in self.rows
            if row["code"] == query["code"] and row["date"] <= query["date"]["$lte"]
        )


def test_stock_universe_only_contains_current_trade_date_non_st_symbols():
    day = DayCollection(["000001", "000002", "600000", "830001"])
    database = {
        "stock_list": ListCollection(
            [
                {"code": "000001", "name": "平安银行"},
                {"code": "000002", "name": "ST示例"},
                {"code": "600000", "name": "浦发银行"},
                {"code": "830001", "name": "北交所示例"},
                {"code": "600001", "name": "停牌旧数据"},
            ]
        ),
        "stock_day": day,
    }

    rows = MongoDailyMarketDataProvider(database).list_instruments(
        "stock", "2026-03-19"
    )

    assert rows == [
        {"symbol": "000001", "name": "平安银行"},
        {"symbol": "600000", "name": "浦发银行"},
    ]
    assert day.query == ("code", {"date": "2026-03-19"})


def test_etf_universe_intersects_etf_list_with_current_index_day():
    database = {
        "etf_list": ListCollection(
            [
                {"code": "510300", "name": "沪深300ETF"},
                {"code": "510500", "name": "中证500ETF"},
            ]
        ),
        "index_day": DayCollection(["000001", "510300"]),
    }

    rows = MongoDailyMarketDataProvider(database).list_instruments("etf", "2026-03-19")

    assert rows == [{"symbol": "510300", "name": "沪深300ETF"}]


def test_latest_trade_date_uses_asset_daily_collection():
    stock_day = LatestDayCollection({"date": "2026-03-19"})
    index_day = LatestDayCollection({"date": "2026-03-18"})
    provider = MongoDailyMarketDataProvider(
        {"stock_day": stock_day, "index_day": index_day}
    )

    assert provider.get_latest_trade_date("stock", "000001") == "2026-03-19"
    assert provider.get_latest_trade_date("etf", "510300") == "2026-03-18"
    assert stock_day.query == (
        {"code": "000001"},
        {"_id": 0, "date": 1},
        [("date", -1)],
    )
    assert index_day.query[0] == {"code": "510300"}


def test_daily_bars_require_complete_qfq_factor_coverage_and_keep_version_facts():
    provider = MongoDailyMarketDataProvider(
        {
            "stock_day": DailyBarsCollection(
                [
                    {
                        "code": "000001",
                        "date": "2026-03-18",
                        "open": 10,
                        "high": 12,
                        "low": 9,
                        "close": 11,
                        "vol": 100,
                    },
                    {
                        "code": "000001",
                        "date": "2026-03-19",
                        "open": 20,
                        "high": 22,
                        "low": 19,
                        "close": 21,
                        "vol": 200,
                    },
                ]
            ),
            "stock_adj": ListCollection(
                [
                    {"date": "2026-03-18", "adj": 0.5},
                    {"date": "2026-03-19", "adj": 1.0},
                ]
            ),
        }
    )

    bars = provider.get_daily_bars("stock", "000001", "2026-03-19", 1200)

    assert [bar["close"] for bar in bars] == [5.5, 21.0]
    assert [bar["adjustment_factor"] for bar in bars] == [0.5, 1.0]
    assert {bar["data_version"] for bar in bars} == {"qfq-daily-v1"}
    assert provider.data_version == "qfq-daily-v1"


def test_daily_bars_fail_closed_on_qfq_factor_gap():
    provider = MongoDailyMarketDataProvider(
        {
            "stock_day": DailyBarsCollection(
                [
                    {
                        "code": "000001",
                        "date": "2026-03-18",
                        "open": 10,
                        "high": 12,
                        "low": 9,
                        "close": 11,
                    },
                    {
                        "code": "000001",
                        "date": "2026-03-19",
                        "open": 20,
                        "high": 22,
                        "low": 19,
                        "close": 21,
                    },
                ]
            ),
            "stock_adj": ListCollection([{"date": "2026-03-19", "adj": 1.0}]),
        }
    )

    with pytest.raises(
        AdjustmentCoverageError,
        match=(
            "qfq-daily-v1 adjustment coverage invalid for stock/000001: "
            "missing_dates=2026-03-18"
        ),
    ):
        provider.get_daily_bars("stock", "000001", "2026-03-19", 1200)
