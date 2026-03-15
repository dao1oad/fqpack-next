import importlib
import sys
import types
from datetime import datetime, timedelta

import pandas as pd
import pytest


class _NoopCache:
    def memoize(self, expiration=0):
        def decorator(func):
            return func

        return decorator


def _identity_frame(data, *args, **kwargs):
    return data


def _unused_fetcher(*args, **kwargs):
    raise AssertionError("unexpected dependency call in test_kline_data_bar_count")


def _install_kline_data_tool_stubs(monkeypatch):
    quantaxis_module = types.ModuleType("QUANTAXIS")
    qa_data_package = types.ModuleType("QUANTAXIS.QAData")
    data_resample_module = types.ModuleType("QUANTAXIS.QAData.data_resample")
    data_resample_module.QA_data_day_resample = _identity_frame
    data_resample_module.QA_data_futureday_resample = _identity_frame
    data_resample_module.QA_data_futuremin_resample = _identity_frame
    data_resample_module.QA_data_stockmin_resample = _identity_frame
    quantaxis_module.QAData = qa_data_package
    qa_data_package.data_resample = data_resample_module

    config_module = types.ModuleType("freshquant.config")
    config_module.cfg = types.SimpleNamespace(TZ=None, TIME_DELTA={"5m": -63})

    future_db_module = types.ModuleType("freshquant.data.future.db")
    future_db_module.fq_data_future_fetch_day = _unused_fetcher
    future_db_module.fq_data_future_fetch_min = _unused_fetcher

    stock_module = types.ModuleType("freshquant.data.stock")
    stock_module.fq_data_stock_fetch_day = _unused_fetcher
    stock_module.fq_data_stock_fetch_min = _unused_fetcher
    stock_module.fq_data_stock_resample_90min = _identity_frame
    stock_module.fq_data_stock_resample_120min = _identity_frame
    stock_module.fqDataStockResample3min = _identity_frame

    cache_module = types.ModuleType("freshquant.database.cache")
    cache_module.in_memory_cache = _NoopCache()

    db_module = types.ModuleType("freshquant.db")
    db_module.DBfreshquant = object()

    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAData", qa_data_package)
    monkeypatch.setitem(
        sys.modules, "QUANTAXIS.QAData.data_resample", data_resample_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.config", config_module)
    monkeypatch.setitem(sys.modules, "freshquant.data.future.db", future_db_module)
    monkeypatch.setitem(sys.modules, "freshquant.data.stock", stock_module)
    monkeypatch.setitem(sys.modules, "freshquant.database.cache", cache_module)
    monkeypatch.setitem(sys.modules, "freshquant.db", db_module)


@pytest.fixture
def kline_data_tool(monkeypatch):
    original_module = sys.modules.get("freshquant.KlineDataTool")
    sys.modules.pop("freshquant.KlineDataTool", None)
    _install_kline_data_tool_stubs(monkeypatch)
    try:
        import freshquant.KlineDataTool as kline_data_tool_module

        yield importlib.reload(kline_data_tool_module)
    finally:
        if original_module is None:
            sys.modules.pop("freshquant.KlineDataTool", None)
        else:
            sys.modules["freshquant.KlineDataTool"] = original_module


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


def test_get_stock_data_uses_bar_count_to_extend_window_and_tail_result(
    monkeypatch, kline_data_tool
):
    seen = {}

    def fake_fetch(code, frequency, start, end):
        seen["code"] = code
        seen["frequency"] = frequency
        seen["start"] = start
        seen["end"] = end
        return _build_stock_df(25000)

    monkeypatch.setattr(kline_data_tool, "fq_data_stock_fetch_min", fake_fetch)

    result = kline_data_tool.get_stock_data(
        "sz000001", "5m", "2026-03-13", bar_count=20000
    )

    assert seen["code"] == "000001"
    assert seen["frequency"] == "5min"
    assert (seen["end"] - seen["start"]) > timedelta(days=63)
    assert len(result) == 20000
    assert result["open"].iloc[0] == 5000
    assert result["open"].iloc[-1] == 24999
