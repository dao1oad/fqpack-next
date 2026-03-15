# -*- coding: utf-8 -*-

import re

import pandas as pd
import pendulum
import pymongo

import freshquant.util.df_helper as df_helper
from freshquant.data.astock import must_pool
from freshquant.db import DBfreshquant
from freshquant.signal.a_stock_common import save_a_stock_pools
from freshquant.strategy.toolkit.grid import plan_grid_distribution
from freshquant.util.code import fq_util_code_append_market_code


def _format_datetime(value, fmt):
    if hasattr(value, "strftime"):
        return value.strftime(fmt)
    return str(value or "")


def _normalize_page_size(page, size):
    page = max(int(page or 1), 1)
    size = max(int(size or 1000), 1)
    return page, size


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

    if len(data) > 0:
        df = pd.DataFrame(data)
        df = df.drop(columns=["_id"])
        df["fire_time"] = df["fire_time"].apply(
            lambda x: _format_datetime(x, "%Y-%m-%d %H:%M")
        )
        return df.to_dict("records")
    else:
        return []


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
    category_list = list(
        DBfreshquant["stock_pre_pools"].distinct(
            "category", {"category": {"$not": re.compile("超级赛道")}}
        )
    )
    return {"code": 0, "data": category_list}


def get_stock_pre_pools_list(page=1, category=""):
    query = {}
    normalized_category = str(category or "").strip()
    if normalized_category:
        query["category"] = normalized_category
    data = list(
        DBfreshquant["stock_pre_pools"]
        .find(query)
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


def add_to_stock_pools_by_code(code, days=30):
    """
    根据code从stock_pre_pools中查找记录，并将其添加到stock_pools中

    Args:
        code: 股票代码

    Returns:
        bool: 操作是否成功
    """
    old = DBfreshquant["stock_pools"].find_one({"code": code})
    if old is not None:
        return True

    # 从stock_pre_pools中查找记录
    record = DBfreshquant["stock_pre_pools"].find_one({"code": code})

    if record is None:
        return False

    # 删除_id字段，因为MongoDB会自动生成新的_id
    if "_id" in record:
        del record["_id"]

    record["expire_at"] = pendulum.now().add(days=days)

    # 将记录写入stock_pools
    result = DBfreshquant["stock_pools"].insert_one(record)

    return result.acknowledged


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


def add_to_must_pool(code, stop_loss_price, initial_lot_amount, lot_amount, forever):
    """
    根据code从stock_pools中插入到must_pool中
    Args:
        code: 股票代码
        lot_amount: 每次买入金额
        category: 分类名称
        stop_loss_price: 止损价格
        initial_lot_amount: 首次买入金额 (可选，默认等于lot_amount)
        forever: 买入后是否删除
    Returns:
        bool: 操作是否成功，如果记录不存在也会返回True
    """
    # 从must_pool中查找记录
    old = DBfreshquant["must_pool"].find_one({"code": code})
    if old is not None:
        return True

    # 从stock_pools中查找记录
    record = DBfreshquant["stock_pools"].find_one({"code": code})
    if record is None:
        return False

    # 将记录写入must_pool
    must_pool.import_pool(
        code,
        record.get("category"),
        stop_loss_price,
        initial_lot_amount,
        lot_amount,
        forever,
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
