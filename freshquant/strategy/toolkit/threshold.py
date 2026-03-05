from datetime import datetime, timedelta
from typing import Any, Dict

from QUANTAXIS.QAFetch.QAQuery_Advance import (
    QA_fetch_index_day_adv,
    QA_fetch_stock_day_adv,
)
from talib import ATR

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.database.cache import in_memory_cache
from freshquant.instrument.general import query_instrument_type
from freshquant.strategy.common import get_threshold_config
from freshquant.util.code import (
    normalize_to_base_code,
    normalize_to_inst_code_with_suffix,
)


@in_memory_cache.memoize(expiration=900)
def _compute_atr_last_stock(inst_code_base: str, period: int) -> float:
    """
    计算 A 股个股在给定周期下的最新 ATR 值，并使用内存缓存避免重复计算。
    """
    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data = QA_fetch_stock_day_adv(inst_code_base, start_date, end_date)
    data = data.to_qfq().data
    atr_value = ATR(data.high.values, data.low.values, data.close.values, period)
    return float(atr_value[-1])


@in_memory_cache.memoize(expiration=900)
def _compute_atr_last_index(inst_code_base: str, period: int) -> float:
    """
    计算 A 股指数/ETF 在给定周期下的最新 ATR 值，并使用内存缓存避免重复计算。
    """
    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data = QA_fetch_index_day_adv(inst_code_base, start_date, end_date)
    data = data.data
    atr_value = ATR(data.high.values, data.low.values, data.close.values, period)
    return float(atr_value[-1])


def eval_stock_threshold_price(instument_code: str, price: float) -> Dict[str, Any]:
    """
    计算 A 股股票的上涨卖出阈值价和下跌补仓阈值价。

    参数:
    - instument_code: 股票代码，支持 '002808'/'002808.SZ'/'sz002808' 等格式
    - 配置从 get_threshold_config(标准化代码) 自动获取
        目前支持:
            mode: 'percent'（默认）
            percent: 百分比阈值，默认 1
    - price: 基准价格（当前价）

    返回:
    {
        "instrument_code": "002808.SZ",
        "base_price": 10.23,
        "top_river_price": 10.33,
        "bot_river_price": 10.13,
        "config": {...}
    }
    """
    inst_code_base = normalize_to_base_code(instument_code)
    inst_code_std = normalize_to_inst_code_with_suffix(instument_code)

    # 加载配置
    cfg = get_threshold_config(inst_code_std) or {"mode": "percent", "percent": 1}

    mode = str(cfg.get("mode", "percent")).lower()

    if mode == "percent":
        percent = float(cfg.get("percent", 1))
        top_river_price = round(price * (1 + percent / 100.0), 4)
        bot_river_price = round(price * (1 - percent / 100.0), 4)
    elif mode == "atr":
        period = int(cfg.get("atr", {}).get("period", 20))
        multiplier = float(cfg.get("atr", {}).get("multiplier", 1))
        instrument_type = query_instrument_type(inst_code_base.lower())
        if instrument_type == InstrumentType.STOCK_CN:
            atr_last = _compute_atr_last_stock(inst_code_base, period)
            top_river_price = float(round(price + atr_last * multiplier, 4))
            bot_river_price = float(round(price - atr_last * multiplier, 4))
            percent = float(round(atr_last / price * 100, 2))
        elif instrument_type == InstrumentType.ETF_CN:
            atr_last = _compute_atr_last_index(inst_code_base, period)
            top_river_price = float(round(price + atr_last * multiplier, 4))
            bot_river_price = float(round(price - atr_last * multiplier, 4))
            percent = float(round(atr_last / price * 100, 2))
        else:
            raise NotImplementedError(f"暂不支持 {instrument_type} 的 ATR 阈值计算")
    else:
        raise ValueError(f"无效的 mode: {mode}")

    return {
        "instrument_code": inst_code_std,
        "base_price": price,
        "top_river_price": top_river_price,
        "bot_river_price": bot_river_price,
        "config": {
            "mode": mode,
            "percent": percent,
            **{k: v for k, v in cfg.items() if k not in {"mode", "percent"}},
        },
    }


if __name__ == "__main__":
    print(eval_stock_threshold_price("000026.SZ", 16.7))
