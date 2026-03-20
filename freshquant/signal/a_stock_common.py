# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

import pendulum

from freshquant.data.astock.basic import fq_fetch_a_stock_category
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.db import DBfreshquant, DBQuantAxis
from freshquant.instrument.general import query_instrument_info
from freshquant.util.datetime_helper import fq_util_datetime_localize


def _to_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_text_list(values):
    return sorted({_to_text(value) for value in list(values or []) if _to_text(value)})


def _normalize_membership(item):
    if not isinstance(item, dict):
        return None
    source = _to_text(item.get("source"))
    category = _to_text(item.get("category"))
    if not source and not category:
        return None
    return {
        "source": source,
        "category": category,
        "added_at": item.get("added_at"),
        "expire_at": item.get("expire_at"),
        "extra": dict(item.get("extra") or {}),
    }


def _merge_memberships(*groups):
    merged = {}
    for group in groups:
        for item in list(group or []):
            normalized = _normalize_membership(item)
            if normalized is None:
                continue
            merged[(normalized["source"], normalized["category"])] = normalized
    return [
        merged[key]
        for key in sorted(merged.keys(), key=lambda item: (item[0], item[1]))
    ]


def save_a_stock_signal(
    symbol,
    code,
    period,
    remark,
    fire_time,
    price,
    stop_lose_price,
    position,
    tags=[],
    strategy=None,
    zsdata=None,
    fills=None,
):
    instrumentOne = query_instrument_info(code)
    category = fq_fetch_a_stock_category(code)
    name = instrumentOne["name"] if instrumentOne is not None else None
    holdings = get_stock_holding_codes()
    x = DBfreshquant["stock_signals"].find_one_and_update(
        {
            "symbol": symbol,
            "code": code,
            "period": period,
            "fire_time": fire_time,
            "position": position,
        },
        {
            "$set": {
                "symbol": symbol,
                "code": code,
                "name": name,
                "period": period,
                "remark": remark,
                "fire_time": fire_time,
                "price": price,
                "stop_lose_price": stop_lose_price,
                "position": position,
                "tags": tags,
                "category": category,
                "strategy": "Guardian",
                "is_holding": code in holdings,
            }
        },
        upsert=True,
    )
    if x is None and fire_time > fq_util_datetime_localize(
        datetime.now() - timedelta(minutes=60)
    ):
        if strategy is not None:
            strategy.on_signal(
                {
                    "symbol": symbol,
                    "code": code,
                    "name": name,
                    "period": period,
                    "fire_time": fire_time,
                    "price": price,
                    "stop_lose_price": stop_lose_price,
                    "position": position,
                    "remark": remark,
                    "tags": tags,
                    "zsdata": zsdata,
                    "fills": fills,
                }
            )


def save_a_stock_factor(sse, symbol, code, dt, factor, value):
    stock_one = DBQuantAxis["stock_list"].find_one({"code": code, "sse": sse})
    name = stock_one["name"] if stock_one is not None else None
    DBfreshquant["stock_factors"].update_one(
        {"symbol": symbol, "code": code, "datetime": dt},
        {
            "$set": {
                "symbol": symbol,
                "code": code,
                "name": name,
                "datetime": dt,
                "updated_at": pendulum.now(),
                factor: value,
            }
        },
        upsert=True,
    )


def save_a_stock_pre_pools(
    code,
    category="",
    dt=pendulum.now(),
    stop_loss_price=None,
    expire_at=pendulum.now().add(days=89),
    remark=None,
    **extra_fields,
):
    dt = pendulum.datetime(dt.year, dt.month, dt.day, tz=pendulum.now().timezone)
    expire_at = pendulum.datetime(
        expire_at.year, expire_at.month, expire_at.day, tz=pendulum.now().timezone
    )
    instrument = query_instrument_info(code)
    if instrument is not None:
        query = {"code": code, "category": category}
        if remark:
            query["remark"] = remark
        else:
            query["$or"] = [
                {"remark": {"$exists": False}},
                {"remark": None},
                {"remark": ""},
            ]

        extra = {}
        existing_doc = DBfreshquant.stock_pre_pools.find_one(query)
        if existing_doc and "extra" in existing_doc:
            extra = existing_doc["extra"]

        extra.update(extra_fields)

        set_fields = {
            "stop_loss_price": stop_loss_price,
            "datetime": dt,
            "expire_at": expire_at,
            "extra": extra,
        }
        if remark:
            set_fields["remark"] = remark

        DBfreshquant.stock_pre_pools.find_one_and_update(
            query,
            {
                "$set": set_fields,
                "$setOnInsert": {
                    "name": instrument["name"],
                },
            },
            upsert=True,
        )


def save_a_stock_pools(
    code,
    category="自选股",
    dt=pendulum.now(),
    stop_loss_price=None,
    expire_at=pendulum.now().add(days=10),
    **extra_fields,
):
    dt = pendulum.datetime(dt.year, dt.month, dt.day, tz=pendulum.now().timezone)
    expire_at = pendulum.datetime(
        expire_at.year, expire_at.month, expire_at.day, tz=pendulum.now().timezone
    )
    instrument = query_instrument_info(code)

    if instrument is None:
        return

    # 查询现有记录（只查询一次）
    existing_doc = DBfreshquant.stock_pools.find_one(
        {"code": code, "category": category}
    )

    incoming_sources = _dedupe_text_list(extra_fields.pop("sources", []))
    incoming_categories = _dedupe_text_list(extra_fields.pop("categories", []))
    incoming_memberships = _merge_memberships(extra_fields.pop("memberships", []))
    if not incoming_sources and incoming_memberships:
        incoming_sources = _dedupe_text_list(
            item.get("source") for item in incoming_memberships
        )
    if not incoming_categories and incoming_memberships:
        incoming_categories = _dedupe_text_list(
            item.get("category") for item in incoming_memberships
        )

    existing_sources = _dedupe_text_list((existing_doc or {}).get("sources", []))
    existing_categories = _dedupe_text_list((existing_doc or {}).get("categories", []))
    existing_memberships = _merge_memberships(
        (existing_doc or {}).get("memberships", [])
    )
    sources = _dedupe_text_list(existing_sources + incoming_sources)
    categories = _dedupe_text_list(existing_categories + incoming_categories)
    memberships = _merge_memberships(existing_memberships, incoming_memberships)

    # 合并 extra 字段
    extra = existing_doc.get("extra", {}) if existing_doc else {}
    extra.update(extra_fields)

    if existing_doc is None:
        # 记录不存在，直接插入
        DBfreshquant.stock_pools.insert_one(
            {
                "code": code,
                "category": category,
                "name": instrument["name"],
                "expire_at": expire_at,
                "datetime": dt,
                "stop_loss_price": stop_loss_price,
                "extra": extra,
                "sources": sources,
                "categories": categories,
                "memberships": memberships,
            }
        )
    else:
        # 记录存在，构建更新操作
        update_ops = {
            "$set": {
                "extra": extra,
                "sources": sources,
                "categories": categories,
                "memberships": memberships,
            }
        }

        # 只有当 stop_loss_price 为空时才更新
        if not existing_doc.get("stop_loss_price"):
            update_ops["$set"]["stop_loss_price"] = stop_loss_price

        DBfreshquant.stock_pools.update_one(
            {"code": code, "category": category}, update_ops
        )


def get_a_stock_pools():
    """获取股票池中的所有有效股票数据

    Returns:
        list: 包含股票信息的列表，每个元素是一个字典，包含code、name、category等信息
    """
    current_time = pendulum.now()
    return list(
        DBfreshquant["stock_pools"].find(
            {"expire_at": {"$gt": current_time}}  # 只返回未过期的股票
        )
    )
