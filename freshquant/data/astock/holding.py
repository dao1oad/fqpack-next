from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
from bson import json_util
from loguru import logger

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.data.qfq_reader import apply_qfq_to_bars
from freshquant.database.cache import (
    get_cache_version,
    in_memory_cache,
    redis_cache,
)
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info, query_instrument_type
from freshquant.order_management.projection.cache_invalidator import (
    STOCK_HOLDINGS_CACHE,
)
from freshquant.order_management.projection.stock_fills import (
    list_arranged_fills,
    list_open_buy_fills,
    list_stock_positions,
)
from freshquant.strategy.common import get_grid_interval_config, get_trade_amount
from freshquant.util.code import (
    fq_util_code_append_market_code,
    fq_util_code_append_market_code_suffix,
    normalize_to_base_code,
    normalize_to_inst_code_with_suffix,
)


def _resolve_position_name(position: Dict) -> str:
    raw_name = str(position.get("name") or "").strip()

    symbol = str(position.get("symbol") or "").strip().lower()
    stock_code = str(position.get("stock_code") or "").strip().lower()
    base_code = normalize_to_base_code(symbol or stock_code)
    guessed_symbol = ""
    if base_code:
        if symbol.startswith("sh") or stock_code.endswith(".sh"):
            guessed_symbol = f"sh{base_code}"
        elif symbol.startswith("sz") or stock_code.endswith(".sz"):
            guessed_symbol = f"sz{base_code}"
        else:
            guessed_symbol = (
                f"{'sh' if base_code.startswith(('5', '6', '9')) else 'sz'}{base_code}"
            )
    candidates = []
    for candidate in (
        symbol,
        stock_code,
        stock_code.split(".")[0] if stock_code else "",
        base_code,
        guessed_symbol,
    ):
        candidate = str(candidate or "").strip().lower()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        try:
            instrument = query_instrument_info(candidate)
        except Exception as exc:
            logger.warning(
                "instrument lookup failed while resolving position name for {}: {}",
                candidate,
                exc,
            )
            break
        name = str((instrument or {}).get("name") or "").strip()
        if name:
            return name

    return raw_name


def _enrich_position_names(records: List[Dict]) -> List[Dict]:
    enriched = []
    for item in records or []:
        record = dict(item)
        record["name"] = _resolve_position_name(record)
        enriched.append(record)
    return enriched


def insertStockPosition(acc: List, item: Dict):
    for i in range(len(acc)):
        if acc[i]["price"] < item["price"]:
            acc.insert(i, item)
            break
    else:
        acc.append(item)
    return acc


def _compute_atr_last_stock(
    inst_code_base: str, date_str: str, period: int
) -> tuple[float, float]:
    """
    计算 A 股个股在给定周期下的最新 ATR 值。
    """
    from QUANTAXIS.QAFetch.QAQuery_Advance import QA_fetch_stock_day_adv
    from talib import ATR

    dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    start_date = (dt - timedelta(days=60)).strftime("%Y-%m-%d")
    end_date = dt.strftime("%Y-%m-%d")
    data = QA_fetch_stock_day_adv(inst_code_base, start_date, end_date)
    data, _metadata = apply_qfq_to_bars(
        data.data,
        scope="stock",
        code=inst_code_base,
        date_col="date",
    )
    atr_value = ATR(data.high.values, data.low.values, data.close.values, period)
    return float(atr_value[-1]), float(data.close.values[-1])


@in_memory_cache.memoize(expiration=900)
def _compute_atr_last_index(
    inst_code_base: str, date_str: str, period: int
) -> tuple[float, float]:
    """
    计算 A 股指数/ETF 在给定周期下的最新 ATR 值，并使用内存缓存避免重复计算。
    """
    from QUANTAXIS.QAFetch.QAQuery_Advance import QA_fetch_index_day_adv
    from talib import ATR

    dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    start_date = (dt - timedelta(days=60)).strftime("%Y-%m-%d")
    end_date = dt.strftime("%Y-%m-%d")
    data = QA_fetch_index_day_adv(inst_code_base, start_date, end_date)
    data = data.data
    atr_value = ATR(data.high.values, data.low.values, data.close.values, period)
    return float(atr_value[-1]), float(data.close.values[-1])


def _query_grid_interval(inst_code_base: str, date_str: str) -> float:
    instrument_code = normalize_to_inst_code_with_suffix(inst_code_base)
    cfg = get_grid_interval_config(instrument_code)
    mode = cfg.get("mode", "percent")
    if mode == "percent":
        return 1.0 + float(cfg.get("percent", 3)) / 100
    elif mode == "atr":
        instrument_type = query_instrument_type(inst_code_base.lower())
        period = int(cfg.get("atr", {}).get("period", 20))
        multiplier = float(cfg.get("atr", {}).get("multiplier", 1))
        if instrument_type == InstrumentType.STOCK_CN:
            atr_value, close_price = _compute_atr_last_stock(
                inst_code_base, date_str, period
            )
            return 1.0 + atr_value * multiplier / close_price
        elif instrument_type == InstrumentType.ETF_CN:
            atr_value, close_price = _compute_atr_last_index(
                inst_code_base, date_str, period
            )
            return 1.0 + atr_value * multiplier / close_price

    raise NotImplementedError("invalid mode")


def get_stock_fill_list(symbol):
    return _get_order_management_stock_fill_list(symbol)


def _get_order_management_stock_fill_list(symbol):
    return list_open_buy_fills(symbol)


def get_stock_fills(symbol):
    records = get_stock_fill_list(symbol)
    if records is not None:
        return pd.DataFrame(records)
    return None


def get_stock_last_fill(symbol):
    records = get_stock_fill_list(symbol)
    if records is not None and len(records) > 0:
        return records[-1]
    return None


# 查询InstrumentStrategy
def getInstrumentStrategy(instrumentCode: str):
    return DBfreshquant["instrument_strategy"].find_one(
        {
            "instrument_code": instrumentCode,
        }
    )


def get_arranged_stock_fill_list(symbol):
    return _get_order_management_arranged_fill_list(symbol)


def _get_order_management_arranged_fill_list(symbol):
    return list_arranged_fills(symbol)


def get_stock_positions():
    records = _get_xt_position_positions()
    return _enrich_position_names(records)


def _get_xt_position_positions():
    rows = []
    for item in _load_xt_position_rows():
        base_code = normalize_to_base_code(
            item.get("symbol") or item.get("stock_code") or item.get("code")
        )
        if not base_code:
            continue
        prefixed_symbol = _resolve_xt_position_symbol(item, base_code)
        quantity = int(item.get("volume") or 0)
        market_value = round(float(item.get("market_value") or 0.0), 2)
        rows.append(
            {
                "symbol": prefixed_symbol,
                "stock_code": item.get("stock_code")
                or fq_util_code_append_market_code_suffix(base_code, upper_case=True),
                "name": str(
                    item.get("name") or item.get("instrument_name") or ""
                ).strip(),
                "quantity": quantity,
                "amount": market_value,
                "amount_adjusted": market_value,
                "market_value": market_value,
                "avg_price": item.get("avg_price"),
                "can_use_volume": item.get("can_use_volume"),
                "frozen_volume": item.get("frozen_volume"),
                "source": item.get("source") or "xtquant",
            }
        )
    rows.sort(key=lambda item: item.get("symbol") or "")
    return rows


def _resolve_xt_position_symbol(item, base_code):
    raw_symbol = str(item.get("symbol") or "").strip().lower()
    if raw_symbol.startswith(("sh", "sz", "bj")) and len(raw_symbol) >= 8:
        return raw_symbol

    stock_code = str(item.get("stock_code") or "").strip()
    if "." in stock_code:
        code_part, market = stock_code.split(".", 1)
        normalized_code = normalize_to_base_code(code_part)
        normalized_market = str(market or "").strip().lower()
        if normalized_code and normalized_market in {"sh", "sz", "bj"}:
            return f"{normalized_market}{normalized_code}"

    return fq_util_code_append_market_code(base_code)


# 查询股票持仓，包括：
# 1. 持仓数量为正
# 2. 持仓金额为负
# 只返回6位数的股票代码
def get_stock_holding_codes():
    version = get_cache_version(STOCK_HOLDINGS_CACHE)
    return _get_stock_holding_codes_cached(version)


@redis_cache.memoize(expiration=15)
def _get_stock_holding_codes_cached(_version):
    return sorted(_extract_holding_codes(_get_xt_position_records()))


def _extract_holding_codes(records):
    codes = set()
    for record in records or []:
        raw_code = (
            record.get("symbol") or record.get("stock_code") or record.get("code")
        )
        normalized = normalize_to_base_code(raw_code or "")
        if normalized and len(normalized) == 6 and normalized.isdigit():
            codes.add(normalized)
    return codes


def _get_xt_position_records():
    return list(
        DBfreshquant["xt_positions"].find({}, {"stock_code": 1, "code": 1, "symbol": 1})
    )


def _load_xt_position_rows():
    return list(DBfreshquant["xt_positions"].find({}))


def get_stock_hold_position(code):
    """
    获取单个股票的持仓信息

    Args:
        code (str): 股票代码 (symbol)

    Returns:
        dict: 单个股票的持仓信息，如果未找到则返回None
    """
    current_positions = get_stock_positions()
    for position in current_positions:
        if position["symbol"][2:] == code:
            return position
    return None


# 清理股票持仓数据
if __name__ == "__main__":
    # stock_fills = get_stock_fills("002599")
    # print(stock_fills)
    fills = get_arranged_stock_fill_list("000026")
    print(json_util.dumps(fills, indent=4))
    # print(len(fills))
    # print(json_util.dumps(get_stock_positions(), indent=4))
    # print(get_stock_holding_codes())
