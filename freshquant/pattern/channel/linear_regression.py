# -*- coding: utf-8 -*-
"""
线性回归标准差通道 - 核心算法实现

基于线性回归和标准差构建价格通道，用于趋势识别和交易信号生成。
"""

from typing import Dict, Optional
import numpy as np
import pandas as pd
from scipy.stats import linregress


def _linear_regression_compute(
    y: np.ndarray,
    std_multiplier: float = 2.0,
) -> Dict[str, np.ndarray]:
    """
    内部函数：对给定的价格序列执行线性回归通道计算

    Parameters
    ----------
    y : np.ndarray
        价格序列
    std_multiplier : float
        标准差倍数

    Returns
    -------
    Dict with keys: upper, lower, center, slope, intercept, r_squared, std, is_valid
    """
    x = np.arange(len(y))

    # 线性回归
    slope, intercept, r_value, p_value, std_err = linregress(x, y)
    regression_line = slope * x + intercept

    # 计算标准差
    deviations = y - regression_line
    std = np.std(deviations, ddof=0)

    # 数值稳定性检查
    if std < 1e-10:
        return {
            "upper": regression_line,
            "lower": regression_line,
            "center": regression_line,
            "slope": slope,
            "intercept": intercept,
            "r_squared": 1.0,
            "std": std,
            "is_valid": False,
            "reason": "价格波动极小，无法构建有效通道",
        }

    # 构建通道
    upper_band = regression_line + std_multiplier * std
    lower_band = regression_line - std_multiplier * std

    return {
        "upper": upper_band,
        "lower": lower_band,
        "center": regression_line,
        "slope": slope,
        "intercept": intercept,
        "r_squared": r_value**2,
        "std": std,
        "is_valid": True,
    }


def linear_regression_channel(
    df: pd.DataFrame,
    period: int = 50,
    price_source: str = "close",
    std_multiplier: float = 2.0,
    min_r_squared: Optional[float] = None,
) -> Dict[str, np.ndarray]:
    """
    基于线性回归的标准差通道

    Parameters
    ----------
    df : pd.DataFrame
        包含 'open', 'high', 'low', 'close' 的K线数据（小写列名）
    period : int
        回溯周期（K线数量）
    price_source : str
        价格源：'close'/'hl2'/'hlc3'/'ohlc4'
    std_multiplier : float
        标准差倍数（通常 1.5 ~ 2.5）
    min_r_squared : float, optional
        最小拟合优度阈值，低于此值返回无效通道

    Returns
    -------
    Dict[str, np.ndarray]
        {
            'upper': 上轨序列,
            'lower': 下轨序列,
            'center': 中轨序列,
            'slope': 斜率,
            'intercept': 截距,
            'r_squared': 拟合优度,
            'std': 标准差,
            'is_valid': 通道是否有效
        }
    """
    # ========== 输入验证 ==========
    if len(df) < period:
        raise ValueError(
            f"数据长度不足: {len(df)} < {period}，"
            f"请至少提供 {period} 根 K 线"
        )

    if period < 3:
        raise ValueError(
            f"周期过小: {period} < 3，"
            f"至少需要 3 个点进行线性回归"
        )

    if std_multiplier <= 0:
        raise ValueError(
            f"标准差倍数必须为正数: {std_multiplier}"
        )

    # 验证必需列
    required_cols = ["open", "high", "low", "close"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"缺少必需列: {missing}，"
            f"请确保数据包含: {required_cols}"
        )

    # 检查 NaN
    if df[required_cols].isna().any().any():
        nan_info = df[required_cols].isna().sum()
        raise ValueError(
            f"数据包含 NaN 值: {nan_info[nan_info > 0].to_dict()}，"
            f"请先处理缺失值"
        )

    # 数据准备
    data = df.iloc[-period:].copy()

    # 选择价格源
    if price_source == "close":
        y = data["close"].values
    elif price_source == "hl2":
        y = (data["high"] + data["low"]) / 2
    elif price_source == "hlc3":
        y = (data["high"] + data["low"] + data["close"]) / 3
    elif price_source == "ohlc4":
        y = (data["open"] + data["high"] + data["low"] + data["close"]) / 4
    else:
        raise ValueError(f"不支持的价格源: {price_source}")

    # 计算通道
    result = _linear_regression_compute(y, std_multiplier)

    # 质量评估
    if min_r_squared is not None and result["r_squared"] < min_r_squared:
        result["is_valid"] = False
        result["reason"] = f"拟合优度不足: {result['r_squared']:.4f} < {min_r_squared}"

    return result


def dual_linear_regression_channel(
    df: pd.DataFrame,
    chanlun,
    price_source: str = "close",
    std_multiplier: float = 2.0,
    min_r_squared: Optional[float] = None,
) -> Dict[str, Dict]:
    """
    基于缠论线段的双通道计算

    计算两个通道：
    - 通道1（历史）：基于倒数第2个线段，延伸到现在
    - 通道2（当前）：基于倒数第1个线段到现在

    Parameters
    ----------
    df : pd.DataFrame
        K线数据
    chanlun : Chanlun
        缠论分析结果
    price_source : str
        价格源
    std_multiplier : float
        标准差倍数
    min_r_squared : float, optional
        最小拟合优度

    Returns
    -------
    Dict with keys:
        - 'channel1': 历史通道（倒数第2个线段）
        - 'channel2': 当前通道（倒数第1个线段）
        - 'comparison': 两通道对比信息
    """
    # 获取线段数据
    duan_dt = chanlun.duan_data["dt"]
    duan_data = chanlun.duan_data["data"]

    # 检查是否有足够的线段
    if len(duan_dt) < 3:
        return {
            "channel1": None,
            "channel2": None,
            "comparison": {
                "error": "线段数量不足，需要至少3个线段",
                "total_duan": len(duan_dt),
            },
        }

    # 获取时间戳映射
    df_reset = df.reset_index(drop=True)

    def _find_idx_by_timestamp(ts: int) -> int:
        """根据时间戳查找在df中的索引"""
        matches = df_reset[df_reset["time_stamp"] == ts].index
        if len(matches) == 0:
            return None
        return matches[0]

    # ========== 通道1：倒数第2个线段 ==========
    # 获取倒数第2个线段的起止点
    second_last_start_ts = duan_dt[-3]  # 倒数第2个线段起点
    second_last_end_ts = duan_dt[-2]   # 倒数第2个线段终点 = 倒数第1个线段起点

    start_idx_1 = _find_idx_by_timestamp(second_last_start_ts)
    end_idx_1 = _find_idx_by_timestamp(second_last_end_ts)

    if start_idx_1 is None or end_idx_1 is None:
        return {
            "channel1": None,
            "channel2": None,
            "comparison": {"error": "无法定位倒数第2个线段在数据中的位置"},
        }

    # 通道1：只用倒数第2个线段包含的K线范围（不延伸）
    data1 = df.iloc[start_idx_1 : end_idx_1 + 1].copy()  # 注意：包含 end_idx_1
    y1 = _select_price_source(data1, price_source)
    channel1 = _linear_regression_compute(y1, std_multiplier)

    if min_r_squared is not None and channel1["r_squared"] < min_r_squared:
        channel1["is_valid"] = False
        channel1["reason"] = f"拟合优度不足: {channel1['r_squared']:.4f} < {min_r_squared}"

    # 添加通道1的元数据
    channel1["start_idx"] = start_idx_1
    channel1["end_idx"] = end_idx_1  # 通道1只到倒数第2个线段终点
    channel1["bar_count"] = len(data1)
    # 线段方向：duan_dt[-3]对应duan_data[-3]（起点），duan_dt[-2]对应duan_data[-2]（终点）
    channel1["duan_start_price"] = float(duan_data[-3])
    channel1["duan_end_price"] = float(duan_data[-2])
    channel1["duan_direction"] = "up" if duan_data[-2] > duan_data[-3] else "down"

    # ========== 通道2：倒数第1个线段 ==========
    start_idx_2 = end_idx_1  # 倒数第1个线段起点 = 倒数第2个线段终点

    # 通道2：从倒数第1个线段起点 → 现在
    data2 = df.iloc[start_idx_2:].copy()
    y2 = _select_price_source(data2, price_source)
    channel2 = _linear_regression_compute(y2, std_multiplier)

    if min_r_squared is not None and channel2["r_squared"] < min_r_squared:
        channel2["is_valid"] = False
        channel2["reason"] = f"拟合优度不足: {channel2['r_squared']:.4f} < {min_r_squared}"

    # 添加通道2的元数据
    channel2["start_idx"] = start_idx_2
    channel2["end_idx"] = len(df) - 1
    channel2["bar_count"] = len(data2)
    # 线段方向：基于线段本身（duan_data[-2]到duan_data[-1]）
    channel2["duan_start_price"] = float(duan_data[-2])
    channel2["duan_end_price"] = float(duan_data[-1])
    channel2["duan_direction"] = "up" if duan_data[-1] > duan_data[-2] else "down"

    # ========== 两通道对比 ==========
    comparison = {
        "channel1_direction": channel1["duan_direction"],
        "channel2_direction": channel2["duan_direction"],
        "channel1_slope": channel1["slope"],
        "channel2_slope": channel2["slope"],
        "slope_change": channel2["slope"] - channel1["slope"],
        "slope_change_pct": (
            (channel2["slope"] - channel1["slope"]) / abs(channel1["slope"]) * 100
            if channel1["slope"] != 0
            else 0
        ),
        "trend_status": _analyze_trend_status(channel1, channel2),
    }

    return {
        "channel1": channel1,
        "channel2": channel2,
        "comparison": comparison,
    }


def _select_price_source(df: pd.DataFrame, price_source: str) -> np.ndarray:
    """选择价格源"""
    if price_source == "close":
        return df["close"].values
    elif price_source == "hl2":
        return (df["high"] + df["low"]) / 2
    elif price_source == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3
    elif price_source == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    else:
        raise ValueError(f"不支持的价格源: {price_source}")


def _analyze_trend_status(channel1: Dict, channel2: Dict) -> str:
    """分析趋势状态"""
    if not channel1["is_valid"] or not channel2["is_valid"]:
        return "通道无效"

    dir1 = channel1["duan_direction"]
    dir2 = channel2["duan_direction"]

    if dir1 == dir2:
        if dir2 == "up":
            # 都是上升通道
            if channel2["slope"] > channel1["slope"]:
                return "加速上涨"
            else:
                return "减速上涨"
        else:
            # 都是下降通道
            if channel2["slope"] < channel1["slope"]:
                return "加速下跌"
            else:
                return "减速下跌"
    else:
        if dir1 == "up" and dir2 == "down":
            return "转折向下"
        else:
            return "转折向上"


def rolling_linear_regression_channel(
    df: pd.DataFrame,
    period: int = 50,
    price_source: str = "close",
    std_multiplier: float = 2.0,
) -> pd.DataFrame:
    """
    滚动计算线性回归通道（向量化实现）

    适用于：历史数据回测、批量信号生成

    Returns
    -------
    pd.DataFrame with columns: upper, lower, center, r_squared
    """
    # 选择价格源
    if price_source == "close":
        price = df["close"]
    elif price_source == "hl2":
        price = (df["high"] + df["low"]) / 2
    else:
        price = df["close"]

    # 初始化结果数组
    n = len(df)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    center = np.full(n, np.nan)
    r_squared = np.full(n, np.nan)

    # 滚动计算
    for i in range(period - 1, n):
        window = price.iloc[i - period + 1 : i + 1]
        x = np.arange(period)

        # 线性回归
        slope, intercept, r_value, _, _ = linregress(x, window.values)
        regression_line = slope * x + intercept

        # 标准差
        std = np.std(window.values - regression_line, ddof=0)

        # 通道
        upper[i] = regression_line[-1] + std_multiplier * std
        lower[i] = regression_line[-1] - std_multiplier * std
        center[i] = regression_line[-1]
        r_squared[i] = r_value**2

    return pd.DataFrame(
        {"upper": upper, "lower": lower, "center": center, "r_squared": r_squared},
        index=df.index,
    )
