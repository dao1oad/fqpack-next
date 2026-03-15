from datetime import datetime, timedelta

import pandas as pd

from freshquant.KlineDataTool import get_stock_data


def _build_stock_df(count: int) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01 09:30", periods=count, freq="5min")
    df = pd.DataFrame(
        {
            "datetime": dates,
            "open": list(range(count)),
            "high": list(range(1, count + 1)),
            "low": list(range(count)),
            "close": list(range(count)),
            "volume": [100.0] * count,
            "amount": [1000.0] * count,
            "time_stamp": [dt.timestamp() for dt in dates],
        }
    )
    return df.set_index("datetime", drop=False)


def test_get_stock_data_uses_bar_count_to_extend_window_and_tail_result(monkeypatch):
    seen = {}

    def fake_fetch(code, frequency, start, end):
        seen["code"] = code
        seen["frequency"] = frequency
        seen["start"] = start
        seen["end"] = end
        return _build_stock_df(25000)

    monkeypatch.setattr("freshquant.KlineDataTool.fq_data_stock_fetch_min", fake_fetch)

    result = get_stock_data("sz000001", "5m", "2026-03-13", bar_count=20000)

    assert seen["code"] == "000001"
    assert seen["frequency"] == "5min"
    assert (seen["end"] - seen["start"]) > timedelta(days=63)
    assert len(result) == 20000
    assert result["open"].iloc[0] == 5000
    assert result["open"].iloc[-1] == 24999
