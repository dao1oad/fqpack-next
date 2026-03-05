# -*- coding: utf-8 -*-
"""选股策略抽象基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScreenResult:
    """选股结果数据类"""
    code: str                          # 股票代码
    name: str                          # 股票名称
    symbol: str                        # 完整代码（如 sh600000）
    period: str                        # 周期（30m/60m/1d 等）
    fire_time: datetime                # 触发时间
    price: float                       # 触发价格
    stop_loss_price: Optional[float]   # 止损价格
    signal_type: str                   # 信号类型
    tags: list[str] = field(default_factory=list)  # 标签
    position: str = "BUY_LONG"         # 方向（BUY_LONG/SELL_SHORT）
    remark: str = ""                   # 备注
    category: str = ""                 # 分类（来自预选池）


class ScreenStrategy(ABC):
    """选股策略抽象基类

    所有选股策略必须继承此类并实现 screen 方法。
    """

    @abstractmethod
    async def screen(self, **kwargs) -> list[ScreenResult]:
        """执行选股

        Args:
            **kwargs: 策略特定参数

        Returns:
            选股结果列表
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称，用于标识和日志"""
        pass

    def _make_result(
        self,
        code: str,
        name: str,
        symbol: str,
        period: str,
        fire_time: datetime,
        price: float,
        stop_loss_price: Optional[float],
        signal_type: str,
        tags: list[str] | None = None,
        position: str = "BUY_LONG",
        remark: str = "",
        category: str = "",
    ) -> ScreenResult:
        """创建 ScreenResult 的便捷方法"""
        return ScreenResult(
            code=code,
            name=name,
            symbol=symbol,
            period=period,
            fire_time=fire_time,
            price=price,
            stop_loss_price=stop_loss_price,
            signal_type=signal_type,
            tags=tags or [],
            position=position,
            remark=remark,
            category=category,
        )
