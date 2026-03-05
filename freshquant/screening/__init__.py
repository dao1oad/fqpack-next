# -*- coding: utf-8 -*-
"""选股模块

提供统一的选股策略框架
"""

from freshquant.screening.base import ScreenStrategy, ScreenResult
from freshquant.screening.strategies.chanlun_service import ChanlunServiceStrategy
from freshquant.screening.strategies.chanlun_la_hui import ChanlunLaHuiStrategy
from freshquant.screening.strategies.clxs import ClxsStrategy

__all__ = [
    "ScreenStrategy",
    "ScreenResult",
    "ChanlunServiceStrategy",
    "ChanlunLaHuiStrategy",
    "ClxsStrategy",
]
