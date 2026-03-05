# -*- coding: utf-8 -*-
"""
线性回归通道 - 信号生成模块

提供突破信号、支撑信号、阻力信号和综合信号分析。
"""

from typing import Dict, Any, List
import numpy as np
import pandas as pd


def channel_breakout_signal(
    df: pd.DataFrame,
    channel: Dict[str, np.ndarray],
) -> Dict[str, Any]:
    """
    检测价格是否突破通道边界

    Parameters
    ----------
    df : pd.DataFrame
        K线数据
    channel : Dict
        通道计算结果

    Returns
    -------
    Dict with keys:
        - signal: 'bullish_breakout' | 'bearish_breakout' | 'no_breakout'
        - distance: 突破距离（通道宽度的比例）
        - reason: 信号原因说明
    """
    if not channel["is_valid"]:
        return {
            "signal": "no_breakout",
            "reason": "通道无效",
        }

    current_price = df["close"].iloc[-1]
    upper = channel["upper"][-1]
    lower = channel["lower"][-1]
    width = upper - lower

    # 检查突破
    if current_price > upper:
        distance = (current_price - upper) / width
        return {
            "signal": "bullish_breakout",
            "distance": distance,
            "reason": f"突破上轨，距离 {distance * 100:.1f}% 通道宽度",
        }
    elif current_price < lower:
        distance = (lower - current_price) / width
        return {
            "signal": "bearish_breakout",
            "distance": distance,
            "reason": f"突破下轨，距离 {distance * 100:.1f}% 通道宽度",
        }
    else:
        return {
            "signal": "no_breakout",
            "distance": 0.0,
            "reason": "价格在通道内",
        }


def channel_support_signal(
    df: pd.DataFrame,
    channel: Dict[str, np.ndarray],
    lookback: int = 5,
    threshold: float = 0.02,
) -> Dict[str, Any]:
    """
    检测价格是否获得通道支撑（下轨支撑）

    支撑信号特征：
    1. 价格接近或触及下轨
    2. 最近几根K线的低点在下轨附近获得支撑
    3. 价格有反弹迹象

    Parameters
    ----------
    df : pd.DataFrame
        K线数据
    channel : Dict
        通道计算结果
    lookback : int
        检查最近几根K线
    threshold : float
        距离下轨的阈值（通道宽度的比例，0.02 = 2%）

    Returns
    -------
    Dict with keys:
        - signal: 'strong_support' | 'weak_support' | 'no_support'
        - distance_to_lower: 距离下轨的距离（通道宽度的比例）
        - touch_count: 最近 lookback 根K线触及下轨的次数
        - rebound_strength: 反弹强度（最近涨跌幅）
        - reason: 信号原因说明
    """
    if not channel["is_valid"]:
        return {
            "signal": "no_support",
            "reason": "通道无效",
        }

    recent = df.iloc[-lookback:]
    upper = channel["upper"][-lookback:]
    lower = channel["lower"][-lookback:]
    width = upper - lower

    # 检查触及下轨的次数
    touch_count = 0
    min_distance_to_lower = 1.0

    for i in range(len(recent)):
        price = recent["close"].iloc[i]
        u = upper[i]
        l = lower[i]
        w = width[i]

        # 计算距离下轨的距离（通道宽度的比例）
        distance = (price - l) / w
        min_distance_to_lower = min(min_distance_to_lower, distance)

        # 触及或非常接近下轨（阈值内）
        if distance < threshold:
            touch_count += 1

    # 计算反弹强度
    first_close = recent["close"].iloc[0]
    last_close = recent["close"].iloc[-1]
    rebound_strength = (
        (last_close - first_close) / first_close if first_close > 0 else 0
    )

    # 综合判断
    current_distance = min_distance_to_lower

    if touch_count >= 2 and rebound_strength > 0.01:
        signal = "strong_support"
        reason = f"多次触及下轨({touch_count}次)且反弹{rebound_strength * 100:.1f}%"

    elif current_distance < threshold:
        signal = "weak_support"
        reason = f"接近下轨，距离{current_distance * 100:.1f}%通道宽度"

    else:
        signal = "no_support"
        reason = f"距离下轨{current_distance * 100:.1f}%通道宽度，未获支撑"

    return {
        "signal": signal,
        "distance_to_lower": current_distance,
        "touch_count": touch_count,
        "rebound_strength": rebound_strength,
        "reason": reason,
    }


def channel_resistance_signal(
    df: pd.DataFrame,
    channel: Dict[str, np.ndarray],
    lookback: int = 5,
    threshold: float = 0.02,
) -> Dict[str, Any]:
    """
    检测价格是否遇到通道阻力（上轨阻力）

    阻力信号特征：
    1. 价格接近或触及上轨
    2. 最近几根K线的高点在上轨附近受阻
    3. 价格有回落迹象

    Parameters
    ----------
    df : pd.DataFrame
        K线数据
    channel : Dict
        通道计算结果
    lookback : int
        检查最近几根K线
    threshold : float
        距离上轨的阈值（通道宽度的比例，0.02 = 2%）

    Returns
    -------
    Dict with keys:
        - signal: 'strong_resistance' | 'weak_resistance' | 'no_resistance'
        - distance_to_upper: 距离上轨的距离（通道宽度的比例）
        - touch_count: 最近 lookback 根K线触及上轨的次数
        - pullback_strength: 回落强度（最近涨跌幅）
        - reason: 信号原因说明
    """
    if not channel["is_valid"]:
        return {
            "signal": "no_resistance",
            "reason": "通道无效",
        }

    recent = df.iloc[-lookback:]
    upper = channel["upper"][-lookback:]
    lower = channel["lower"][-lookback:]
    width = upper - lower

    # 检查触及上轨的次数
    touch_count = 0
    min_distance_to_upper = 1.0

    for i in range(len(recent)):
        price = recent["close"].iloc[i]
        u = upper[i]
        l = lower[i]
        w = width[i]

        # 计算距离上轨的距离（通道宽度的比例）
        distance = (u - price) / w
        min_distance_to_upper = min(min_distance_to_upper, distance)

        # 触及或非常接近上轨（阈值内）
        if distance < threshold:
            touch_count += 1

    # 计算回落强度
    first_close = recent["close"].iloc[0]
    last_close = recent["close"].iloc[-1]
    pullback_strength = (
        (first_close - last_close) / first_close if first_close > 0 else 0
    )

    # 综合判断
    current_distance = min_distance_to_upper

    if touch_count >= 2 and pullback_strength > 0.01:
        signal = "strong_resistance"
        reason = f"多次触及上轨({touch_count}次)且回落{pullback_strength * 100:.1f}%"

    elif current_distance < threshold:
        signal = "weak_resistance"
        reason = f"接近上轨，距离{current_distance * 100:.1f}%通道宽度"

    else:
        signal = "no_resistance"
        reason = f"距离上轨{current_distance * 100:.1f}%通道宽度，未遇阻力"

    return {
        "signal": signal,
        "distance_to_upper": current_distance,
        "touch_count": touch_count,
        "pullback_strength": pullback_strength,
        "reason": reason,
    }


def channel_comprehensive_signal(
    df: pd.DataFrame,
    channel: Dict[str, np.ndarray],
    lookback: int = 5,
    threshold: float = 0.02,
) -> Dict[str, Any]:
    """
    综合通道信号分析（突破 + 支撑 + 阻力）

    Returns
    -------
    Dict with comprehensive trading signal
    """
    # 突破信号
    breakout = channel_breakout_signal(df, channel)

    # 支撑信号
    support = channel_support_signal(df, channel, lookback, threshold)

    # 阻力信号
    resistance = channel_resistance_signal(df, channel, lookback, threshold)

    # 当前价格位置
    current_price = df["close"].iloc[-1]
    upper = channel["upper"][-1]
    lower = channel["lower"][-1]
    position = (current_price - lower) / (upper - lower)

    # 综合判断
    result = {
        "current_price": current_price,
        "upper": upper,
        "lower": lower,
        "position_pct": position * 100,
        "breakout": breakout["signal"],
        "support": support["signal"],
        "resistance": resistance["signal"],
        "trading_signal": None,
        "trading_reason": [],
    }

    # 优先级判断
    if breakout["signal"] == "bullish_breakout":
        result["trading_signal"] = "strong_buy"
        result["trading_reason"].append("突破上轨，强势买入")

    elif breakout["signal"] == "bearish_breakout":
        result["trading_signal"] = "strong_sell"
        result["trading_reason"].append("突破下轨，强势卖出")

    elif support["signal"] == "strong_support":
        result["trading_signal"] = "buy"
        result["trading_reason"].append(f"下轨强支撑: {support['reason']}")

    elif resistance["signal"] == "strong_resistance":
        result["trading_signal"] = "sell"
        result["trading_reason"].append(f"上轨强阻力: {resistance['reason']}")

    elif support["signal"] == "weak_support":
        result["trading_signal"] = "watch_buy"
        result["trading_reason"].append(f"接近下轨支撑: {support['reason']}")

    elif resistance["signal"] == "weak_resistance":
        result["trading_signal"] = "watch_sell"
        result["trading_reason"].append(f"接近上轨阻力: {resistance['reason']}")

    else:
        result["trading_signal"] = "hold"
        result["trading_reason"].append(f"通道中部，位置{position * 100:.1f}%")

    result["trading_reason"] = " | ".join(result["trading_reason"])

    return result
