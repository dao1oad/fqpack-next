import os
from datetime import datetime
from importlib import import_module
from pathlib import Path

from freshquant.db import DBfreshquant

SHOUBAN30_PRE_POOL_CATEGORY = "三十涨停Pro预选"
SHOUBAN30_STOCK_POOL_CATEGORY = "三十涨停Pro自选"
SHOUBAN30_MUST_POOL_CATEGORY = "三十涨停Pro"
SHOUBAN30_BLK_FILENAME = "30RYZT.blk"
DEFAULT_STOP_LOSS_PRICE = 0.1
DEFAULT_INITIAL_LOT_AMOUNT = 50000
DEFAULT_LOT_AMOUNT = 50000
DEFAULT_FOREVER = True


def _normalize_code6(value):
    code6 = str(value or "").strip()
    if len(code6) != 6 or not code6.isdigit():
        raise ValueError("invalid code6")
    return code6


def _normalize_items(items):
    if not isinstance(items, list) or not items:
        raise ValueError("items required")
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("items must be a list of dict")
        code6 = _normalize_code6(item.get("code6") or item.get("code"))
        normalized.append(
            {
                "order": index,
                "code": code6,
                "name": str(item.get("name") or "").strip() or code6,
                "plate_key": str(item.get("plate_key") or "").strip(),
                "plate_name": str(item.get("plate_name") or "").strip(),
                "provider": str(item.get("provider") or "").strip(),
                "hit_count_window": item.get("hit_count_window"),
                "latest_trade_date": str(item.get("latest_trade_date") or "").strip(),
            }
        )
    return normalized


def _sorted_pre_pool_docs():
    docs = list(
        DBfreshquant["stock_pre_pools"].find({"category": SHOUBAN30_PRE_POOL_CATEGORY})
    )
    return sorted(
        docs,
        key=lambda item: (
            item.get("extra", {}).get("shouban30_order", 0),
            item.get("code", ""),
        ),
    )


def _sorted_stock_pool_docs():
    docs = list(
        DBfreshquant["stock_pools"].find({"category": SHOUBAN30_STOCK_POOL_CATEGORY})
    )
    return sorted(
        docs,
        key=lambda item: (item.get("datetime") or datetime.min, item.get("code", "")),
        reverse=True,
    )


def _serialize_pool_doc(doc):
    extra = dict(doc.get("extra") or {})
    return {
        "code": doc.get("code"),
        "code6": doc.get("code"),
        "name": doc.get("name"),
        "category": doc.get("category"),
        "datetime": doc.get("datetime"),
        "expire_at": doc.get("expire_at"),
        "extra": extra,
    }


def _require_tdx_home():
    tdx_home = str(os.environ.get("TDX_HOME") or "").strip()
    if not tdx_home:
        raise RuntimeError("TDX_HOME not configured")
    return Path(tdx_home)


def _blk_line_from_code(code6):
    prefix = "1" if str(code6).startswith("6") else "0"
    return f"{prefix}{code6}"


def _build_pre_pool_doc(item, context):
    now = datetime.now()
    return {
        "code": item["code"],
        "name": item["name"],
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
        "datetime": now,
        "extra": {
            "shouban30_order": item["order"],
            "shouban30_provider": item["provider"],
            "shouban30_plate_key": item["plate_key"],
            "shouban30_plate_name": item["plate_name"],
            "shouban30_replace_scope": str(context.get("replace_scope") or "").strip(),
            "shouban30_stock_window_days": context.get("stock_window_days"),
            "shouban30_as_of_date": str(context.get("as_of_date") or "").strip(),
            "shouban30_selected_filters": list(
                context.get("selected_extra_filters") or []
            ),
            "shouban30_hit_count_window": item["hit_count_window"],
            "shouban30_latest_trade_date": item["latest_trade_date"],
        },
    }


def replace_pre_pool(items, context=None):
    context = dict(context or {})
    normalized_items = _normalize_items(items)
    delete_result = DBfreshquant["stock_pre_pools"].delete_many(
        {"category": SHOUBAN30_PRE_POOL_CATEGORY}
    )
    for item in normalized_items:
        DBfreshquant["stock_pre_pools"].insert_one(_build_pre_pool_doc(item, context))
    blk_sync = sync_pre_pool_to_blk()
    return {
        "saved_count": len(normalized_items),
        "deleted_count": delete_result.deleted_count,
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
        "blk_sync": blk_sync,
    }


def list_pre_pool():
    return [_serialize_pool_doc(doc) for doc in _sorted_pre_pool_docs()]


def sync_pre_pool_to_blk():
    target = _require_tdx_home() / "T0002" / "blocknew" / SHOUBAN30_BLK_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    docs = _sorted_pre_pool_docs()
    target.write_text(
        "\n".join(_blk_line_from_code(doc.get("code")) for doc in docs),
        encoding="gbk",
    )
    return {"success": True, "file_path": str(target), "count": len(docs)}


def add_pre_pool_item_to_stock_pool(code6):
    code6 = _normalize_code6(code6)
    source = DBfreshquant["stock_pre_pools"].find_one(
        {"code": code6, "category": SHOUBAN30_PRE_POOL_CATEGORY}
    )
    if source is None:
        raise ValueError("pre_pool item not found")

    existing = DBfreshquant["stock_pools"].find_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    target_doc = {
        "code": code6,
        "name": source.get("name") or code6,
        "category": SHOUBAN30_STOCK_POOL_CATEGORY,
        "datetime": datetime.now(),
        "extra": {
            "shouban30_source": "pre_pool",
            "shouban30_from_category": SHOUBAN30_PRE_POOL_CATEGORY,
            "shouban30_provider": source.get("extra", {}).get("shouban30_provider"),
            "shouban30_plate_key": source.get("extra", {}).get("shouban30_plate_key"),
        },
    }
    if existing is None:
        DBfreshquant["stock_pools"].insert_one(target_doc)
        return "created"
    if (
        existing.get("name") == target_doc["name"]
        and existing.get("extra") == target_doc["extra"]
    ):
        return "already_exists"
    DBfreshquant["stock_pools"].update_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY},
        {"$set": {"name": target_doc["name"], "extra": target_doc["extra"]}},
    )
    return "updated"


def delete_pre_pool_item(code6):
    code6 = _normalize_code6(code6)
    deleted = DBfreshquant["stock_pre_pools"].delete_one(
        {"code": code6, "category": SHOUBAN30_PRE_POOL_CATEGORY}
    )
    blk_sync = sync_pre_pool_to_blk()
    return {"deleted": deleted.deleted_count > 0, "blk_sync": blk_sync}


def list_stock_pool():
    return [_serialize_pool_doc(doc) for doc in _sorted_stock_pool_docs()]


def add_stock_pool_item_to_must_pool(code6):
    code6 = _normalize_code6(code6)
    record = DBfreshquant["stock_pools"].find_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    if record is None:
        raise ValueError("stock_pool item not found")
    existing = DBfreshquant["must_pool"].find_one({"code": code6})
    import_module("freshquant.data.astock.must_pool").import_pool(
        code6,
        SHOUBAN30_MUST_POOL_CATEGORY,
        DEFAULT_STOP_LOSS_PRICE,
        DEFAULT_INITIAL_LOT_AMOUNT,
        DEFAULT_LOT_AMOUNT,
        DEFAULT_FOREVER,
    )
    return "created" if existing is None else "updated"


def delete_stock_pool_item(code6):
    code6 = _normalize_code6(code6)
    deleted = DBfreshquant["stock_pools"].delete_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    return {"deleted": deleted.deleted_count > 0}
