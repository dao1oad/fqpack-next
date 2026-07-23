from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

import freshquant.chanlun_service as chanlun_service
import freshquant.chanlun_structure_service as structure_service
import freshquant.market_data.xtdata.strategy_consumer as strategy_consumer
from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.data.adj_intraday import apply_qfq_with_intraday_override
from freshquant.data.qfq_contract import (
    QFQDataNotReadyError,
    require_qfq_ready_marker,
)
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

    def find_one(self, *_args, **_kwargs):
        return None


class _EmptyDatabase:
    def __getitem__(self, _name):
        return _EmptyCollection()


class _MarkerDatabase:
    def __init__(self, marker):
        self.marker = marker

    def __getitem__(self, _name):
        marker = self.marker

        class Collection:
            def find_one(self, *_args, **_kwargs):
                return marker

        return Collection()


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


def _consumer(monkeypatch, kind: str) -> strategy_consumer.StrategyConsumer:
    consumer = object.__new__(strategy_consumer.StrategyConsumer)
    consumer.max_bars = 32
    consumer._asset_kind = lambda _code: kind
    monkeypatch.setattr(
        strategy_consumer,
        "_load_minute_history_from_quantaxis_db",
        lambda **_kwargs: _bars(),
    )
    monkeypatch.setattr(strategy_consumer, "DBfreshquant", _EmptyDatabase())
    return consumer


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {
            "collection": "stock_adj",
            "status": "publishing",
            "source": "xtdata_preclose",
            "writer": "freshquant.market_data.xtdata.qfq",
        },
        {
            "collection": "stock_adj",
            "status": "ready",
            "source": "legacy",
            "writer": "freshquant.market_data.xtdata.qfq",
        },
        {
            "collection": "stock_adj",
            "status": "ready",
            "source": "xtdata_preclose",
            "writer": "legacy",
        },
    ],
)
def test_qfq_marker_must_match_canonical_ready_contract(marker):
    with pytest.raises(QFQDataNotReadyError, match="QFQ_DATA_NOT_READY"):
        require_qfq_ready_marker(
            db=_MarkerDatabase(marker), collection_name="stock_adj"
        )


def test_qfq_marker_accepts_matching_canonical_writer():
    marker = {
        "collection": "etf_adj",
        "status": "ready",
        "source": "xtdata_preclose",
        "writer": "freshquant.market_data.xtdata.qfq",
    }

    assert (
        require_qfq_ready_marker(db=_MarkerDatabase(marker), collection_name="etf_adj")
        == marker
    )


def test_strict_qfq_rejects_invalid_bar_date():
    bars = pd.DataFrame(
        {
            "datetime": ["2026-07-22 09:35:00", "not-a-date"],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.8, 9.9],
            "close": [10.1, 10.2],
        }
    )
    with pytest.raises(QFQDataNotReadyError, match="invalid trading dates"):
        apply_qfq_with_intraday_override(
            bars,
            pd.DataFrame([{"date": "2026-07-22", "adj": 1.0}]),
            override=None,
            strict=True,
            code="000001",
        )


def test_strict_qfq_rejects_invalid_intraday_anchor_scale():
    bars = _bars()
    with pytest.raises(QFQDataNotReadyError, match="anchor_scale"):
        apply_qfq_with_intraday_override(
            bars,
            pd.DataFrame([{"date": "2026-07-22", "adj": 1.0}]),
            override={"trade_date": "2026-07-22", "anchor_scale": 0.0},
            strict=True,
            code="000001",
        )


def test_strict_qfq_rejects_invalid_factor_rows_even_when_coverage_exists():
    bars = _bars()
    with pytest.raises(QFQDataNotReadyError, match="invalid=1"):
        apply_qfq_with_intraday_override(
            bars,
            pd.DataFrame(
                [
                    {"date": "2026-07-22", "adj": 1.0},
                    {"date": "2026-07-23", "adj": 0.0},
                ]
            ),
            override=None,
            strict=True,
            code="000001",
        )


@pytest.mark.parametrize("kind,code", [("stock", "sz000001"), ("etf", "sh510050")])
def test_qfq_read_fails_closed_when_factor_is_missing(monkeypatch, kind, code):
    consumer = _consumer(monkeypatch, kind)
    monkeypatch.setattr(
        strategy_consumer,
        "fetch_qfq_adj_df",
        lambda **_kwargs: pd.DataFrame(columns=["date", "adj"]),
    )
    monkeypatch.setattr(
        strategy_consumer, "fetch_intraday_override", lambda **_kwargs: None
    )

    with pytest.raises(QFQDataNotReadyError, match="QFQ_DATA_NOT_READY"):
        consumer._load_window_from_db(code=code, period_backend="5min")


def test_index_read_is_bfq_and_never_reads_factor(monkeypatch):
    consumer = _consumer(monkeypatch, "index")
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


def test_index_quote_fetcher_preserves_bfq_values(monkeypatch):
    source = _bars().copy()
    source.index = source["datetime"]
    monkeypatch.setattr(
        index_quote, "fq_data_index_fetch_min", lambda *args, **kwargs: source
    )

    result = index_quote.queryIndexCandleSticks("sh000300", "5m")

    assert result["close"].tolist() == [10.1, 10.3]
    assert result["open"].tolist() == [10.0, 10.2]


@pytest.mark.parametrize(
    "code,expected",
    [
        ("sz000001", InstrumentType.STOCK_CN),
        ("600000.SH", InstrumentType.STOCK_CN),
        ("sh520000", InstrumentType.ETF_CN),
        ("520000.SH", InstrumentType.ETF_CN),
        ("sh530001", InstrumentType.ETF_CN),
        ("530001.SH", InstrumentType.ETF_CN),
        ("sh000300", InstrumentType.INDEX_CN),
        ("000300.SH", InstrumentType.INDEX_CN),
        ("sz399001", InstrumentType.INDEX_CN),
        ("399001.SZ", InstrumentType.INDEX_CN),
    ],
)
def test_shared_cn_security_classification_boundaries(code, expected):
    assert infer_cn_instrument_type(code) == expected


def _signal_stub(df: pd.DataFrame) -> dict:
    empty = []
    return {
        "open": df["open"].tolist(),
        "high": df["high"].tolist(),
        "low": df["low"].tolist(),
        "close": df["close"].tolist(),
        "bi_data": empty,
        "duan_data": empty,
        "higher_duan_data": empty,
        "higher_higher_duan_data": empty,
        "zd_data": empty,
        "zs_flag": empty,
        "duan_zs_data": empty,
        "duan_zs_flag": empty,
        "high_duan_zs_data": empty,
        "high_duan_zs_flag": empty,
        "buy_zs_huila": None,
        "sell_zs_huila": None,
        "buy_v_reverse": None,
        "sell_v_reverse": None,
        "macd_bullish_divergence": empty,
        "macd_bearish_divergence": empty,
        "duan_signal_list": [0] * len(df),
    }


def test_get_data_v2_routes_index_to_bfq_fetcher(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        chanlun_service,
        "query_instrument_type",
        lambda _code: InstrumentType.INDEX_CN,
    )
    monkeypatch.setattr(chanlun_service, "calculate_trading_signals", _signal_stub)
    monkeypatch.setattr("freshquant.instrument.index.query_index_map", lambda: {})

    def fake_index(code, period, end_date, bar_count=0):
        captured["args"] = (code, period, end_date, bar_count)
        return _bars()

    monkeypatch.setattr(index_quote, "queryIndexCandleSticks", fake_index)
    payload = chanlun_service.get_data_v2("sh000300", "5m", bar_count=7)

    assert captured["args"] == ("sh000300", "5m", None, 7)
    assert payload["instrumentType"] == InstrumentType.INDEX_CN
    assert payload["close"] == [10.1, 10.3]


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


def test_chanlun_and_strategy_use_shared_security_classification(monkeypatch):
    monkeypatch.setattr(
        chanlun_service, "query_instrument_type", infer_cn_instrument_type
    )
    monkeypatch.setattr(
        "freshquant.instrument.general.query_instrument_type",
        infer_cn_instrument_type,
    )

    assert (
        chanlun_service._resolve_security_symbol_and_type("sh000300")[1]
        == InstrumentType.INDEX_CN
    )
    assert (
        chanlun_service._resolve_security_symbol_and_type("sz520000")[1]
        == InstrumentType.ETF_CN
    )
    assert (
        chanlun_service._resolve_security_symbol_and_type("sh530001")[1]
        == InstrumentType.ETF_CN
    )
    consumer = object.__new__(strategy_consumer.StrategyConsumer)
    assert consumer._asset_kind("sh000300") == "index"
    assert consumer._asset_kind("sh520000") == "etf"
    assert consumer._asset_kind("sh530001") == "etf"
    assert consumer._asset_kind("sz000001") == "stock"
