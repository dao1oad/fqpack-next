import sys
import types

import pandas as pd
import pytest

from freshquant.chanlun_structure_service import (
    DEFAULT_BAR_LIMIT,
    _sanitize_kline_df,
    build_chanlun_structure_payload,
    build_dataframe_from_cache_payload,
    get_chanlun_structure,
)


def test_build_dataframe_from_cache_payload_keeps_ohlcv_alignment():
    assert build_dataframe_from_cache_payload is not None

    payload = {
        "date": ["2026-03-07 09:30", "2026-03-07 09:35"],
        "open": [10.0, 10.1],
        "high": [10.2, 10.3],
        "low": [9.9, 10.0],
        "close": [10.1, 10.2],
        "volume": [100, 120],
        "amount": [1000.0, 1224.0],
    }

    df = build_dataframe_from_cache_payload(payload)

    assert list(df.columns) == [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]
    assert len(df) == 2
    assert df["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist() == payload["date"]
    assert df["close"].tolist() == [10.1, 10.2]


def test_build_chanlun_structure_payload_extracts_last_higher_segment_segment_and_bi():
    assert build_chanlun_structure_payload is not None

    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2026-03-07 09:30",
                    "2026-03-07 09:35",
                    "2026-03-07 09:40",
                    "2026-03-07 09:45",
                ]
            ),
            "open": [10.0, 10.1, 10.2, 10.15],
            "high": [10.1, 10.3, 10.35, 10.4],
            "low": [9.9, 10.0, 10.1, 10.05],
            "close": [10.05, 10.2, 10.15, 10.3],
            "volume": [1, 1, 1, 1],
            "amount": [1, 1, 1, 1],
        }
    )
    fc_res = {
        "ok": True,
        "bi": [0, -1, 0, 1],
        "duan": [0, -1, 0, 1],
        "duan_high": [0, -1, 0, 1],
        "pivots": [
            {
                "start": 1,
                "end": 3,
                "zg": 10.28,
                "zd": 10.14,
                "gg": 10.4,
                "dd": 10.0,
                "direction": 1,
            }
        ],
        "pivots_high": [
            {
                "start": 1,
                "end": 3,
                "zg": 10.28,
                "zd": 10.14,
                "gg": 10.4,
                "dd": 10.0,
                "direction": 1,
            }
        ],
    }

    result = build_chanlun_structure_payload(
        symbol="sz000001",
        period="5m",
        end_date=None,
        df=df,
        fc_res=fc_res,
        source="realtime_cache_fullcalc",
    )

    higher = result["structure"]["higher_segment"]
    segment = result["structure"]["segment"]
    bi = result["structure"]["bi"]

    assert result["ok"] is True
    assert result["source"] == "realtime_cache_fullcalc"
    assert result["bar_count"] == 4
    assert higher["direction"] == "up"
    assert higher["start_time"] == "2026-03-07 09:35"
    assert higher["end_time"] == "2026-03-07 09:45"
    assert higher["contained_duan_count"] == 1
    assert higher["pivot_count"] == 1
    assert higher["pivots"][0]["zg"] == pytest.approx(10.28)
    assert segment["direction"] == "up"
    assert segment["contained_bi_count"] == 1
    assert segment["pivot_count"] == 1
    assert bi["direction"] == "up"
    assert bi["start_price"] == pytest.approx(10.0)
    assert bi["end_price"] == pytest.approx(10.4)
    assert bi["price_change_pct"] == pytest.approx(4.0)


def test_sanitize_kline_df_sorts_before_fill():
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2026-03-07 09:35",
                    "2026-03-07 09:40",
                    "2026-03-07 09:30",
                ]
            ),
            "open": [None, 20.0, 10.0],
            "high": [None, 20.2, 10.2],
            "low": [None, 19.8, 9.8],
            "close": [None, 20.1, 10.1],
            "volume": [None, 200.0, 100.0],
            "amount": [None, 2000.0, 1000.0],
        }
    )

    clean = _sanitize_kline_df(df, limit=0)

    assert clean["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist() == [
        "2026-03-07 09:30",
        "2026-03-07 09:35",
        "2026-03-07 09:40",
    ]
    assert clean["open"].tolist() == [10.0, 10.0, 20.0]


def test_sanitize_kline_df_handles_datetime_as_index_and_column():
    idx = pd.Index(
        pd.to_datetime(["2026-03-07 09:35", "2026-03-07 09:30"]),
        name="datetime",
    )
    df = pd.DataFrame(
        {
            "open": [20.0, 10.0],
            "high": [20.2, 10.2],
            "low": [19.8, 9.8],
            "close": [20.1, 10.1],
            "volume": [200.0, 100.0],
        },
        index=idx,
    )
    df["datetime"] = df.index

    clean = _sanitize_kline_df(df, limit=0)

    assert clean["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist() == [
        "2026-03-07 09:30",
        "2026-03-07 09:35",
    ]
    assert clean["open"].tolist() == [10.0, 20.0]


def test_get_chanlun_structure_sanitizes_realtime_cache_before_fullcalc(monkeypatch):
    dates = pd.date_range("2026-03-07 09:30", periods=DEFAULT_BAR_LIMIT + 5, freq="min")
    payload = {
        "date": dates.strftime("%Y-%m-%d %H:%M").tolist(),
        "open": list(range(DEFAULT_BAR_LIMIT + 5)),
        "high": list(range(1, DEFAULT_BAR_LIMIT + 6)),
        "low": list(range(DEFAULT_BAR_LIMIT + 5)),
        "close": list(range(DEFAULT_BAR_LIMIT + 5)),
        "volume": [100.0] * (DEFAULT_BAR_LIMIT + 5),
        "amount": [1000.0] * (DEFAULT_BAR_LIMIT + 5),
    }
    seen = {}

    monkeypatch.setattr(
        "freshquant.chanlun_structure_service._get_realtime_cache_payload",
        lambda symbol, period, end_date: payload,
    )
    monkeypatch.setattr(
        "freshquant.chanlun_structure_service._fetch_kline_df",
        lambda symbol, period, end_date: pytest.fail("should use realtime cache"),
    )

    def run_fullcalc_stub(df, model_ids):
        seen["bar_count"] = len(df)
        return {
            "ok": True,
            "bi": [0] * len(df),
            "duan": [0] * len(df),
            "duan_high": [0] * len(df),
            "pivots": [],
            "pivots_high": [],
        }

    stub_module = types.SimpleNamespace(run_fullcalc=run_fullcalc_stub)
    monkeypatch.setitem(
        sys.modules, "freshquant.analysis.fullcalc_wrapper", stub_module
    )

    result = get_chanlun_structure("sz000001", "5m")

    assert seen["bar_count"] == DEFAULT_BAR_LIMIT
    assert result["source"] == "realtime_cache_fullcalc"
