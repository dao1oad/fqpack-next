# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.db import DBQuantAxis, DBfreshquant

COL_QUALITY_STOCK_UNIVERSE = "quality_stock_universe"
QUALITY_STOCK_SOURCE_VERSION = "xgt_hot_blocks_v1"
QUALITY_STOCK_BLOCK_NAMES = (
    "活跃ETF",
    "宽基ETF",
    "上证50",
    "“中证央企”",
    "沪深300",
    "证金汇金",
    "昨成交20",
    "养老金",
    "社保重仓",
    "社保新进",
    "大基金",
    "基金重仓",
    "基金增仓",
    "基金独门",
    "券商重仓",
    "券商金股",
    "高股息股",
    "高分红股",
    "自由现金",
    "绩优股",
    "行业龙头",
)


def refresh_quality_stock_universe(
    *,
    block_collection=None,
    target_collection=None,
    now_provider=None,
):
    block_collection = block_collection or DBQuantAxis["stock_block"]
    target_collection = target_collection or DBfreshquant[COL_QUALITY_STOCK_UNIVERSE]
    now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    updated_at = now_provider().isoformat()
    target_collection.create_index("code6", unique=True, name="uniq_quality_code6")

    block_lookup = {}
    rows = block_collection.find({"blockname": {"$in": list(QUALITY_STOCK_BLOCK_NAMES)}})
    for row in rows or []:
        code6 = _normalize_code6(row.get("code"))
        if not code6:
            continue
        block_name = str(row.get("blockname") or "").strip()
        if not block_name:
            continue
        block_lookup.setdefault(code6, set()).add(block_name)

    documents = []
    for code6 in sorted(block_lookup):
        block_names = [
            block_name
            for block_name in QUALITY_STOCK_BLOCK_NAMES
            if block_name in block_lookup[code6]
        ]
        documents.append(
            {
                "code6": code6,
                "block_names": block_names,
                "source_version": QUALITY_STOCK_SOURCE_VERSION,
                "updated_at": updated_at,
            }
        )

    target_collection.delete_many({})
    if documents:
        target_collection.insert_many(documents, ordered=False)

    return {
        "count": len(documents),
        "source_version": QUALITY_STOCK_SOURCE_VERSION,
        "updated_at": updated_at,
    }


def load_quality_stock_lookup(*, target_collection=None):
    target_collection = target_collection or DBfreshquant[COL_QUALITY_STOCK_UNIVERSE]
    return {
        _normalize_code6(item.get("code6")): dict(item)
        for item in (target_collection.find({}) or [])
        if _normalize_code6(item.get("code6"))
    }


def _normalize_code6(value):
    digits = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if not digits:
        return None
    return digits[-6:].zfill(6)
