# -*- coding: utf-8 -*-
"""
线性回归通道 - 实时更新类

适用于逐tick处理或实时监控场景。
"""

from typing import Dict, List
import numpy as np
from scipy.stats import linregress


class RealTimeLinearRegressionChannel:
    """
    实时更新的线性回归通道

    适用于：逐tick处理或实时监控
    """

    def __init__(self, period: int = 50, std_multiplier: float = 2.0):
        """
        初始化实时通道

        Parameters
        ----------
        period : int
            回溯周期
        std_multiplier : float
            标准差倍数
        """
        self.period = period
        self.std_multiplier = std_multiplier
        self.prices: List[float] = []

    def update(self, price: float) -> Dict[str, float]:
        """
        更新最新价格并计算通道

        Parameters
        ----------
        price : float
            最新价格

        Returns
        -------
        Dict with keys: upper, lower, center, slope, r_squared, is_valid
        """
        self.prices.append(price)

        # 保持固定窗口长度
        if len(self.prices) > self.period:
            self.prices.pop(0)

        # 数据不足
        if len(self.prices) < self.period:
            return {
                "upper": np.nan,
                "lower": np.nan,
                "center": np.nan,
                "slope": np.nan,
                "r_squared": np.nan,
                "is_valid": False,
            }

        x = np.arange(self.period)
        y = np.array(self.prices)

        # 线性回归
        slope, intercept, r_value, _, _ = linregress(x, y)
        regression_line = slope * x + intercept

        # 标准差
        std = np.std(y - regression_line, ddof=0)

        return {
            "upper": regression_line[-1] + self.std_multiplier * std,
            "lower": regression_line[-1] - self.std_multiplier * std,
            "center": regression_line[-1],
            "slope": slope,
            "r_squared": r_value**2,
            "is_valid": True,
        }

    def reset(self) -> None:
        """重置通道状态"""
        self.prices = []
