# -*- coding: utf-8 -*-

import os
import re
from pathlib import Path

import pandas as pd
import pendulum
import pymongo

import freshquant.util.df_helper as df_helper
from freshquant.bootstrap_config import bootstrap_config
from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.data.astock import must_pool
from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_type
from freshquant.pre_pool_service import PrePoolService
from freshquant.signal.a_stock_common import save_a_stock_pools
from freshquant.strategy.toolkit.grid import plan_grid_distribution
from freshquant.util.code import fq_util_code_append_market_code, normalize_to_base_code


def _format_datetime(value, fmt):
    if hasattr(value, "strftime"):
        return value.strftime(fmt)
    return str(value or "")


def _normalize_page_size(page, size):
    page = max(int(page or 1), 1)
    size = max(int(size or 1000), 1)
    return page, size


TDX_SELF_SELECT_FILENAME = "ZXG.blk"
TDX_SELF_SELECT_CATEGORY = "通达信自选股"
TDX_SELF_SELECT_SOURCE = "tdx_self_select"
TDX_SELF_SELECT_SUPPORTED_INSTRUMENT_TYPES = {
    InstrumentType.STOCK_CN,
    InstrumentType.ETF_CN,
}


def _normalize_stock_code6(value):
    raw = str(value or "").strip()
    code = normalize_to_base_code(raw)
    if re.fullmatch(r"\d{6}", str(code or "")):
        return str(code)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return None


def get_current_stock_holding_codes():
    """Return current xt_positions base codes for stock_pools de-duplication."""
    codes = set()
    for record in DBfreshquant["xt_positions"].find(
        {}, {"stock_code": 1, "code": 1, "symbol": 1}
    ):
        for key in ("symbol", "stock_code", "code"):
            code = _normalize_stock_code6(record.get(key))
            if code:
                codes.add(code)
                break
    return codes


def _require_tdx_home(tdx_home=None):
    value = str(
        tdx_home or bootstrap_config.tdx.home or os.environ.get("TDX_HOME") or ""
    ).strip()
    if not value:
        raise RuntimeError("TDX_HOME not configured")
    return Path(value)


def _tdx_self_select_path(tdx_home=None, filename=TDX_SELF_SELECT_FILENAME):
    return _require_tdx_home(tdx_home) / "T0002" / "blocknew" / filename


def decode_tdx_self_select_code(line):
    """Decode one TDX .blk self-select line into a 6-digit China security code."""
    raw = str(line or "").strip().upper()
    if not raw:
        return None

    compact = re.sub(r"\s+", "", raw)
    if re.fullmatch(r"[012]\d{6}", compact):
        return _decode_tdx_prefixed_code(compact)
    if re.fullmatch(r"\d{6}", compact):
        return compact

    digits = re.sub(r"\D", "", compact)
    if re.fullmatch(r"[012]\d{6}", digits):
        return _decode_tdx_prefixed_code(digits)
    if re.fullmatch(r"\d{6}", digits):
        return digits
    return None


def _decode_tdx_prefixed_code(value):
    market_prefix = value[0]
    code = value[1:]
    if market_prefix == "1":
        return code if code.startswith(("5", "6")) else None
    if market_prefix == "0":
        return code if code.startswith(("0", "2", "3")) else None
    if market_prefix == "2":
        return code if code.startswith(("4", "8", "92")) else None
    return None


def _has_unsupported_tdx_stock_pool_prefix(code):
    value = str(code or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        return True
    if value.startswith(("10", "11", "12", "13", "200", "900")):
        return True
    if value.startswith("1") and not value.startswith(("15", "16", "18")):
        return True
    return False


def _is_supported_tdx_stock_pool_code(code):
    value = str(code or "").strip()
    if _has_unsupported_tdx_stock_pool_prefix(value):
        return False
    try:
        instrument_type = query_instrument_type(value.lower())
    except Exception:
        instrument_type = None
    if instrument_type is None:
        return True
    return instrument_type in TDX_SELF_SELECT_SUPPORTED_INSTRUMENT_TYPES


def read_tdx_self_select_codes(tdx_home=None, filename=TDX_SELF_SELECT_FILENAME):
    path = _tdx_self_select_path(tdx_home=tdx_home, filename=filename)
    if not path.exists():
        raise FileNotFoundError(f"TDX self-select file not found: {path}")

    text = path.read_bytes().decode("gbk", errors="ignore")
    codes = []
    for line in text.splitlines():
        code = decode_tdx_self_select_code(line)
        if code and code not in codes:
            codes.append(code)
    return codes


def sync_stock_pools_from_tdx_self_select(
    days=30,
    *,
    tdx_home=None,
    filename=TDX_SELF_SELECT_FILENAME,
    category=TDX_SELF_SELECT_CATEGORY,
    source=TDX_SELF_SELECT_SOURCE,
):
    """Make freshquant.stock_pools match the current TDX self-select pool."""
    codes = read_tdx_self_select_codes(tdx_home=tdx_home, filename=filename)
    now = pendulum.now()
    expire_at = now.add(days=int(days or 30))
    synced_codes = []
    removed_codes = []
    skipped_holding_codes = []
    skipped_invalid_codes = []
    holding_codes = get_current_stock_holding_codes()

    target_codes = []
    for code in codes:
        if not _is_supported_tdx_stock_pool_code(code):
            skipped_invalid_codes.append(code)
            continue
        if code in holding_codes:
            skipped_holding_codes.append(code)
            continue
        target_codes.append(code)

    target_code_set = set(target_codes)
    existing_docs = list(DBfreshquant["stock_pools"].find({}, {"code": 1}))
    for existing in existing_docs:
        existing_code = _normalize_stock_code6(existing.get("code"))
        if existing_code and existing_code not in target_code_set:
            DBfreshquant["stock_pools"].delete_one({"code": existing_code})
            removed_codes.append(existing_code)

    for code in target_codes:
        existing = DBfreshquant["stock_pools"].find_one({"code": code}) or {}

        membership = {
            "source": source,
            "category": category,
            "added_at": now,
            "expire_at": expire_at,
            "extra": {
                "entrypoint": "tdx_self_select",
                "file_name": filename,
            },
        }
        update = {
            "$set": {
                "code": code,
                "category": category,
                "name": existing.get("name") or code,
                "expire_at": expire_at,
                "datetime": now,
                "sources": [source],
                "categories": [category],
                "memberships": [membership],
                "remark": "tdx_self_select",
                "extra": {
                    "entrypoint": "tdx_self_select",
                    "file_name": filename,
                },
            },
            "$setOnInsert": {
                "stop_loss_price": None,
            },
        }
        DBfreshquant["stock_pools"].update_one(
            {"code": code},
            update,
            upsert=True,
        )
        if DBfreshquant["stock_pools"].find_one({"code": code}) is None:
            skipped_invalid_codes.append(code)
            continue
        synced_codes.append(code)

    return {
        "file_name": filename,
        "file_path": str(_tdx_self_select_path(tdx_home=tdx_home, filename=filename)),
        "category": category,
        "source": source,
        "read_count": len(codes),
        "unique_count": len(codes),
        "appended_count": len(synced_codes),
        "synced_count": len(synced_codes),
        "removed_count": len(removed_codes),
        "skipped_holding_count": len(skipped_holding_codes),
        "skipped_existing_count": 0,
        "skipped_invalid_count": len(skipped_invalid_codes),
        "appended_codes": synced_codes,
        "synced_codes": synced_codes,
        "removed_codes": removed_codes,
        "skipped_holding_codes": skipped_holding_codes,
        "skipped_existing_codes": [],
        "skipped_invalid_codes": skipped_invalid_codes,
    }


def get_stock_signal_list(page=1, size=1000, category="candidates"):
    page, size = _normalize_page_size(page, size)
    cond = {}
    if category == "candidates":
        cond["is_holding"] = False
        cond["position"] = "BUY_LONG"
    elif category == "must_pool_buys":
        cond["is_holding"] = False
        cond["position"] = "BUY_LONG"
    else:
        cond["is_holding"] = True

    if category == "must_pool_buys":
        must_pool_codes = sorted(
            str(doc.get("code") or "")
            for doc in DBfreshquant["must_pool"].find({})
            if doc.get("code")
        )
        if not must_pool_codes:
            data = []
        else:
            data = list(
                DBfreshquant["stock_signals"]
                .find({**cond, "code": {"$in": must_pool_codes}})
                .sort("fire_time", pymongo.DESCENDING)
                .skip((page - 1) * size)
                .limit(size)
            )
    else:
        data = list(
            DBfreshquant["stock_signals"]
            .find(cond)
            .sort("fire_time", pymongo.DESCENDING)
            .skip((page - 1) * size)
            .limit(size)
        )

    out = []
    for doc in data:
        item = dict(doc)
        item.pop("_id", None)
        item["fire_time"] = _format_datetime(doc.get("fire_time"), "%Y-%m-%d %H:%M")
        item["created_at"] = _format_datetime(
            doc.get("created_at") or doc.get("fire_time"), "%Y-%m-%d %H:%M"
        )
        out.append(item)
    return out


def get_stock_model_signal_list(page=1, size=1000):
    page, size = _normalize_page_size(page, size)
    start = (page - 1) * size
    data = list(
        DBfreshquant["realtime_screen_multi_period"]
        .find({})
        .sort([("datetime", pymongo.DESCENDING), ("created_at", pymongo.DESCENDING)])
        .skip(start)
        .limit(size)
    )
    out = []
    for doc in data:
        out.append(
            {
                "datetime": _format_datetime(doc.get("datetime"), "%Y-%m-%d %H:%M"),
                "created_at": _format_datetime(
                    doc.get("created_at"), "%Y-%m-%d %H:%M:%S"
                ),
                "code": doc.get("code") or "",
                "name": doc.get("name") or "",
                "period": doc.get("period") or "",
                "model": doc.get("model") or "",
                "close": doc.get("close"),
                "stop_loss_price": doc.get("stop_loss_price"),
                "source": doc.get("source") or "",
            }
        )
    return out


def get_stock_pools_list(page=1):
    data = list(
        DBfreshquant["stock_pools"]
        .find({})
        .sort("datetime", pymongo.DESCENDING)
        .skip((page - 1) * 1000)
        .limit(1000)
    )
    if len(data) > 0:
        df = pd.DataFrame(data)
        df = df.drop(columns=["_id"])
        df["symbol"] = df["code"].apply(lambda x: fq_util_code_append_market_code(x))
        return df_helper.to_dict(df)
    else:
        return []


def plan_stock_grid_trade(
    ceiling_price: float,
    floor_price: float,
    amount: float,
    quantity: int,
    grid_num: int = 10,
) -> dict:
    """
    计算股票网格交易的价格和数量分布方案。

    Args:
        ceiling_price (float): 网格上限价格
        floor_price (float): 网格下限价格
        amount (float): 计划投入的总金额
        quantity (int): 计划交易的总数量
        grid_num (int, optional): 网格数量，默认为10

    Returns:
        dict: 包含网格交易计划的详细信息：
            - grid_points: 网格点列表，每个点包含price（价格）, quantity（数量）和amount（金额）
            - total: 汇总信息，包含total_quantity和total_amount
    """
    # 生成网格分布方案（股票每手100股）
    df = plan_grid_distribution(
        ceiling_price=ceiling_price,
        floor_price=floor_price,
        amount=amount,
        quantity=quantity,
        grid_num=grid_num,
        lot_shares=100,
    )

    # 转换为API响应格式
    grid_list = []
    for _, row in df.iterrows():
        grid_list.append(
            {
                "price": round(float(row["price"]), 6),
                "quantity": int(row["quantity"]),
                "amount": round(float(row["amount"]), 6),
                "amount_adjust": round(float(row["amount_adjust"]), 6),
                "price_diff": (
                    round(float(row["price_diff"]), 6)
                    if "price_diff" in row and not pd.isna(row["price_diff"])
                    else None
                ),
                "price_percent": (
                    round(float(row["price_percent"]), 6)
                    if "price_percent" in row and not pd.isna(row["price_percent"])
                    else None
                ),
            }
        )

    # 计算实际总计
    total_quantity = int(df["quantity"].sum())
    total_amount = float((df["amount"] * df["amount_adjust"].iloc[0]).sum())

    return {
        "grid_list": grid_list,
        "total": {"quantity": total_quantity, "amount": total_amount},
    }


def get_stock_pre_pools_category():
    category_list = sorted(
        {
            str(category or "").strip()
            for row in PrePoolService(db=DBfreshquant).list_codes()
            for category in row.get("categories") or []
            if category and not re.search("超级赛道", str(category))
        }
    )
    return {"code": 0, "data": category_list}


def get_stock_pre_pools_list(page=1, category=""):
    page, size = _normalize_page_size(page, 1000)
    normalized_category = str(category or "").strip()
    rows = PrePoolService(db=DBfreshquant).list_codes(
        category=normalized_category or None
    )
    start = (page - 1) * size
    data = rows[start : start + size]
    out = []
    for row in data:
        item = dict(row)
        item["symbol"] = fq_util_code_append_market_code(item.get("code"))
        item["datetime"] = _format_datetime(
            item.get("updated_at") or item.get("datetime"), "%Y-%m-%d %H:%M"
        )
        item["created_at"] = _format_datetime(
            item.get("created_at") or item.get("datetime"), "%Y-%m-%d %H:%M"
        )
        item.setdefault("category", next(iter(item.get("categories") or []), ""))
        out.append(item)
    return out


def get_stock_must_pools_list(page=1):
    data = list(
        DBfreshquant["must_pool"]
        .find({})
        .sort("datetime", pymongo.DESCENDING)
        .skip((page - 1) * 1000)
        .limit(1000)
    )
    if len(data) > 0:
        df = pd.DataFrame(data)
        df = df.drop(columns=["_id"])
        df["symbol"] = df["code"].apply(lambda x: fq_util_code_append_market_code(x))
        return df_helper.to_dict(df)
    else:
        return []


def add_to_stock_pools_by_code(
    code,
    days=30,
    allow_direct=False,
    category=None,
    source=None,
    remark=None,
):
    """
    根据code从stock_pre_pools中查找记录，并将其添加到stock_pools中

    Args:
        code: 股票代码

    Returns:
        bool: 操作是否成功
    """
    old = DBfreshquant["stock_pools"].find_one({"code": code})
    record = PrePoolService(db=DBfreshquant).get_code(code)
    if record is None:
        if not allow_direct:
            return False

        now = pendulum.now()
        expire_at = now.add(days=days)
        direct_category = str(category or "CLX15分钟监控").strip() or "CLX15分钟监控"
        direct_source = (
            str(source or "clx_signal_workbench").strip() or "clx_signal_workbench"
        )
        membership_extra = {"entrypoint": "clx_signal_workbench"}
        if remark:
            membership_extra["remark"] = str(remark)
        save_a_stock_pools(
            code=code,
            category=direct_category,
            dt=now,
            stop_loss_price=None,
            expire_at=expire_at,
            sources=[direct_source],
            categories=[direct_category],
            memberships=[
                {
                    "source": direct_source,
                    "category": direct_category,
                    "added_at": now,
                    "expire_at": expire_at,
                    "extra": membership_extra,
                }
            ],
            remark=str(remark or ""),
        )
        DBfreshquant["stock_pools"].update_one(
            {"code": code, "category": direct_category},
            {"$set": {"expire_at": expire_at}},
        )
        return (
            DBfreshquant["stock_pools"].find_one(
                {"code": code, "category": direct_category}
            )
            is not None
        )
    target_category = (
        old.get("category")
        if old is not None
        else record.get("category")
        or next(iter(record.get("categories") or []), "自选股")
    )
    extra = dict(record.get("extra") or {})
    if not extra:
        memberships = list(record.get("memberships") or [])
        if memberships:
            extra = dict((memberships[0].get("extra") or {}))

    save_a_stock_pools(
        code=code,
        category=target_category,
        dt=record.get("updated_at") or record.get("datetime") or pendulum.now(),
        stop_loss_price=record.get("stop_loss_price"),
        expire_at=pendulum.now().add(days=days),
        sources=list(record.get("sources") or []),
        categories=list(record.get("categories") or []),
        memberships=list(record.get("memberships") or []),
        **extra,
    )

    return True


def delete_from_stock_pre_pools_by_code(code):
    """
    根据code从stock_pre_pools中删除记录

    Args:
        code: 股票代码

    Returns:
        bool: 操作是否成功，如果记录不存在也会返回True
    """
    # 从stock_pre_pools中删除记录
    result = DBfreshquant["stock_pre_pools"].delete_one({"code": code})

    # 返回操作是否成功，即使没有匹配的记录也会返回True
    return result.acknowledged


def delete_from_stock_pools_by_code(code):
    """
    根据code从stock_pools中删除记录

    Args:
        code: 股票代码

    Returns:
        bool: 操作是否成功，如果记录不存在也会返回True
    """
    # 从stock_pools中删除记录
    result = DBfreshquant["stock_pools"].delete_one({"code": code})

    # 返回操作是否成功，即使没有匹配的记录也会返回True
    return result.acknowledged


def add_to_must_pool(code, stop_loss_price, initial_lot_amount, lot_amount):
    """
    根据code从stock_pools中插入到must_pool中
    Args:
        code: 股票代码
        lot_amount: 每次买入金额
        category: 分类名称
        stop_loss_price: 止损价格
        initial_lot_amount: 首次买入金额 (可选，默认等于lot_amount)
    Returns:
        bool: 操作是否成功，如果记录不存在也会返回True
    """
    # 从stock_pools中查找记录
    record = DBfreshquant["stock_pools"].find_one({"code": code})
    if record is None:
        return False

    provenance = must_pool.build_stock_pool_provenance(record)

    # 将记录写入must_pool
    must_pool.import_pool(
        code=code,
        category=record.get("category"),
        stop_loss_price=stop_loss_price,
        initial_lot_amount=initial_lot_amount,
        lot_amount=lot_amount,
        forever=True,
        provenance=provenance,
    )
    return True


def delete_from_must_pool_by_code(code):
    """
    根据code从must_pool中删除记录
    Args:
        code: 股票代码
    Returns:
        bool: 操作是否成功，如果记录不存在也会返回True
    """
    # 从must_pool中删除记录
    result = DBfreshquant["must_pool"].delete_one({"code": code})

    # 返回操作是否成功，即使没有匹配的记录也会返回True
    return result.acknowledged


def get_params():
    data = list(DBfreshquant["params"].find({}))
    if len(data) > 0:
        df = pd.DataFrame(data)
        df = df.drop(columns=["_id"])
        return df_helper.to_dict(df)
    else:
        return []


def update_params(name, value):
    """
    更新参数配置

    Args:
        name: 参数名称，不能为空
        value: 参数值，不能为None

    Returns:
        bool: 操作是否成功

    Raises:
        ValueError: 当参数验证失败时抛出异常
    """
    # 参数验证
    if not name or not isinstance(name, str):
        raise ValueError("参数名称不能为空且必须是字符串")

    if name.strip() == "":
        raise ValueError("参数名称不能为空字符串")

    if value is None:
        raise ValueError("参数值不能为None")

    # 参数名称长度限制
    if len(name.strip()) > 100:
        raise ValueError("参数名称长度不能超过100个字符")

    try:
        result = DBfreshquant["params"].update_one(
            {"code": name.strip()}, {"$set": {"value": value}}, upsert=True
        )
        return result.acknowledged
    except Exception as e:
        raise ValueError(f"数据库操作失败: {str(e)}")


def add_to_stock_pools_by_stock(stock):
    """
    根据用户输入的股票信息，插入到stock_pools中

    Args:
        code: 股票代码

    Returns:
        bool: 操作是否成功
    """
    code = stock.get("code")
    if code is None:
        return False
    category = stock.get("category")
    if category is None:
        return False
    stop_loss_price = stock.get("stop_loss_price")
    if stop_loss_price is None:
        return False
    save_a_stock_pools(code=code, category=category, stop_loss_price=stop_loss_price)
    return True
