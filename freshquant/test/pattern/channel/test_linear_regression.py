# coding: utf-8

import pytest
import numpy as np
import pandas as pd
from datetime import datetime

from freshquant.KlineDataTool import get_stock_data
from freshquant.config import cfg
from freshquant.pattern.channel import (
    linear_regression_channel,
    rolling_linear_regression_channel,
    channel_breakout_signal,
    channel_support_signal,
    channel_resistance_signal,
    channel_comprehensive_signal,
    RealTimeLinearRegressionChannel,
)


def test_linear_regression_basic():
    """测试基础计算"""

    # 构造测试数据：明确的上升趋势
    np.random.seed(42)
    n = 50
    x = np.linspace(0, 100, n)
    y = 2 * x + 100 + np.random.randn(n) * 5

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-01", periods=n, freq="D"),
            "open": y,
            "high": y + 2,
            "low": y - 2,
            "close": y,
            "volume": 1000000,
            "amount": 100000000,
        }
    )
    df["time_str"] = df["datetime"].apply(lambda dt: dt.strftime("%Y-%m-%d"))
    df.set_index("datetime", inplace=True, drop=False)

    # 计算通道
    result = linear_regression_channel(df, period=50)

    assert result["is_valid"] == True
    # 斜率约为 4 (因为 x 是 0-100，斜率 2 的直线在 50 个点中斜率接近 4)
    assert abs(result["slope"]) > 0  # 斜率应大于 0
    assert result["r_squared"] > 0.95  # 拟合度应较高


def test_insufficient_data():
    """测试数据不足异常"""

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-01", periods=2, freq="D"),
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [1000, 1000],
            "amount": [100000, 100000],
        }
    )
    df["time_str"] = df["datetime"].apply(lambda dt: dt.strftime("%Y-%m-%d"))
    df.set_index("datetime", inplace=True, drop=False)

    with pytest.raises(ValueError, match="数据长度不足"):
        linear_regression_channel(df, period=50)


def test_price_source_variants():
    """测试不同价格源"""

    # 构造测试数据
    np.random.seed(42)
    n = 50
    y = 100 + np.random.randn(n) * 5

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-01", periods=n, freq="D"),
            "open": y + 1,
            "high": y + 3,
            "low": y - 2,
            "close": y,
            "volume": 1000000,
            "amount": 100000000,
        }
    )
    df.set_index("datetime", inplace=True, drop=False)

    # 测试不同价格源
    sources = ["close", "hl2", "hlc3", "ohlc4"]
    for source in sources:
        result = linear_regression_channel(df, period=30, price_source=source)
        assert "upper" in result
        assert "lower" in result
        assert "center" in result


def test_signals():
    """测试信号生成"""

    # 构造测试数据
    n = 50
    x = np.linspace(0, 100, n)
    y = 2 * x + 100

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-01", periods=n, freq="D"),
            "open": y,
            "high": y + 2,
            "low": y - 2,
            "close": y,
            "volume": 1000000,
            "amount": 100000000,
        }
    )
    df.set_index("datetime", inplace=True, drop=False)

    channel = linear_regression_channel(df, period=50)

    # 测试突破信号
    breakout = channel_breakout_signal(df, channel)
    assert "signal" in breakout

    # 测试支撑信号
    support = channel_support_signal(df, channel)
    assert "signal" in support

    # 测试阻力信号
    resistance = channel_resistance_signal(df, channel)
    assert "signal" in resistance

    # 测试综合信号
    comprehensive = channel_comprehensive_signal(df, channel)
    assert "trading_signal" in comprehensive


def test_realtime_channel():
    """测试实时更新类"""

    rt_channel = RealTimeLinearRegressionChannel(period=10, std_multiplier=2.0)

    # 初始状态
    result = rt_channel.update(100.0)
    assert result["is_valid"] == False

    # 填充数据
    for i in range(10):
        result = rt_channel.update(100 + i)

    assert result["is_valid"] == True
    assert "upper" in result
    assert "lower" in result

    # 测试重置
    rt_channel.reset()
    assert len(rt_channel.prices) == 0


def test_freshquant_integration():
    """测试 FreshQuant 集成"""

    # 获取真实数据
    df = get_stock_data("sh600000", "1d", None)  # endDate=None 获取最新数据

    if df is not None and len(df) >= 50:
        df["time_str"] = df["datetime"].apply(
            lambda dt: dt.strftime(cfg.DT_FORMAT_FULL)
        )

        result = linear_regression_channel(df, period=50)

        if result["is_valid"]:
            assert "slope" in result
            assert "r_squared" in result
        else:
            assert "reason" in result
    else:
        pytest.skip("数据不足，跳过集成测试")
