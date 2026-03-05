# -*- coding: utf-8 -*-
"""数据库输出

将选股结果保存到 MongoDB 的 stock_signals、stock_pools、stock_pre_pools 表
"""

from loguru import logger
from typing import Optional

import pendulum

from freshquant.screening.base.strategy import ScreenResult
from freshquant.signal.a_stock_common import (
    save_a_stock_pools,
    save_a_stock_pre_pools,
    save_a_stock_signal,
)


class DatabaseOutput:
    """数据库输出处理器"""

    @staticmethod
    def save_signal(result: ScreenResult, strategy: str = "screening"):
        """保存交易信号到 stock_signals 表

        Args:
            result: 选股结果
            strategy: 策略名称
        """
        try:
            save_a_stock_signal(
                symbol=result.symbol,
                code=result.code,
                period=result.period,
                remark=result.remark or result.signal_type,
                fire_time=result.fire_time,
                price=result.price,
                stop_lose_price=result.stop_loss_price,
                position=result.position,
                tags=result.tags,
                strategy=strategy,
            )
        except Exception as e:
            logger.error(f"保存信号失败 {result.symbol}: {e}")

    @staticmethod
    def save_pools(
        result: ScreenResult,
        expire_days: int = 10,
        category: Optional[str] = None,
    ):
        """保存到股票池 stock_pools 表

        Args:
            result: 选股结果
            expire_days: 过期天数
            category: 分类（默认使用 signal_type）
        """
        try:
            category = category or f"{result.period}_{result.signal_type}"
            expire_at = pendulum.now().add(days=expire_days)

            save_a_stock_pools(
                code=result.code,
                category=category,
                dt=result.fire_time,
                stop_loss_price=result.stop_loss_price,
                expire_at=expire_at,
            )
        except Exception as e:
            logger.error(f"保存股票池失败 {result.symbol}: {e}")

    @staticmethod
    def save_pre_pools(
        result: ScreenResult,
        expire_days: int = 89,
        category: Optional[str] = None,
        **extra_fields,
    ):
        """保存到预选池 stock_pre_pools 表

        Args:
            result: 选股结果
            expire_days: 过期天数
            category: 分类
            **extra_fields: 额外字段
        """
        try:
            category = category or result.signal_type
            expire_at = pendulum.now().add(days=expire_days)

            save_a_stock_pre_pools(
                code=result.code,
                category=category,
                dt=result.fire_time,
                stop_loss_price=result.stop_loss_price,
                expire_at=expire_at,
                **extra_fields,
            )
        except Exception as e:
            logger.error(f"保存预选池失败 {result.symbol}: {e}")

    @classmethod
    def save_all(
        cls,
        results: list[ScreenResult],
        save_signal: bool = True,
        save_pools: bool = False,
        save_pre_pools: bool = False,
        pool_expire_days: int = 10,
        pre_pool_expire_days: int = 89,
    ):
        """批量保存选股结果

        Args:
            results: 选股结果列表
            save_signal: 是否保存到 stock_signals
            save_pools: 是否保存到 stock_pools
            save_pre_pools: 是否保存到 stock_pre_pools
            pool_expire_days: 股票池过期天数
            pre_pool_expire_days: 预选池过期天数
        """
        for result in results:
            if save_signal:
                cls.save_signal(result)
            if save_pools:
                cls.save_pools(result, expire_days=pool_expire_days)
            if save_pre_pools:
                cls.save_pre_pools(result, expire_days=pre_pool_expire_days)

        logger.info(f"保存 {len(results)} 条结果到数据库")
