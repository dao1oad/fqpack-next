from typing import Optional

import pydash

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant


@in_memory_cache.memoize(expiration=900)
def get_trade_amount(instrument_code: Optional[str] = None) -> int:
    """获取交易手数配置，按优先级从多个数据源查找配置"""
    lot_amount: Optional[int] = None

    # 1. 从 instrument_strategy 集合查询
    if instrument_code:
        if strategy := DBfreshquant["instrument_strategy"].find_one(
            {"instrument_code": instrument_code}
        ):
            lot_amount = int(pydash.get(strategy, "lot_amount"))

    # 2. 从 must_pool 集合查询（去除交易所后缀）
    if lot_amount is None and instrument_code:
        code_base = instrument_code.upper().removesuffix(".SH").removesuffix(".SZ")
        if must_pool := DBfreshquant["must_pool"].find_one({"code": code_base}):
            lot_amount = int(pydash.get(must_pool, "lot_amount"))

    # 3. 从 guardian 参数配置获取默认值
    if lot_amount is None:
        if param := DBfreshquant["params"].find_one({"code": "guardian"}):
            # 合并重复的获取逻辑
            lot_amount = int(pydash.get(param["value"], "stock.lot_amount", 1500))

    # 返回最终值或默认值
    return lot_amount or 1000


@in_memory_cache.memoize(expiration=900)
def get_trade_min_amount() -> int:
    """获取最小交易手数配置（直接从guardian参数配置获取）"""
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        return int(pydash.get(param["value"], "stock.min_amount", 1000))
    return 1000


@in_memory_cache.memoize(expiration=900)
def get_position_pct() -> float:
    """获取仓位比例配置（从guardian参数配置获取）"""
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        return float(pydash.get(param["value"], "stock.position_pct", 30.0))
    return 40.0


@in_memory_cache.memoize(expiration=900)
def get_auto_open() -> bool:
    """获取自动开仓配置（从guardian参数配置获取）"""
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        return bool(pydash.get(param["value"], "stock.auto_open", False))
    return False


@in_memory_cache.memoize(expiration=900)
def get_threshold_config(instrument_code: Optional[str] = None) -> dict:
    """获取阈值配置：优先从 instrument_strategy 获取，其次从 guardian 参数获取，最后使用默认值"""
    default = {
        "mode": "percent",
        "percent": 1,
    }
    # 1. 从 instrument_strategy 集合读取（按标的覆盖）
    if instrument_code:
        strategy = DBfreshquant["instrument_strategy"].find_one(
            {"instrument_code": instrument_code}
        )
        if strategy:
            strategy_threshold = pydash.get(strategy, "threshold")
            if isinstance(strategy_threshold, dict) and strategy_threshold:
                return strategy_threshold

    # 2. 回退到 guardian 参数配置
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        return pydash.get(param["value"], "stock.threshold", default)

    # 3. 默认值
    return default


@in_memory_cache.memoize(expiration=900)
def get_grid_interval_config(instrument_code: Optional[str] = None) -> dict:
    """获取网格间隔配置：优先从 instrument_strategy 获取，其次从 guardian 参数获取，最后使用默认值"""
    default = {
        "mode": "percent",
        "percent": 3,
    }
    # 1. 从 instrument_strategy 集合读取（按标的覆盖）
    if instrument_code:
        strategy = DBfreshquant["instrument_strategy"].find_one(
            {"instrument_code": instrument_code}
        )
        if strategy:
            strategy_grid_interval = pydash.get(strategy, "grid_interval")
            if isinstance(strategy_grid_interval, dict) and strategy_grid_interval:
                return strategy_grid_interval

    # 2. 回退到 guardian 参数配置
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        return pydash.get(param["value"], "stock.grid_interval", default)

    # 3. 默认值
    return default


if __name__ == "__main__":
    trade_amount = get_trade_amount("603517.SH")
    print(trade_amount)
    print(get_auto_open())
