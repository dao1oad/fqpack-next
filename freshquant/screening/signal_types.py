# -*- coding: utf-8 -*-
"""缠论信号类型定义

统一的信号类型定义，用于各模块间保持一致
"""

from typing import TypedDict


class SignalInfo(TypedDict):
    """信号信息"""
    name: str      # 信号名称
    direction: str  # 方向 BUY_LONG/SELL_SHORT


# 缠论信号类型映射
CHANLUN_SIGNAL_TYPES: dict[str, SignalInfo] = {
    "buy_zs_huila": {"name": "回拉中枢上涨", "direction": "BUY_LONG"},
    "sell_zs_huila": {"name": "回拉中枢下跌", "direction": "SELL_SHORT"},
    "buy_zs_tupo": {"name": "突破中枢上涨", "direction": "BUY_LONG"},
    "sell_zs_tupo": {"name": "突破中枢下跌", "direction": "SELL_SHORT"},
    "buy_v_reverse": {"name": "V反上涨", "direction": "BUY_LONG"},
    "sell_v_reverse": {"name": "V反下跌", "direction": "SELL_SHORT"},
    "buy_five_v_reverse": {"name": "五浪V反上涨", "direction": "BUY_LONG"},
    "sell_five_v_reverse": {"name": "五浪V反下跌", "direction": "SELL_SHORT"},
    "buy_duan_break": {"name": "线段破坏上涨", "direction": "BUY_LONG"},
    "sell_duan_break": {"name": "线段破坏下跌", "direction": "SELL_SHORT"},
    "macd_bullish_divergence": {"name": "MACD看涨背驰", "direction": "BUY_LONG"},
    "macd_bearish_divergence": {"name": "MACD看跌背驰", "direction": "SELL_SHORT"},
}


def get_signal_name(signal_type: str) -> str:
    """获取信号名称"""
    return CHANLUN_SIGNAL_TYPES.get(signal_type, {}).get("name", signal_type)


def get_signal_direction(signal_type: str) -> str:
    """获取信号方向"""
    return CHANLUN_SIGNAL_TYPES.get(signal_type, {}).get("direction", "BUY_LONG")
