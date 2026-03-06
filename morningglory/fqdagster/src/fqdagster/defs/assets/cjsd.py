"""CJSD (超级赛道) assets using Dagster's asset-based approach.

This module defines assets for CJSD calculation with proper dependencies:
- cjsd_index: depends on stock_day and index_day
- cjsd_score: depends on cjsd_index
- cjsd_stock_pool: depends on cjsd_score
"""

import pendulum
from dagster import AssetExecutionContext, asset

from freshquant.research.cjsd.main import (
    apply_cjsd_to_stock_pool,
    calcCjsdScoreAll,
    prepare_cjsd_index,
)


@asset(
    deps=["stock_day", "stock_xdxr", "index_day"],
    group_name="cjsd_data",
)
def cjsd_index(context: AssetExecutionContext) -> str:
    """准备超级赛道指数数据。依赖stock_day和index_day更新。"""
    context.log.info("准备超级赛道指数数据")
    prepare_cjsd_index()
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(
    deps=["cjsd_index"],
    group_name="cjsd_data",
)
def cjsd_score(context: AssetExecutionContext, cjsd_index: str) -> str:
    """计算超级赛道得分。依赖cjsd_index更新。"""
    context.log.info("计算超级赛道得分")
    context.log.info(f"cjsd_index updated at: {cjsd_index}")
    calcCjsdScoreAll()
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")


@asset(
    deps=["cjsd_score"],
    group_name="cjsd_data",
)
def cjsd_stock_pool(context: AssetExecutionContext, cjsd_score: str) -> str:
    """更新股票池超级赛道数据。依赖cjsd_score更新。"""
    context.log.info("更新股票池超级赛道数据")
    context.log.info(f"cjsd_score updated at: {cjsd_score}")
    apply_cjsd_to_stock_pool()
    return pendulum.now().format("YYYY-MM-DD HH:mm:ss")
