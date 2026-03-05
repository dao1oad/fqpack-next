# -*- coding: utf-8 -*-
"""
线性回归标准差通道模块

基于线性回归和标准差构建价格通道，用于趋势识别和交易信号生成。
"""

from freshquant.pattern.channel.linear_regression import (
    linear_regression_channel,
    rolling_linear_regression_channel,
    dual_linear_regression_channel,
)
from freshquant.pattern.channel.signals import (
    channel_breakout_signal,
    channel_support_signal,
    channel_resistance_signal,
    channel_comprehensive_signal,
)
from freshquant.pattern.channel.realtime import RealTimeLinearRegressionChannel
from freshquant.pattern.channel.chart import create_channel_chart, create_dual_channel_chart

__all__ = [
    # 核心算法
    "linear_regression_channel",
    "rolling_linear_regression_channel",
    "dual_linear_regression_channel",
    # 信号生成
    "channel_breakout_signal",
    "channel_support_signal",
    "channel_resistance_signal",
    "channel_comprehensive_signal",
    # 实时更新
    "RealTimeLinearRegressionChannel",
    # 可视化
    "create_channel_chart",
    "create_dual_channel_chart",
]
