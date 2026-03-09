from datetime import datetime

import pandas as pd

from freshquant.data.adj_intraday import apply_qfq_with_intraday_override


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "datetime": datetime(2026, 3, 8, 14, 55),
                "open": 10.0,
                "high": 10.8,
                "low": 9.9,
                "close": 10.5,
            },
            {
                "datetime": datetime(2026, 3, 9, 9, 35),
                "open": 11.0,
                "high": 11.8,
                "low": 10.9,
                "close": 11.5,
            },
        ]
    )


def _base_adj() -> pd.DataFrame:
    return pd.DataFrame([{"date": "2026-03-08", "adj": 2.0}])


def test_apply_qfq_with_intraday_override_keeps_trade_date_raw_and_rescales_history():
    out = apply_qfq_with_intraday_override(
        _bars(),
        _base_adj(),
        override={"trade_date": "2026-03-09", "anchor_scale": 0.5},
    )

    assert out["open"].tolist() == [10.0, 11.0]
    assert out["close"].tolist() == [10.5, 11.5]


def test_apply_qfq_with_intraday_override_falls_back_to_base_adj_when_override_missing():
    out = apply_qfq_with_intraday_override(_bars(), _base_adj(), override=None)

    assert out["open"].tolist() == [20.0, 22.0]
    assert out["close"].tolist() == [21.0, 23.0]
