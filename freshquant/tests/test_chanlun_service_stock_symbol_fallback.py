import importlib
import sys
import types

import pandas as pd
import pytest

from freshquant.carnation.enum_instrument import InstrumentType


def _install_chanlun_stubs(monkeypatch):
    quantaxis_module = types.ModuleType("QUANTAXIS")

    placeholder_module = types.ModuleType("freshquant.placeholder")
    placeholder_module.fractal = []

    analysis_module = types.ModuleType("freshquant.analysis.chanlun_analysis")
    analysis_module.Chanlun = object

    def _calculate_trading_signals(df):
        size = len(df)
        return {
            "open": df["open"].to_list(),
            "high": df["high"].to_list(),
            "low": df["low"].to_list(),
            "close": df["close"].to_list(),
            "bi_data": [],
            "duan_data": [],
            "higher_duan_data": [],
            "higher_higher_duan_data": [],
            "zd_data": [],
            "zs_flag": [],
            "duan_zs_data": [],
            "duan_zs_flag": [],
            "high_duan_zs_data": [],
            "high_duan_zs_flag": [],
            "buy_zs_huila": [],
            "sell_zs_huila": [],
            "buy_v_reverse": [],
            "sell_v_reverse": [],
            "macd_bullish_divergence": [],
            "macd_bearish_divergence": [],
            "duan_signal_list": [0] * size,
        }

    analysis_module.calculate_trading_signals = _calculate_trading_signals

    config_module = types.ModuleType("freshquant.config")
    config_module.cfg = types.SimpleNamespace(TZ=None)
    config_module.config = {}
    config_module.settings = {}

    holding_module = types.ModuleType("freshquant.data.astock.holding")
    holding_module.get_stock_fills = lambda code: None

    future_basic_module = types.ModuleType("freshquant.data.future.basic")
    future_basic_module.fq_fetch_future_basic = lambda symbol: None

    instrument_etf_module = types.ModuleType("freshquant.instrument.etf")
    instrument_etf_module.query_etf_map = lambda: {}

    instrument_general_module = types.ModuleType("freshquant.instrument.general")
    instrument_general_module.query_instrument_type = lambda code: None

    instrument_stock_module = types.ModuleType("freshquant.instrument.stock")
    instrument_stock_module.query_stock_map = lambda: {}

    kline_module = types.ModuleType("freshquant.KlineDataTool")
    kline_module.getFutureData = lambda *args, **kwargs: None
    kline_module.getGlobalFutureData = lambda *args, **kwargs: None
    kline_module.get_future_data_v2 = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("future fetcher should not be used for stock-like code")
    )
    kline_module.get_stock_data = lambda *args, **kwargs: None

    macd_divergence_module = types.ModuleType(
        "freshquant.pattern.chanlun.macd_divergence"
    )
    macd_divergence_module.locate_macd_divergence = lambda *args, **kwargs: None

    position_future_module = types.ModuleType("freshquant.position.cn_future")
    position_future_module.queryArrangedCnFutureFillList = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("future fills should not be queried for stock-like code"))

    quote_etf_module = types.ModuleType("freshquant.quote.etf")
    quote_etf_module.queryEtfCandleSticks = lambda *args, **kwargs: (
        _ for _ in ()
    ).throw(AssertionError("ETF fetcher should not be used in this stock test"))

    bei_chi_module = types.ModuleType("freshquant.signal.bei_chi")
    bei_chi_module.huang_bai_xian_di_bei_chi = lambda *args, **kwargs: None
    bei_chi_module.mian_ji_di_bei_chi = lambda *args, **kwargs: None

    break_pivot_module = types.ModuleType("freshquant.signal.break_pivot")
    break_pivot_module.rise_break_pivot_gg = lambda *args, **kwargs: None
    break_pivot_module.rise_break_pivot_zd = lambda *args, **kwargs: None
    break_pivot_module.rise_break_pivot_zg = lambda *args, **kwargs: None
    break_pivot_module.rise_break_pivot_zm = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_module)
    monkeypatch.setitem(sys.modules, "freshquant.placeholder", placeholder_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.analysis.chanlun_analysis", analysis_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.config", config_module)
    monkeypatch.setitem(sys.modules, "freshquant.data.astock.holding", holding_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.data.future.basic", future_basic_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.instrument.etf", instrument_etf_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.general", instrument_general_module
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.instrument.stock", instrument_stock_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.KlineDataTool", kline_module)
    monkeypatch.setitem(
        sys.modules,
        "freshquant.pattern.chanlun.macd_divergence",
        macd_divergence_module,
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.position.cn_future", position_future_module
    )
    monkeypatch.setitem(sys.modules, "freshquant.quote.etf", quote_etf_module)
    monkeypatch.setitem(sys.modules, "freshquant.signal.bei_chi", bei_chi_module)
    monkeypatch.setitem(
        sys.modules, "freshquant.signal.break_pivot", break_pivot_module
    )


@pytest.fixture
def chanlun_service(monkeypatch):
    original_module = sys.modules.get("freshquant.chanlun_service")
    sys.modules.pop("freshquant.chanlun_service", None)
    _install_chanlun_stubs(monkeypatch)
    try:
        import freshquant.chanlun_service as chanlun_service_module

        yield importlib.reload(chanlun_service_module)
    finally:
        if original_module is None:
            sys.modules.pop("freshquant.chanlun_service", None)
        else:
            sys.modules["freshquant.chanlun_service"] = original_module


def test_get_data_v2_uses_stock_fetcher_for_bare_stock_code_when_maps_missing(
    monkeypatch, chanlun_service
):
    import freshquant.util.code as code_module

    captured = {}

    def fake_get_stock_data(symbol, period, end_date):
        captured["args"] = (symbol, period, end_date)
        return pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2026-03-11 09:35", "2026-03-11 09:40"]),
                "open": [10.0, 10.2],
                "high": [10.3, 10.4],
                "low": [9.9, 10.1],
                "close": [10.1, 10.3],
                "volume": [1000, 1200],
                "amount": [10000, 12360],
            }
        )

    monkeypatch.setattr(chanlun_service, "get_stock_data", fake_get_stock_data)
    monkeypatch.setattr(code_module, "query_stock_map", lambda: {})
    monkeypatch.setattr(code_module, "query_etf_map", lambda: {})
    monkeypatch.setattr(code_module, "query_bond_map", lambda: {})
    monkeypatch.setattr(code_module, "query_index_map", lambda: {})
    monkeypatch.setattr(
        chanlun_service, "query_instrument_type", lambda code: None, raising=False
    )
    monkeypatch.setattr(
        chanlun_service, "query_stock_map", lambda: {"sz002594": {"name": "比亚迪"}}
    )
    monkeypatch.setattr(chanlun_service, "query_etf_map", lambda: {})
    monkeypatch.setattr(chanlun_service, "get_stock_fills", lambda code: None)

    payload = chanlun_service.get_data_v2("002594", "5m")

    assert captured["args"] == ("sz002594", "5m", None)
    assert payload["symbol"] == "002594"
    assert payload["name"] == "比亚迪"
    assert payload["instrumentType"] == InstrumentType.STOCK_CN
    assert payload["future_fills"] is None
