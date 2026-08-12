import math
from typing import Optional

import pydash
from loguru import logger

from freshquant.database.cache import in_memory_cache
from freshquant.db import DBfreshquant


def _code_base(instrument_code: Optional[str]) -> Optional[str]:
    if not instrument_code:
        return None
    return instrument_code.upper().removesuffix(".SH").removesuffix(".SZ")


def _coerce_int(value, *, default=None):
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_guardian_config_value(
    instrument_code: Optional[str],
    *,
    strategy_key: str,
    must_pool_key: Optional[str] = None,
    params_path: Optional[str] = None,
):
    """共享参数解析链：``instrument_strategy`` → ``must_pool`` → ``params``。

    返回解析链上第一个非空值；全部缺失时返回 ``None``。供
    ``get_trade_amount`` / ``get_threshold_config`` /
    ``get_grid_interval_config`` / ``get_min_buy_amount`` 复用，避免第 4 份
    拷贝，并修正“字段缺失即 ``int(None)`` TypeError”的旧模式。
    """

    if instrument_code:
        strategy = DBfreshquant["instrument_strategy"].find_one(
            {"instrument_code": instrument_code}
        )
        if strategy is not None:
            value = pydash.get(strategy, strategy_key)
            if value is not None:
                return value
    code_base = _code_base(instrument_code)
    if code_base:
        if must_pool := DBfreshquant["must_pool"].find_one({"code": code_base}):
            value = pydash.get(must_pool, must_pool_key) if must_pool_key else None
            if value is not None:
                return value
    if param := DBfreshquant["params"].find_one({"code": "guardian"}):
        value = pydash.get(param["value"], params_path) if params_path else None
        if value is not None:
            return value
    return None


@in_memory_cache.memoize(expiration=900)
def get_trade_amount(instrument_code: Optional[str] = None) -> int:
    """获取交易手数配置，按优先级从多个数据源查找配置"""
    lot_amount = _resolve_guardian_config_value(
        instrument_code,
        strategy_key="lot_amount",
        must_pool_key="lot_amount",
        params_path="stock.lot_amount",
    )
    lot_amount = _coerce_int(lot_amount)
    return lot_amount or 50000


@in_memory_cache.memoize(expiration=900)
def get_threshold_config(instrument_code: Optional[str] = None) -> dict:
    """获取阈值配置：优先从 instrument_strategy 获取，其次从 guardian 参数获取，最后使用默认值"""
    default = {
        "mode": "percent",
        "percent": 1,
    }
    value = _resolve_guardian_config_value(
        instrument_code,
        strategy_key="threshold",
        params_path="stock.threshold",
    )
    if isinstance(value, dict) and value:
        return value
    return default


@in_memory_cache.memoize(expiration=900)
def get_grid_interval_config(instrument_code: Optional[str] = None) -> dict:
    """获取网格间隔配置：优先从 instrument_strategy 获取，其次从 guardian 参数获取，最后使用默认值"""
    default = {
        "mode": "percent",
        "percent": 3,
    }
    value = _resolve_guardian_config_value(
        instrument_code,
        strategy_key="grid_interval",
        params_path="stock.grid_interval",
    )
    if isinstance(value, dict) and value:
        return value
    return default


@in_memory_cache.memoize(expiration=900)
def get_min_buy_amount(instrument_code: Optional[str] = None) -> int:
    """新增全局最小买入金额（#549）：所有买入路径通用门槛。

    来源：``params.guardian.stock.min_buy_amount``（允许 instrument_strategy
    按标的覆盖），默认 10000、下限钳制 10000。``B < min_buy_amount`` 不买
    （不消耗冷却）；只约束取整前 B。
    """

    value = _resolve_guardian_config_value(
        instrument_code,
        strategy_key="min_buy_amount",
        params_path="stock.min_buy_amount",
    )
    parsed = _coerce_int(value)
    if parsed is None:
        parsed = 10000
    return max(parsed, 10000)


@in_memory_cache.memoize(expiration=900)
def get_buy_amount_exponent() -> float:
    """全局做T买入金额指数（#578）：``B = R × t^n``。

    解析链只走全局 ``params.guardian.stock.buy_amount_exponent``（不传
    instrument_code，避免产生标的级覆盖入口）；默认 2.0；读侧非法/越界
    [1.0, 5.0] 回退 2.0 并告警（fail-safe 到现状），写侧由
    ``SystemConfigService._normalize_settings_values`` 校验。
    """

    value = _resolve_guardian_config_value(
        None,
        strategy_key="buy_amount_exponent",
        params_path="stock.buy_amount_exponent",
    )
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 2.0
    if not math.isfinite(parsed) or parsed < 1.0 or parsed > 5.0:
        logger.warning(
            "params.guardian.stock.buy_amount_exponent 非法（{}），回退 2.0",
            value,
        )
        return 2.0
    return parsed


if __name__ == "__main__":
    trade_amount = get_trade_amount("603517.SH")
    print(trade_amount)
