from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

import freshquant.chanlun_structure_service as structure_service
import freshquant.data.index as index_data
import freshquant.market_data.xtdata.strategy_consumer as strategy_consumer
from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.instrument.general import infer_cn_instrument_type
from freshquant.quote import index as index_quote


class _EmptyCursor:
    def sort(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(())


class _EmptyCollection:
    def find(self, *_args, **_kwargs):
        return _EmptyCursor()


class _EmptyDatabase:
    def __getitem__(self, _name):
        return _EmptyCollection()


class _CaptureCollection(_EmptyCollection):
    def __init__(self):
        self.query = None

    def find(self, query, *_args, **_kwargs):
        self.query = query
        return _EmptyCursor()


class _CaptureDatabase:
    def __init__(self):
        self.collection = _CaptureCollection()

    def __getitem__(self, name):
        assert name == "index_realtime"
        return self.collection


def _bars() -> pd.DataFrame:
    now = pd.Timestamp("2026-07-22 09:35", tz="Asia/Shanghai")
    return pd.DataFrame(
        {
            "datetime": [
                now.to_pydatetime(),
                (now + timedelta(minutes=5)).to_pydatetime(),
            ],
            "open": [10.0, 10.2],
            "high": [10.3, 10.4],
            "low": [9.9, 10.1],
            "close": [10.1, 10.3],
            "volume": [100.0, 120.0],
            "amount": [1000.0, 1236.0],
        }
    )


@pytest.mark.parametrize(
    "code,expected",
    [
        ("sz000001", InstrumentType.STOCK_CN),
        ("600000.SH", InstrumentType.STOCK_CN),
        ("sh520000", InstrumentType.ETF_CN),
        ("530001.SH", InstrumentType.ETF_CN),
        ("sh000300", InstrumentType.INDEX_CN),
        ("000300.SH", InstrumentType.INDEX_CN),
        ("sz399001", InstrumentType.INDEX_CN),
        ("399001.SZ", InstrumentType.INDEX_CN),
        ("920001.BJ", InstrumentType.STOCK_CN),
    ],
)
def test_shared_cn_security_classification_boundaries(code, expected):
    assert infer_cn_instrument_type(code) == expected


def test_index_minute_fetch_does_not_call_to_qfq(monkeypatch):
    class _IndexData:
        data = _bars()

        def to_qfq(self):
            raise AssertionError("real Index must stay BFQ")

    monkeypatch.setattr(
        index_data,
        "QA_fetch_index_min_adv",
        lambda *_args, **_kwargs: _IndexData(),
    )

    result = index_data.fq_data_QA_fetch_index_min_adv(
        "000300", "2026-01-01", "2026-01-02", "5min"
    )

    assert result["close"].tolist() == [10.1, 10.3]


def test_index_quote_fetcher_preserves_bfq_values(monkeypatch):
    source = _bars().copy()
    source.index = source["datetime"]
    monkeypatch.setattr(
        index_quote, "fq_data_index_fetch_min", lambda *args, **kwargs: source
    )

    result = index_quote.queryIndexCandleSticks("sh000300", "5m")

    assert result["close"].tolist() == [10.1, 10.3]
    assert result["open"].tolist() == [10.0, 10.2]


def test_index_realtime_query_uses_index_market_for_conflicting_code(monkeypatch):
    source = _bars().copy()
    capture_db = _CaptureDatabase()
    monkeypatch.setattr(
        index_data,
        "fq_data_QA_fetch_index_min_adv",
        lambda *_args, **_kwargs: source,
    )
    monkeypatch.setattr(index_data, "DBfreshquant", capture_db)
    monkeypatch.setattr(
        index_data,
        "query_index_map",
        lambda: {"000001": {"sse": "SH"}},
    )

    result = index_data.fq_data_index_fetch_min(
        "000001",
        "5min",
        pd.Timestamp("2026-07-22 09:30"),
        pd.Timestamp("2026-07-22 15:00"),
    )

    assert result is not None
    assert capture_db.collection.query["code"] == "sh000001"


def test_index_weekly_resample_exposes_datetime_not_multiindex_tuple(monkeypatch):
    dates = pd.to_datetime(["2026-07-17", "2026-07-24"])
    weekly = pd.DataFrame(
        {
            "open": [10.0, 10.2],
            "high": [10.3, 10.4],
            "low": [9.9, 10.1],
            "close": [10.1, 10.3],
            "volume": [100.0, 120.0],
            "amount": [1000.0, 1236.0],
        },
        index=pd.MultiIndex.from_arrays(
            [dates, ["000001", "000001"]], names=["date", "code"]
        ),
    )
    monkeypatch.setattr(
        index_quote,
        "fq_data_index_fetch_day",
        lambda *_args, **_kwargs: _bars(),
    )
    monkeypatch.setattr(
        index_quote, "QA_data_day_resample", lambda *_args, **_kwargs: weekly
    )

    result = index_quote.queryIndexCandleSticks("sh000001", "1w")

    assert result["datetime"].tolist() == list(dates)
    assert all(hasattr(value, "strftime") for value in result["datetime"])


def test_strategy_consumer_index_read_never_reads_factor(monkeypatch):
    consumer = object.__new__(strategy_consumer.StrategyConsumer)
    consumer.max_bars = 32
    consumer._is_index_like = lambda _code: True
    consumer._is_real_index = lambda _code: True
    monkeypatch.setattr(
        strategy_consumer,
        "_load_minute_history_from_quantaxis_db",
        lambda **_kwargs: _bars(),
    )
    monkeypatch.setattr(strategy_consumer, "DBfreshquant", _EmptyDatabase())
    monkeypatch.setattr(
        strategy_consumer,
        "fetch_qfq_adj_df",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("Index must not read adj")
        ),
    )

    result = consumer._load_window_from_db(code="sh000300", period_backend="5min")

    assert result["open"].tolist() == [10.0, 10.2]
    assert result["close"].tolist() == [10.1, 10.3]


def test_chanlun_structure_routes_index_to_bfq_fetcher(monkeypatch):
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_type",
        infer_cn_instrument_type,
    )
    monkeypatch.setattr(
        index_quote,
        "queryIndexCandleSticks",
        lambda *_args, **_kwargs: _bars(),
    )

    result = structure_service._fetch_kline_df("sh000300", "5m", None)

    assert result["close"].tolist() == [10.1, 10.3]
