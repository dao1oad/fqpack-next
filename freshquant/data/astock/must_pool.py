import datetime
from copy import deepcopy

import pyperclip
from bson import ObjectId

from freshquant.db import DBfreshquant
from freshquant.instrument.general import query_instrument_info
from freshquant.strategy.common import get_trade_amount

PRIMARY_SOURCE_PRIORITY = {
    "subject-management": 0,
    "shouban30": 1,
    "daily-screening": 2,
    "stock-pools": 3,
    "stock_pool_legacy": 4,
    "legacy": 5,
    "manual": 6,
}
SHOUBAN30_CATEGORIES = {
    "三十涨停Pro预选",
    "三十涨停Pro自选",
    "三十涨停Pro",
}


def _to_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _deepcopy_dict(value):
    if isinstance(value, dict):
        return deepcopy(value)
    return {}


def _pick_earliest(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return right if right < left else left


def _pick_latest(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return right if right > left else left


def _dedupe_text_list(*groups):
    values = set()
    for group in groups:
        for value in list(group or []):
            text = _to_text(value)
            if text:
                values.add(text)
    return sorted(values)


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
        "extra": _deepcopy_dict(item.get("extra")),
    }


def _merge_memberships(*groups):
    merged = {}
    for group in groups:
        for item in list(group or []):
            normalized = _normalize_membership(item)
            if normalized is None:
                continue
            key = (normalized["source"], normalized["category"])
            existing = merged.get(key)
            if existing is None:
                merged[key] = normalized
                continue
            extra = _deepcopy_dict(existing.get("extra"))
            extra.update(_deepcopy_dict(normalized.get("extra")))
            merged[key] = {
                "source": existing.get("source") or normalized.get("source"),
                "category": existing.get("category") or normalized.get("category"),
                "added_at": _pick_earliest(
                    existing.get("added_at"), normalized.get("added_at")
                ),
                "expire_at": _pick_latest(
                    existing.get("expire_at"), normalized.get("expire_at")
                ),
                "extra": extra,
            }
    return [merged[key] for key in sorted(merged.keys(), key=lambda item: item)]


def _membership_priority(item):
    source = _to_text((item or {}).get("source"))
    category = _to_text((item or {}).get("category"))
    added_at = (item or {}).get("added_at") or datetime.datetime.max
    return (
        PRIMARY_SOURCE_PRIORITY.get(source, 99),
        added_at,
        category,
    )


def _select_primary_membership_category(memberships):
    normalized = _merge_memberships(memberships)
    if not normalized:
        return ""
    return sorted(normalized, key=_membership_priority)[0].get("category") or ""


def _workspace_order_hint(document):
    document = dict(document or {})
    value = document.get("workspace_order_hint")
    if value is None:
        value = document.get("workspace_order")
    if value is None:
        value = _deepcopy_dict(document.get("extra")).get("shouban30_order")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _infer_legacy_source(document):
    document = dict(document or {})
    category = _to_text(document.get("category"))
    remark = _to_text(document.get("remark"))
    extra = _deepcopy_dict(document.get("extra"))
    if not category and not remark and not extra:
        return ""
    if category in SHOUBAN30_CATEGORIES or any(
        str(key).startswith("shouban30_") for key in extra
    ):
        return "shouban30"
    if remark.startswith("daily-screening:"):
        return "daily-screening"
    return "legacy"


def _infer_legacy_category(document):
    document = dict(document or {})
    category = _to_text(document.get("category"))
    extra = _deepcopy_dict(document.get("extra"))
    if category in SHOUBAN30_CATEGORIES or any(
        str(key).startswith("shouban30_") for key in extra
    ):
        plate_key = _to_text(extra.get("shouban30_plate_key"))
        if plate_key:
            return f"plate:{plate_key}"
    return category


def build_legacy_provenance(document=None):
    document = dict(document or {})
    memberships = _merge_memberships(document.get("memberships", []))
    if not memberships:
        source = _infer_legacy_source(document)
        category = _infer_legacy_category(document)
        if source or category:
            memberships = _merge_memberships(
                [
                    {
                        "source": source,
                        "category": category,
                        "added_at": document.get("created_at")
                        or document.get("updated_at")
                        or document.get("datetime"),
                        "expire_at": document.get("expire_at"),
                        "extra": _deepcopy_dict(document.get("extra")),
                    }
                ]
            )

    provenance = merge_provenance(
        {
            "manual_category": document.get("manual_category"),
            "category": document.get("category"),
            "sources": document.get("sources", []),
            "categories": document.get("categories", []),
            "memberships": memberships,
        }
    )
    provenance["workspace_order_hint"] = _workspace_order_hint(document)
    return provenance


def build_stock_pool_provenance(document=None):
    provenance = build_legacy_provenance(document)
    return {
        "sources": provenance.get("sources", []),
        "categories": provenance.get("categories", []),
        "memberships": provenance.get("memberships", []),
        "workspace_order_hint": provenance.get("workspace_order_hint"),
    }


def merge_provenance(existing=None, incoming=None):
    existing = dict(existing or {})
    incoming = dict(incoming or {})
    memberships = _merge_memberships(
        existing.get("memberships", []),
        incoming.get("memberships", []),
    )
    manual_category = _to_text(
        existing.get("manual_category") or incoming.get("manual_category")
    )
    category = manual_category or _select_primary_membership_category(memberships)
    if not category:
        category = _to_text(incoming.get("category") or existing.get("category"))
    return {
        "manual_category": manual_category,
        "sources": _dedupe_text_list(
            existing.get("sources", []),
            incoming.get("sources", []),
            [item.get("source") for item in memberships],
        ),
        "categories": _dedupe_text_list(
            existing.get("categories", []),
            incoming.get("categories", []),
            [item.get("category") for item in memberships],
        ),
        "memberships": memberships,
        "category": category,
    }


def remove(id=None, category=None, codes=None):
    """统一删除方法

    Args:
        id: 记录的唯一标识符
        category: 分类名称
        codes: 股票代码列表
    """
    if id:
        # 根据id删除记录
        DBfreshquant.must_pool.delete_one({"_id": ObjectId(id)})
    elif category and codes:
        # 删除指定category中的指定codes
        DBfreshquant.must_pool.delete_many(
            {"category": category, "code": {"$in": codes}}
        )
    elif category:
        # 删除整个category
        DBfreshquant.must_pool.delete_many({"category": category})
    elif codes:
        # 从所有category中删除指定codes
        DBfreshquant.must_pool.delete_many({"code": {"$in": codes}})
    else:
        raise ValueError("必须提供 category 或 codes 或 id 参数")


def import_pool(
    code: str,
    category: str,
    stop_loss_price: float,
    initial_lot_amount: float = None,
    lot_amount: float = None,
    forever: bool = True,
    provenance: dict | None = None,
):
    """保存股票到must_pool集合

    Args:
        code: 股票代码
        lot_amount: 每次买入金额
        category: 分类名称
        stop_loss_price: 止损价格
        initial_lot_amount: 首次买入金额 (可选，默认等于lot_amount)
    """

    forever = True

    if lot_amount is None:
        lot_amount = get_trade_amount(code)
    if initial_lot_amount is None:
        initial_lot_amount = lot_amount
    if not code or stop_loss_price is None:
        raise ValueError("code, stop_loss_price 参数必须提供")

    # 检查是否已存在相同code和category的记录
    existing = DBfreshquant.must_pool.find_one({"code": code})
    existing_provenance = build_legacy_provenance(existing)
    incoming_provenance = merge_provenance(
        {"category": category},
        provenance or {},
    )
    merged_provenance = merge_provenance(existing_provenance, incoming_provenance)
    workspace_order_hint = (
        dict(provenance or {}).get("workspace_order_hint")
        if dict(provenance or {}).get("workspace_order_hint") is not None
        else existing_provenance.get("workspace_order_hint")
    )
    resolved_category = (
        _to_text(merged_provenance.get("manual_category"))
        or _to_text(category)
        or _to_text(merged_provenance.get("category"))
    )
    if not resolved_category:
        raise ValueError("category 或 provenance.category 参数必须提供")

    instrument = query_instrument_info(code)

    if existing:
        # 更新现有记录
        DBfreshquant.must_pool.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "name": instrument["name"],
                    "instrument_type": instrument["sec"],
                    "initial_lot_amount": initial_lot_amount,
                    "lot_amount": lot_amount,
                    "manual_category": merged_provenance.get("manual_category", ""),
                    "category": resolved_category,
                    "sources": merged_provenance.get("sources", []),
                    "categories": merged_provenance.get("categories", []),
                    "memberships": merged_provenance.get("memberships", []),
                    "workspace_order_hint": workspace_order_hint,
                    "stop_loss_price": stop_loss_price,
                    "forever": forever,
                    "disabled": False,
                    "updated_at": datetime.datetime.now(),
                }
            },
        )
    else:
        # 插入新记录
        DBfreshquant.must_pool.insert_one(
            {
                "code": code,
                "name": instrument["name"],
                "instrument_type": instrument["sec"],
                "initial_lot_amount": initial_lot_amount,
                "lot_amount": lot_amount,
                "manual_category": merged_provenance.get("manual_category", ""),
                "category": resolved_category,
                "sources": merged_provenance.get("sources", []),
                "categories": merged_provenance.get("categories", []),
                "memberships": merged_provenance.get("memberships", []),
                "workspace_order_hint": workspace_order_hint,
                "stop_loss_price": stop_loss_price,
                "forever": forever,
                "disabled": False,
                "created_at": datetime.datetime.now(),
                "updated_at": datetime.datetime.now(),
            }
        )


def copy(category: str):
    # 根据category筛选记录
    query = {"category": category} if category else {}
    codes = DBfreshquant.must_pool.distinct("code", query)

    if not codes:
        return "没有找到任何股票代码"

    # 转换为字符串并用逗号分隔
    code_str = "\n".join(codes)

    # 复制到剪贴板
    pyperclip.copy(code_str)
    return codes
