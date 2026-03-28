from datetime import datetime, timedelta
from typing import Dict, List

import pandas as pd
import pymongo
from bson import json_util
from loguru import logger

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.config import settings
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


def _get_legacy_stock_fills_collection():
    return DBfreshquant["stock_fills"]


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


def accStockTrades(acc: List, cur: Dict):
    if "买" in cur["op"]:
        acc = insertStockPosition(acc, json_util.loads(json_util.dumps(cur)))
    elif "卖" in cur["op"]:
        if len(acc) > 0:
            if acc[-1]["quantity"] < cur["quantity"]:
                r = float((cur["quantity"] - acc[-1]["quantity"])) / float(
                    cur["quantity"]
                )
                cur["quantity"] = cur["quantity"] - acc[-1]["quantity"]
                cur["amount"] = cur["amount"] * r
                acc.pop()
                acc = accStockTrades(acc, cur)
            elif acc[-1]["quantity"] == cur["quantity"]:
                acc.pop()
            else:
                r = acc[-1]["quantity"] - cur["quantity"] / float(acc[-1]["quantity"])
                acc[-1]["quantity"] = acc[-1]["quantity"] - cur["quantity"]
                acc[-1]["amount"] = acc[-1]["amount"] * r
    return acc


@in_memory_cache.memoize(expiration=900)
def _compute_atr_last_stock(
    inst_code_base: str, date_str: str, period: int
) -> tuple[float, float]:
    """
    计算 A 股个股在给定周期下的最新 ATR 值，并使用内存缓存避免重复计算。
    """
    from QUANTAXIS.QAFetch.QAQuery_Advance import QA_fetch_stock_day_adv
    from talib import ATR

    dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)
    start_date = (dt - timedelta(days=60)).strftime("%Y-%m-%d")
    end_date = dt.strftime("%Y-%m-%d")
    data = QA_fetch_stock_day_adv(inst_code_base, start_date, end_date)
    data = data.to_qfq().data
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


@in_memory_cache.memoize(expiration=900)
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


def accArrangedStockTrades(acc: List, cur: Dict, lotAmount: int):
    if "买" in cur["op"]:
        if cur["amount"] > lotAmount:
            item = json_util.loads(json_util.dumps(cur))
            quantity = int(lotAmount / item["price"] / 100) * 100
            if quantity == 0:
                quantity = 100
            if quantity == item["quantity"]:
                acc = insertStockPosition(acc, item)
            else:
                item["quantity"] = quantity
                item["amount"] = quantity * item["price"]
                acc = insertStockPosition(acc, item)
                cur["quantity"] = cur["quantity"] - quantity
                cur["amount"] = cur["amount"] - quantity * item["price"]
                code = cur.get("symbol") or cur.get("code")
                date_str = datetime.strptime(str(cur["date"]), "%Y%m%d").strftime(
                    "%Y-%m-%d"
                )
                grid_interval = _query_grid_interval(code, date_str)
                cur["price"] = float("%.2f" % (cur["price"] * grid_interval))
                acc = accArrangedStockTrades(acc, cur, lotAmount)
        else:
            acc = insertStockPosition(acc, json_util.loads(json_util.dumps(cur)))
    elif "卖" in cur["op"]:
        if len(acc) > 0:
            if acc[-1]["quantity"] < cur["quantity"]:
                r = float((cur["quantity"] - acc[-1]["quantity"])) / float(
                    cur["quantity"]
                )
                cur["quantity"] = cur["quantity"] - acc[-1]["quantity"]
                cur["amount"] = cur["amount"] * r
                acc.pop()
                acc = accStockTrades(acc, cur)
            elif acc[-1]["quantity"] == cur["quantity"]:
                acc.pop()
            else:
                r = acc[-1]["quantity"] - cur["quantity"] / float(acc[-1]["quantity"])
                acc[-1]["quantity"] = acc[-1]["quantity"] - cur["quantity"]
                acc[-1]["amount"] = acc[-1]["amount"] * r
    return acc


def get_stock_fill_list(symbol):
    records = _get_order_management_stock_fill_list(symbol)
    if records:
        _compare_with_legacy_fill_list(symbol, records)
        return records
    records = _get_compat_stock_fill_list(symbol)
    if records:
        return records
    if not _allow_legacy_runtime_fallback():
        return None
    return _get_legacy_stock_fill_list(symbol)


def _get_order_management_stock_fill_list(symbol):
    records = list_open_buy_fills(symbol)
    return records or None


def _get_legacy_stock_fill_list(symbol):
    records = (
        DBfreshquant["stock_fills"]
        .find({"symbol": symbol, "quantity": {"$ne": 0}})
        .sort([("date", pymongo.ASCENDING), ("time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        if "amount_adjust" not in df.columns:
            df["amount_adjust"] = 1
        df["amount_adjust"].fillna(1, inplace=True)
        records = df.to_dict("records")
        acc = []
        for record in records:
            acc = accStockTrades(acc, record)
        return acc
    else:
        return None


def _get_compat_stock_fill_list(symbol):
    records = (
        DBfreshquant["stock_fills_compat"]
        .find({"symbol": symbol, "quantity": {"$ne": 0}})
        .sort([("date", pymongo.ASCENDING), ("time", pymongo.ASCENDING)])
    )
    df = pd.DataFrame(records)
    if not df.empty:
        if "amount_adjust" not in df.columns:
            df["amount_adjust"] = 1
        df["amount_adjust"].fillna(1, inplace=True)
        records = df.to_dict("records")
        acc = []
        for record in records:
            acc = accStockTrades(acc, record)
        return acc
    return None


# 查询InstrumentStrategy
def getInstrumentStrategy(instrumentCode: str):
    return DBfreshquant["instrument_strategy"].find_one(
        {
            "instrument_code": instrumentCode,
        }
    )


def get_arranged_stock_fill_list(symbol):
    records = _get_order_management_arranged_fill_list(symbol)
    if records:
        _compare_with_legacy_arranged_fill_list(symbol, records)
        return records
    records = _get_compat_arranged_stock_fill_list(symbol)
    if records:
        return records
    if not _allow_legacy_runtime_fallback():
        return None
    return _get_legacy_arranged_stock_fill_list(symbol)


def _get_order_management_arranged_fill_list(symbol):
    records = list_arranged_fills(symbol)
    return records or None


def _get_legacy_arranged_stock_fill_list(symbol):
    records = list(
        DBfreshquant["stock_fills"]
        .find({"symbol": symbol, "quantity": {"$ne": 0}})
        .sort([("date", pymongo.ASCENDING), ("time", pymongo.ASCENDING)])
    )
    if len(records) > 0:
        stockCode = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
        lotAmount = get_trade_amount(stockCode)
        acc = []
        for record in records:
            acc = accArrangedStockTrades(acc, record, lotAmount)
        return acc
    else:
        return None


def _get_compat_arranged_stock_fill_list(symbol):
    records = list(
        DBfreshquant["stock_fills_compat"]
        .find({"symbol": symbol, "quantity": {"$ne": 0}})
        .sort([("date", pymongo.ASCENDING), ("time", pymongo.ASCENDING)])
    )
    if len(records) > 0:
        stockCode = fq_util_code_append_market_code_suffix(symbol, upper_case=True)
        lotAmount = get_trade_amount(stockCode)
        acc = []
        for record in records:
            acc = accArrangedStockTrades(acc, record, lotAmount)
        return acc
    return None


def _compare_with_legacy_fill_list(symbol, projected_records):
    if not settings.get("order_management", {}).get("enable_dual_read_compare", True):
        return
    legacy_records = _get_compat_stock_fill_list(symbol) or _get_legacy_stock_fill_list(
        symbol
    )
    if legacy_records is None:
        return
    if _normalize_records_for_compare(
        projected_records
    ) != _normalize_records_for_compare(legacy_records):
        logger.warning(
            "order_management open buy fills differ from legacy for {}", symbol
        )


def _compare_with_legacy_arranged_fill_list(symbol, projected_records):
    if not settings.get("order_management", {}).get("enable_dual_read_compare", True):
        return
    legacy_records = _get_compat_arranged_stock_fill_list(
        symbol
    ) or _get_legacy_arranged_stock_fill_list(symbol)
    if legacy_records is None:
        return
    if _normalize_records_for_compare(
        projected_records
    ) != _normalize_records_for_compare(legacy_records):
        logger.warning(
            "order_management arranged fills differ from legacy for {}", symbol
        )


def _allow_legacy_runtime_fallback():
    return bool(
        settings.get("order_management", {}).get(
            "enable_legacy_stock_fill_runtime_fallback", False
        )
    )


def _normalize_records_for_compare(records):
    normalized = []
    for item in records or []:
        normalized.append(
            {
                "date": item.get("date"),
                "time": item.get("time"),
                "price": round(float(item.get("price", 0)), 2),
                "quantity": int(item.get("quantity", 0)),
                "amount": round(float(item.get("amount", 0)), 2),
            }
        )
    return normalized


def get_stock_fills(symbol):
    records = get_stock_fill_list(symbol)
    if records is not None:
        return pd.DataFrame(records)
    else:
        return None


def get_stock_last_fill(symbol):
    records = get_stock_fill_list(symbol)
    if records is not None and len(records) > 0:
        return records[-1]
    else:
        return None


# 查询股票持仓，包括：
# 1. 持仓数量为正
# 2. 持仓金额为负
def get_stock_positions():
    records = _get_xt_position_positions()
    return _enrich_position_names(records)


def _get_legacy_stock_positions():
    records = (
        DBfreshquant["stock_fills"]
        .find({})
        .sort([("date", pymongo.DESCENDING), ("time", pymongo.DESCENDING)])
    )
    df = pd.DataFrame(records)
    if len(df) > 0:
        df.drop(columns=["_id"], inplace=True)
        if "amount_adjust" not in df.columns:
            df["amount_adjust"] = 1
        df["amount_adjust"].fillna(1, inplace=True)
        df["symbol"] = df["symbol"].apply(lambda x: fq_util_code_append_market_code(x))
        df["direction"] = df["op"].apply(lambda op: -1 if "买" in op else 1)
        df["amount"] = df["amount"] * df["direction"]
        df["amount_adjusted"] = df["amount"] * df["amount_adjust"]
        df["quantity"] = df["quantity"] * df["direction"] * -1

        df = df.reset_index(drop=True)

        # 先分组聚合
        grouped = (
            df.groupby(by=["symbol"])
            .agg(
                {
                    "symbol": "first",
                    "stock_code": "first",
                    "name": "first",
                    "quantity": "sum",
                    "amount": "sum",
                    "amount_adjusted": "sum",
                    "date": "last",
                    "time": "last",
                }
            )
            .reset_index(drop=True)
        )
        # 筛选条件：持仓数量>0 且 调整后金额<0
        grouped = grouped[(grouped["amount_adjusted"] < 0) | (grouped["quantity"] > 0)]
        grouped = grouped.sort_values(by=["date", "time"])
        df = df.round({"amount": 2})

        return _enrich_position_names(grouped.to_dict(orient="records"))
    else:
        return []


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

    records = (
        DBfreshquant["stock_fills"]
        .find({"symbol": code})
        .sort([("date", pymongo.DESCENDING), ("time", pymongo.DESCENDING)])
    )
    df = pd.DataFrame(records)
    if len(df) > 0:
        df.drop(columns=["_id"], inplace=True)
        if "amount_adjust" not in df.columns:
            df["amount_adjust"] = 1
        df["amount_adjust"].fillna(1, inplace=True)
        df["symbol"] = df["symbol"].apply(lambda x: fq_util_code_append_market_code(x))
        df["direction"] = df["op"].apply(lambda op: -1 if "买" in op else 1)
        df["amount"] = df["amount"] * df["direction"]
        df["amount_adjusted"] = df["amount"] * df["amount_adjust"]
        df["quantity"] = df["quantity"] * df["direction"] * -1

        # 重置索引以避免分组时的歧义
        df = df.reset_index(drop=True)

        # 先分组聚合
        grouped = (
            df.groupby(by=["symbol"])
            .agg(
                {
                    "symbol": "first",
                    "stock_code": "first",
                    "name": "first",
                    "quantity": "sum",
                    "amount": "sum",
                    "amount_adjusted": "sum",
                    "date": "last",
                    "time": "last",
                }
            )
            .reset_index(drop=True)
        )  # 重置索引以避免歧义

        # 筛选条件：持仓数量>0 且 调整后金额<0
        grouped = grouped[(grouped["amount_adjusted"] < 0) | (grouped["quantity"] > 0)]
        grouped = grouped.sort_values(by=["date", "time"])
        grouped = grouped.round({"amount": 2})

        # 转换为字典并返回单个股票的信息
        result = grouped.to_dict(orient="records")
        if result:
            return result[0]  # 返回第一个匹配的股票信息
    return None


# 清理股票持仓数据
def clean_stock_fills():
    """Deprecated raw legacy cleanup; keep only for manual audit workflows."""
    # 检查当前时间是否在晚上8点之后
    current_time = datetime.now()
    if current_time.hour < 20:  # 20点是晚上8点
        print(
            f"清理操作只能在晚上8点之后执行，当前时间: {current_time.strftime('%H:%M:%S')}"
        )
        return False

    # 在允许的时间范围内执行清理操作
    codes = get_stock_holding_codes()
    _get_legacy_stock_fills_collection().delete_many({"symbol": {"$nin": codes}})
    return True


def compact_stock_fills(code=None):
    """Deprecated raw legacy compaction; prefer stock.fill rebuild for compat maintenance."""
    # 检查当前时间是否在晚上8点之后
    current_time = datetime.now()
    if current_time.hour < 20:  # 20点是晚上8点
        print(
            f"compact_stock_fills只能在晚上8点之后执行，当前时间: {current_time.strftime('%H:%M:%S')}"
        )
        return False
    holding_codes = get_stock_holding_codes()
    if code is not None:
        holding_codes = [c for c in holding_codes if c == code]
    for code in holding_codes:
        position_info = get_stock_hold_position(code)
        if position_info:
            stock_fill_list = list(
                _get_legacy_stock_fills_collection().find({"symbol": code})
            )
            quantity = int(position_info["quantity"])
            amount_adjusted = float(position_info["amount_adjusted"])
            if len(stock_fill_list) > 1 and quantity == 0 and amount_adjusted < 0:
                records = [
                    {
                        "op": "买",
                        "symbol": code,
                        "date": int(datetime.now().strftime("%Y%m%d")),
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "price": 0.0,
                        "amount": -amount_adjusted,
                        "name": position_info["name"],
                        "quantity": 0,
                        "source": "reset",
                        "stock_code": position_info["stock_code"],
                    }
                ]
                existing_records = list(DBfreshquant.stock_fills.find({"symbol": code}))
                if len(existing_records) > 1:
                    audit_record = {
                        "operation": "reset_stock_fills",
                        "symbol": code,
                        "original_records": existing_records,
                        "timestamp": datetime.now(),
                        "record_count": len(existing_records),
                    }
                    DBfreshquant.audit_log.insert_one(audit_record)
                _get_legacy_stock_fills_collection().delete_many({"symbol": code})
                DBfreshquant.stock_fills.insert_many(records)


if __name__ == "__main__":
    # stock_fills = get_stock_fills("002599")
    # print(stock_fills)
    fills = get_arranged_stock_fill_list("000026")
    print(json_util.dumps(fills, indent=4))
    # print(len(fills))
    # print(json_util.dumps(get_stock_positions(), indent=4))
    # print(get_stock_holding_codes())
    # compact_stock_fills()
    # clean_stock_fills()
