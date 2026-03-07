import pandas as pd
import pytest

try:
    from freshquant.chanlun_structure_service import (
        build_chanlun_structure_payload,
        build_dataframe_from_cache_payload,
    )
except ImportError:
    build_chanlun_structure_payload = None
    build_dataframe_from_cache_payload = None


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
