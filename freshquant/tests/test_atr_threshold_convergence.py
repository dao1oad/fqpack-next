# -*- coding: utf-8 -*-
"""B5 ATR 收敛（总收口 PR7）：threshold 单实现 + 交易日缓存键 + holding 委托。"""

import importlib
import sys
import types
from datetime import datetime

from freshquant.carnation.enum_instrument import InstrumentType


def _reimport(monkeypatch, dotted):
    """清理被其他测试替换的包级 stub 后从磁盘重新导入目标模块。"""
    for name in list(sys.modules):
        if name == dotted or name.startswith(dotted + "."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(dotted)


def _fake_qa_data(high=(1.0, 2.0), low=(0.5, 1.0), close=(10.0, 11.0)):
    return types.SimpleNamespace(
        data=types.SimpleNamespace(
            high=types.SimpleNamespace(values=list(high)),
            low=types.SimpleNamespace(values=list(low)),
            close=types.SimpleNamespace(values=list(close)),
        )
    )


def test_compute_atr_last_stock_returns_tuple_and_anchors_window(monkeypatch):
    threshold_module = _reimport(monkeypatch, "freshquant.strategy.toolkit.threshold")
    captured = {}

    def fake_fetch(inst_code_base, start_date, end_date):
        captured["inst"] = inst_code_base
        captured["start"] = start_date
        captured["end"] = end_date
        return _fake_qa_data()

    monkeypatch.setattr(threshold_module, "QA_fetch_stock_day_adv", fake_fetch)
    monkeypatch.setattr(
        threshold_module,
        "apply_qfq_to_bars",
        lambda data, **kwargs: (data, None),
    )
    monkeypatch.setattr(
        threshold_module,
        "ATR",
        lambda high, low, close, period: [1.0, 1.5],
    )

    atr_value, close_price = threshold_module._compute_atr_last_stock(
        "000001", 20, "2024-03-10"
    )

    assert (atr_value, close_price) == (1.5, 11.0)
    assert captured == {
        "inst": "000001",
        "start": "2024-01-09",
        "end": "2024-03-09",
    }


def test_compute_atr_last_index_cache_key_includes_anchor_date(monkeypatch):
    threshold_module = _reimport(monkeypatch, "freshquant.strategy.toolkit.threshold")
    calls = []

    def fake_fetch(inst_code_base, start_date, end_date):
        calls.append((inst_code_base, start_date, end_date))
        return _fake_qa_data()

    monkeypatch.setattr(threshold_module, "QA_fetch_index_day_adv", fake_fetch)
    monkeypatch.setattr(
        threshold_module,
        "ATR",
        lambda high, low, close, period: [1.0, 1.5],
    )

    result_a = threshold_module._compute_atr_last_index("000300", 20, "2099-01-01")
    result_a_again = threshold_module._compute_atr_last_index(
        "000300", 20, "2099-01-01"
    )
    result_b = threshold_module._compute_atr_last_index("000300", 20, "2099-01-02")

    assert result_a == result_a_again == (1.5, 11.0)
    assert result_b == (1.5, 11.0)
    assert len(calls) == 2
    assert calls[0][2] == "2098-12-31"
    assert calls[1][2] == "2099-01-01"


def test_query_grid_interval_delegates_atr_to_threshold(monkeypatch):
    holding_module = _reimport(monkeypatch, "freshquant.data.astock.holding")
    calls = []

    fake_threshold = types.ModuleType("freshquant.strategy.toolkit.threshold")
    fake_threshold._compute_atr_last_stock = (
        lambda inst_code_base, period, anchor_date: calls.append(
            ("stock", inst_code_base, period, anchor_date)
        )
        or (2.0, 20.0)
    )
    fake_threshold._compute_atr_last_index = (
        lambda inst_code_base, period, anchor_date: calls.append(
            ("index", inst_code_base, period, anchor_date)
        )
        or (2.0, 20.0)
    )
    monkeypatch.setitem(
        sys.modules, "freshquant.strategy.toolkit.threshold", fake_threshold
    )
    monkeypatch.setattr(
        holding_module,
        "query_instrument_type",
        lambda code: InstrumentType.STOCK_CN,
    )
    monkeypatch.setattr(
        holding_module,
        "get_grid_interval_config",
        lambda instrument_code: {"mode": "atr", "atr": {"period": 20, "multiplier": 1}},
    )

    interval = holding_module._query_grid_interval("000001", "2024-03-10")

    assert interval == 1.1
    assert calls == [("stock", "000001", 20, "2024-03-10")]


def test_eval_stock_threshold_price_atr_mode_anchors_to_today(monkeypatch):
    threshold_module = _reimport(monkeypatch, "freshquant.strategy.toolkit.threshold")
    captured = {}

    def fake_atr(inst_code_base, period, anchor_date):
        captured["anchor"] = anchor_date
        return (1.0, 10.0)

    monkeypatch.setattr(threshold_module, "_compute_atr_last_stock", fake_atr)
    monkeypatch.setattr(
        threshold_module,
        "query_instrument_type",
        lambda code: InstrumentType.STOCK_CN,
    )
    monkeypatch.setattr(
        threshold_module,
        "get_threshold_config",
        lambda instrument_code: {"mode": "atr", "atr": {"period": 20, "multiplier": 1}},
    )

    result = threshold_module.eval_stock_threshold_price("000001", 10.0)

    assert result["top_river_price"] == 11.0
    assert result["bot_river_price"] == 9.0
    assert captured["anchor"] == datetime.now().strftime("%Y-%m-%d")
