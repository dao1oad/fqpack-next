import os
from datetime import datetime
from importlib import import_module
from pathlib import Path

from freshquant.config import settings
from freshquant.db import DBfreshquant

SHOUBAN30_PRE_POOL_CATEGORY = "三十涨停Pro预选"
SHOUBAN30_STOCK_POOL_CATEGORY = "三十涨停Pro自选"
SHOUBAN30_MUST_POOL_CATEGORY = "三十涨停Pro"
SHOUBAN30_BLK_FILENAME = "30RYZT.blk"
DEFAULT_STOP_LOSS_PRICE = 0.1
DEFAULT_INITIAL_LOT_AMOUNT = 50000
DEFAULT_LOT_AMOUNT = 50000
DEFAULT_FOREVER = True
SHOUBAN30_ORDER_FIELD = "shouban30_order"


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
    return _sorted_workspace_docs(docs, _sort_docs_by_datetime_desc)


def _sorted_stock_pool_docs():
    docs = list(
        DBfreshquant["stock_pools"].find({"category": SHOUBAN30_STOCK_POOL_CATEGORY})
    )
    return _sorted_workspace_docs(docs, _sort_docs_by_datetime_desc)


def _workspace_order(doc):
    value = doc.get("extra", {}).get(SHOUBAN30_ORDER_FIELD)
    if isinstance(value, int) and value >= 0:
        return value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _sort_docs_by_datetime_desc(docs):
    ordered = sorted(docs, key=lambda item: item.get("code", ""))
    return sorted(
        ordered, key=lambda item: item.get("datetime") or datetime.min, reverse=True
    )


def _sorted_workspace_docs(docs, legacy_sorter):
    docs = list(docs)
    if not docs:
        return []
    if not any(_workspace_order(doc) is not None for doc in docs):
        return legacy_sorter(docs)
    return sorted(
        docs,
        key=lambda item: (
            _workspace_order(item) is None,
            _workspace_order(item) if _workspace_order(item) is not None else 10**9,
            item.get("code", ""),
        ),
    )


def _backfill_workspace_orders(collection_name, category, docs):
    docs = list(docs)
    if not docs or all(_workspace_order(doc) is not None for doc in docs):
        return docs

    updated_docs = []
    for index, doc in enumerate(docs):
        DBfreshquant[collection_name].update_one(
            {"code": doc.get("code"), "category": category},
            {"$set": {f"extra.{SHOUBAN30_ORDER_FIELD}": index}},
        )
        next_doc = dict(doc)
        next_extra = dict(next_doc.get("extra") or {})
        next_extra[SHOUBAN30_ORDER_FIELD] = index
        next_doc["extra"] = next_extra
        updated_docs.append(next_doc)
    return updated_docs


def _ensure_pre_pool_orders():
    return _backfill_workspace_orders(
        "stock_pre_pools",
        SHOUBAN30_PRE_POOL_CATEGORY,
        _sorted_pre_pool_docs(),
    )


def _ensure_stock_pool_orders():
    return _backfill_workspace_orders(
        "stock_pools",
        SHOUBAN30_STOCK_POOL_CATEGORY,
        _sorted_stock_pool_docs(),
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


def _settings_get(root, dotted_key):
    current = root
    for part in str(dotted_key).split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
            continue
        current = getattr(current, part, None)
    return current


def _require_tdx_home():
    tdx_home = str(
        _settings_get(settings, "tdx.home") or os.environ.get("TDX_HOME") or ""
    ).strip()
    if not tdx_home:
        raise RuntimeError("TDX_HOME not configured")
    return Path(tdx_home)


def _blk_line_from_code(code6):
    prefix = "1" if str(code6).startswith("6") else "0"
    return f"{prefix}{code6}"


def _write_blk(docs):
    target = _require_tdx_home() / "T0002" / "blocknew" / SHOUBAN30_BLK_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(_blk_line_from_code(doc.get("code")) for doc in docs),
        encoding="gbk",
    )
    return {"success": True, "file_path": str(target), "count": len(docs)}


def _build_pre_pool_doc(item, context):
    now = datetime.now()
    resolved_days = context.get("days")
    if resolved_days is None:
        resolved_days = context.get("stock_window_days")
    resolved_end_date = str(
        context.get("end_date") or context.get("as_of_date") or ""
    ).strip()
    return {
        "code": item["code"],
        "name": item["name"],
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
        "datetime": now,
        "extra": {
            SHOUBAN30_ORDER_FIELD: item["order"],
            "shouban30_provider": item["provider"],
            "shouban30_plate_key": item["plate_key"],
            "shouban30_plate_name": item["plate_name"],
            "shouban30_replace_scope": str(context.get("replace_scope") or "").strip(),
            "shouban30_days": resolved_days,
            "shouban30_end_date": resolved_end_date,
            "shouban30_stock_window_days": resolved_days,
            "shouban30_as_of_date": resolved_end_date,
            "shouban30_selected_filters": list(
                context.get("selected_extra_filters") or []
            ),
            "shouban30_hit_count_window": item["hit_count_window"],
            "shouban30_latest_trade_date": item["latest_trade_date"],
        },
    }


def _build_stock_pool_doc(source_doc, order):
    source_extra = dict(source_doc.get("extra") or {})
    return {
        "code": source_doc.get("code"),
        "name": source_doc.get("name") or source_doc.get("code"),
        "category": SHOUBAN30_STOCK_POOL_CATEGORY,
        "datetime": datetime.now(),
        "extra": {
            SHOUBAN30_ORDER_FIELD: order,
            "shouban30_source": "pre_pool",
            "shouban30_from_category": SHOUBAN30_PRE_POOL_CATEGORY,
            "shouban30_provider": source_extra.get("shouban30_provider"),
            "shouban30_plate_key": source_extra.get("shouban30_plate_key"),
            "shouban30_plate_name": source_extra.get("shouban30_plate_name"),
            "shouban30_hit_count_window": source_extra.get(
                "shouban30_hit_count_window"
            ),
            "shouban30_latest_trade_date": source_extra.get(
                "shouban30_latest_trade_date"
            ),
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


def append_pre_pool(items, context=None):
    context = dict(context or {})
    normalized_items = _normalize_items(items)
    existing_docs = _ensure_pre_pool_orders()
    existing_codes = {doc.get("code") for doc in existing_docs}
    next_order = len(existing_docs)
    appended_count = 0
    skipped_count = 0

    for item in normalized_items:
        if item["code"] in existing_codes:
            skipped_count += 1
            continue
        next_item = dict(item)
        next_item["order"] = next_order
        DBfreshquant["stock_pre_pools"].insert_one(
            _build_pre_pool_doc(next_item, context)
        )
        existing_codes.add(item["code"])
        next_order += 1
        appended_count += 1

    return {
        "appended_count": appended_count,
        "skipped_count": skipped_count,
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
    }


def _clear_pool(collection_name, category, syncer):
    delete_result = DBfreshquant[collection_name].delete_many({"category": category})
    blk_sync = syncer()
    return {
        "deleted_count": delete_result.deleted_count,
        "category": category,
        "blk_sync": blk_sync,
    }


def list_pre_pool():
    return [_serialize_pool_doc(doc) for doc in _sorted_pre_pool_docs()]


def sync_pre_pool_to_blk():
    return _write_blk(_sorted_pre_pool_docs())


def sync_stock_pool_to_blk():
    return _write_blk(_sorted_stock_pool_docs())


def clear_pre_pool():
    return _clear_pool(
        "stock_pre_pools",
        SHOUBAN30_PRE_POOL_CATEGORY,
        sync_pre_pool_to_blk,
    )


def clear_stock_pool():
    return _clear_pool(
        "stock_pools",
        SHOUBAN30_STOCK_POOL_CATEGORY,
        sync_stock_pool_to_blk,
    )


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
    if existing is not None:
        return "already_exists"

    stock_docs = _ensure_stock_pool_orders()
    DBfreshquant["stock_pools"].insert_one(
        _build_stock_pool_doc(source, len(stock_docs))
    )
    return "created"


def sync_pre_pool_to_stock_pool():
    pre_pool_docs = _ensure_pre_pool_orders()
    stock_pool_docs = _ensure_stock_pool_orders()
    existing_codes = {doc.get("code") for doc in stock_pool_docs}
    next_order = len(stock_pool_docs)
    appended_count = 0
    skipped_count = 0

    for source_doc in pre_pool_docs:
        code = source_doc.get("code")
        if code in existing_codes:
            skipped_count += 1
            continue
        DBfreshquant["stock_pools"].insert_one(
            _build_stock_pool_doc(source_doc, next_order)
        )
        existing_codes.add(code)
        next_order += 1
        appended_count += 1

    return {
        "appended_count": appended_count,
        "skipped_count": skipped_count,
        "category": SHOUBAN30_STOCK_POOL_CATEGORY,
    }


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
