# -*- coding: utf-8 -*-
"""选股模块

提供统一的选股策略框架。

保持包初始化轻量，避免导入子模块时被 `__init__` 递归拉起所有策略实现。
"""

from freshquant.screening.base import ScreenResult, ScreenStrategy

__all__ = [
    "ScreenStrategy",
    "ScreenResult",
    "ChanlunServiceStrategy",
    "ChanlunLaHuiStrategy",
    "ClxsStrategy",
]


def __getattr__(name):
    if name == "ChanlunServiceStrategy":
        from freshquant.screening.strategies.chanlun_service import (
            ChanlunServiceStrategy,
        )

        return ChanlunServiceStrategy
    if name == "ChanlunLaHuiStrategy":
        from freshquant.screening.strategies.chanlun_la_hui import ChanlunLaHuiStrategy

        return ChanlunLaHuiStrategy
    if name == "ClxsStrategy":
        from freshquant.screening.strategies.clxs import ClxsStrategy

        return ClxsStrategy
    raise AttributeError(name)
