from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

from freshquant.clx_daily_selection.market_data import MongoDailyMarketDataProvider


class FakeQFQDataNotReadyError(RuntimeError):
    error_code = "QFQ_DATA_NOT_READY"

    def __init__(self, message, *, scope=None, code=None, missing_dates=None):
        self.scope = str(scope or "")
        self.code = str(code or "")
        self.missing_dates = tuple(missing_dates or ())
        super().__init__(f"QFQ_DATA_NOT_READY: {message}")


def install_qfq_reader(monkeypatch, apply_qfq_to_bars):
    module = ModuleType("freshquant.data.qfq_reader")
    module.QFQDataNotReadyError = FakeQFQDataNotReadyError
    module.apply_qfq_to_bars = apply_qfq_to_bars
    monkeypatch.setitem(sys.modules, module.__name__, module)


def qfq_metadata(**overrides):
    values = {
        "scope": "stock",
        "active_slot": "a",
        "collection": "stock_adj_qfq_a",
        "snapshot_id": "stock-snapshot-20260731",
        "factor_asof": "2026-07-31",
        "published_at": "2026-08-02T12:00:00Z",
        "effective_version": "stock-snapshot-20260731",
        "override_version": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


class TrackingDatabase(dict):
    def __init__(self, values):
        super().__init__(values)
        self.requested_collections = []

    def __getitem__(self, key):
        self.requested_collections.append(key)
        return super().__getitem__(key)


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


def test_daily_bars_use_strict_reader_on_bfq_and_keep_snapshot_facts(monkeypatch):
    captured = {}

    def apply_qfq_to_bars(bars, **kwargs):
        captured["bars"] = bars.copy()
        captured["kwargs"] = kwargs
        adjusted = bars.copy()
        adjusted[["open", "high", "low", "close"]] = adjusted[
            ["open", "high", "low", "close"]
        ].astype(float)
        adjusted.loc[0, ["open", "high", "low", "close"]] *= 0.5
        return adjusted, qfq_metadata()

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    database = TrackingDatabase(
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
        }
    )
    expected_pair = {
        "stock": {
            "snapshot_id": "stock-snapshot-20260731",
            "factor_asof": "2026-07-31",
            "active_slot": "a",
            "collection": "stock_adj_qfq_a",
            "published_at": "2026-08-02T12:00:00Z",
            "effective_version": "stock-snapshot-20260731",
            "override_version": None,
        },
        "etf": {
            "snapshot_id": "etf-snapshot-20260731",
            "factor_asof": "2026-07-31",
            "active_slot": "b",
            "published_at": "2026-08-02T12:00:00Z",
        },
    }
    provider = MongoDailyMarketDataProvider(
        database, expected_snapshot_metadata=expected_pair
    )

    bars = provider.get_daily_bars("stock", "000001", "2026-07-31", 1200)

    assert [bar["close"] for bar in bars] == [5.5, 21.0]
    assert [bar["adjustment_factor"] for bar in bars] == [0.5, 1.0]
    assert {bar["data_version"] for bar in bars} == {"qfq-daily-v1"}
    assert {bar["qfq_active_slot"] for bar in bars} == {"a"}
    assert {bar["qfq_snapshot_id"] for bar in bars} == {"stock-snapshot-20260731"}
    assert {bar["qfq_factor_asof"] for bar in bars} == {"2026-07-31"}
    assert {bar["qfq_published_at"] for bar in bars} == {"2026-08-02T12:00:00Z"}
    assert {bar["qfq_effective_version"] for bar in bars} == {"stock-snapshot-20260731"}
    assert {bar["qfq_collection"] for bar in bars} == {"stock_adj_qfq_a"}
    assert provider.data_version == "qfq-daily-v1"
    assert provider.last_read_metadata("stock") == {
        "scope": "stock",
        "active_slot": "a",
        "collection": "stock_adj_qfq_a",
        "snapshot_id": "stock-snapshot-20260731",
        "factor_asof": "2026-07-31",
        "published_at": "2026-08-02T12:00:00Z",
        "effective_version": "stock-snapshot-20260731",
        "override_version": None,
    }
    assert database.requested_collections == ["stock_day"]
    assert captured["bars"]["close"].tolist() == [11, 21]
    assert captured["kwargs"] == {
        "scope": "stock",
        "code": "000001",
        "db": database,
        "date_col": "date",
        "ohlc_cols": ("open", "high", "low", "close"),
    }


def test_daily_bars_propagate_strict_reader_not_ready(monkeypatch):
    def apply_qfq_to_bars(_bars, **_kwargs):
        raise FakeQFQDataNotReadyError(
            "active snapshot does not cover requested bars",
            scope="stock",
            code="000001",
            missing_dates=["2026-03-18"],
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
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
        }
    )

    with pytest.raises(FakeQFQDataNotReadyError, match="QFQ_DATA_NOT_READY"):
        provider.get_daily_bars("stock", "000001", "2026-03-19", 1200)


def test_etf_daily_bars_accept_per_call_frozen_metadata(monkeypatch):
    captured = {}

    def apply_qfq_to_bars(bars, **kwargs):
        captured.update(kwargs)
        return bars.copy(), qfq_metadata(
            scope="etf",
            active_slot="b",
            collection="etf_adj_qfq_b",
            snapshot_id="etf-snapshot-20260731",
            published_at="2026-08-02T12:01:00Z",
            effective_version="etf-snapshot-20260731",
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    database = TrackingDatabase(
        {
            "index_day": DailyBarsCollection(
                [
                    {
                        "code": "510300",
                        "date": "2026-07-31",
                        "open": 4.0,
                        "high": 4.1,
                        "low": 3.9,
                        "close": 4.05,
                    }
                ]
            )
        }
    )
    provider = MongoDailyMarketDataProvider(database)

    bars = provider.get_daily_bars(
        "etf",
        "510300",
        "2026-07-31",
        1200,
        expected_snapshot_metadata={
            "snapshot_id": "etf-snapshot-20260731",
            "factor_asof": "2026-07-31",
            "active_slot": "b",
            "collection": "etf_adj_qfq_b",
            "published_at": "2026-08-02T12:01:00Z",
        },
    )

    assert bars[0]["qfq_snapshot_id"] == "etf-snapshot-20260731"
    assert captured["scope"] == "etf"
    assert captured["code"] == "510300"
    assert database.requested_collections == ["index_day"]


def test_daily_bars_fail_closed_when_frozen_snapshot_drifts(monkeypatch):
    def apply_qfq_to_bars(bars, **_kwargs):
        return pd.DataFrame(bars), qfq_metadata(snapshot_id="new-snapshot")

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    provider = MongoDailyMarketDataProvider(
        {
            "stock_day": DailyBarsCollection(
                [
                    {
                        "code": "000001",
                        "date": "2026-07-31",
                        "open": 20,
                        "high": 22,
                        "low": 19,
                        "close": 21,
                    }
                ]
            )
        },
        expected_snapshot_metadata={
            "stock": {
                "snapshot_id": "frozen-snapshot",
                "factor_asof": "2026-07-31",
            }
        },
    )

    with pytest.raises(
        FakeQFQDataNotReadyError, match="frozen QFQ snapshot metadata mismatch"
    ):
        provider.get_daily_bars("stock", "000001", "2026-07-31", 1200)
    assert provider.last_read_metadata("stock") is None


def test_daily_bars_reject_override_for_snapshot_covered_target(monkeypatch):
    def apply_qfq_to_bars(bars, **_kwargs):
        return pd.DataFrame(bars), qfq_metadata(
            effective_version="stock-snapshot-20260731:override-v1",
            override_version="override-v1",
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    provider = MongoDailyMarketDataProvider(
        {
            "stock_day": DailyBarsCollection(
                [
                    {
                        "code": "000001",
                        "date": "2026-07-31",
                        "open": 20,
                        "high": 22,
                        "low": 19,
                        "close": 21,
                    }
                ]
            )
        }
    )

    with pytest.raises(
        FakeQFQDataNotReadyError,
        match="override for a snapshot-covered date",
    ):
        provider.get_daily_bars("stock", "000001", "2026-07-31", 1200)


@pytest.mark.parametrize(
    ("asset_type", "symbol", "collection_name"),
    [("stock", "301717", "stock_day"), ("etf", "158000", "index_day")],
)
def test_target_day_qfq_probe_propagates_missing_factor_as_not_ready(
    monkeypatch, asset_type, symbol, collection_name
):
    def apply_qfq_to_bars(_bars, **_kwargs):
        raise FakeQFQDataNotReadyError(
            "active QFQ snapshot does not cover requested bars",
            scope=asset_type,
            code=symbol,
            missing_dates=["2026-07-31"],
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    provider = MongoDailyMarketDataProvider(
        {
            collection_name: DailyBarsCollection(
                [
                    {
                        "code": symbol,
                        "date": "2026-07-31",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                    }
                ]
            )
        }
    )

    with pytest.raises(FakeQFQDataNotReadyError, match="QFQ_DATA_NOT_READY"):
        provider.probe_qfq_instrument(
            asset_type,
            symbol,
            "2026-07-31",
            expected_snapshot_metadata={
                "scope": asset_type,
                "active_slot": "a" if asset_type == "stock" else "b",
                "collection": f"{asset_type}_adj_qfq_{'a' if asset_type == 'stock' else 'b'}",
                "snapshot_id": f"{asset_type}-snapshot-20260731",
                "factor_asof": "2026-07-31",
                "published_at": "2026-08-02T12:00:00Z",
                "effective_version": f"{asset_type}-snapshot-20260731",
            },
        )


def test_full_window_qfq_probe_isolates_an_actual_bfq_date_without_factor(
    monkeypatch,
):
    captured = {}

    def apply_qfq_to_bars(bars, **_kwargs):
        captured["dates"] = bars["date"].tolist()
        raise FakeQFQDataNotReadyError(
            "active QFQ snapshot does not cover requested bars",
            scope="stock",
            code="000001",
            missing_dates=["2026-07-30"],
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    provider = MongoDailyMarketDataProvider(
        {
            "stock_day": DailyBarsCollection(
                [
                    {
                        "code": "000001",
                        "date": "2026-07-30",
                        "open": 9,
                        "high": 10,
                        "low": 8,
                        "close": 9.5,
                    },
                    {
                        "code": "000001",
                        "date": "2026-07-31",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                    },
                ]
            )
        }
    )

    with pytest.raises(FakeQFQDataNotReadyError) as error:
        provider.probe_qfq_instrument("stock", "000001", "2026-07-31", bar_count=1200)

    assert captured["dates"] == ["2026-07-30", "2026-07-31"]
    assert error.value.missing_dates == ("2026-07-30",)


@pytest.mark.parametrize(
    ("asset_type", "symbol", "collection_name", "slot"),
    [
        ("stock", "000001", "stock_day", "a"),
        ("etf", "510300", "index_day", "b"),
    ],
)
def test_full_window_qfq_probe_accepts_short_lifecycle_stock_and_etf_codes(
    monkeypatch, asset_type, symbol, collection_name, slot
):
    captured = {}

    def apply_qfq_to_bars(bars, **_kwargs):
        captured["dates"] = bars["date"].tolist()
        return bars.copy(), qfq_metadata(
            scope=asset_type,
            active_slot=slot,
            collection=f"{asset_type}_adj_qfq_{slot}",
            snapshot_id=f"{asset_type}-snapshot-20260731",
            effective_version=f"{asset_type}-snapshot-20260731",
        )

    install_qfq_reader(monkeypatch, apply_qfq_to_bars)
    expected = {
        "scope": asset_type,
        "active_slot": slot,
        "collection": f"{asset_type}_adj_qfq_{slot}",
        "snapshot_id": f"{asset_type}-snapshot-20260731",
        "factor_asof": "2026-07-31",
        "published_at": "2026-08-02T12:00:00Z",
        "effective_version": f"{asset_type}-snapshot-20260731",
    }
    provider = MongoDailyMarketDataProvider(
        {
            collection_name: DailyBarsCollection(
                [
                    {
                        "code": symbol,
                        "date": "2026-07-30",
                        "open": 9,
                        "high": 10,
                        "low": 8,
                        "close": 9.5,
                    },
                    {
                        "code": symbol,
                        "date": "2026-07-31",
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                    },
                ]
            )
        }
    )

    metadata = provider.probe_qfq_instrument(
        asset_type,
        symbol,
        "2026-07-31",
        bar_count=1200,
        expected_snapshot_metadata=expected,
    )

    assert captured["dates"] == ["2026-07-30", "2026-07-31"]
    assert metadata["snapshot_id"] == expected["snapshot_id"]
    assert metadata["active_slot"] == slot


@pytest.mark.parametrize("bar_count", [0, -1])
def test_qfq_probe_requires_a_positive_bar_count(bar_count):
    provider = MongoDailyMarketDataProvider({})

    with pytest.raises(ValueError, match="bar_count must be positive"):
        provider.probe_qfq_instrument(
            "stock", "000001", "2026-07-31", bar_count=bar_count
        )
