import os
from datetime import datetime
from importlib import import_module
from pathlib import Path

from freshquant.bootstrap_config import bootstrap_config
from freshquant.db import DBfreshquant
from freshquant.pre_pool_service import PrePoolService

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
    value = doc.get("workspace_order")
    if isinstance(value, int) and value >= 0:
        return value
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and parsed >= 0:
        return parsed
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


def _next_workspace_order(docs):
    return (
        max(
            (
                _workspace_order(doc)
                for doc in docs
                if _workspace_order(doc) is not None
            ),
            default=-1,
        )
        + 1
    )


def _dedupe_text_list(*groups):
    values = set()
    for group in groups:
        for value in list(group or []):
            text = str(value or "").strip()
            if text:
                values.add(text)
    return sorted(values)


def _normalize_membership(item):
    if not isinstance(item, dict):
        return None
    source = str(item.get("source") or "").strip()
    category = str(item.get("category") or "").strip()
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


def _merged_stock_pool_provenance(source_doc, existing_doc=None):
    memberships = _merge_memberships(
        (existing_doc or {}).get("memberships", []),
        source_doc.get("memberships", []),
    )
    sources = _dedupe_text_list(
        (existing_doc or {}).get("sources", []),
        source_doc.get("sources", []),
        [item.get("source") for item in memberships],
    )
    categories = _dedupe_text_list(
        (existing_doc or {}).get("categories", []),
        source_doc.get("categories", []),
        [item.get("category") for item in memberships],
    )
    return {
        "sources": sources,
        "categories": categories,
        "memberships": memberships,
    }


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
        "sources": list(doc.get("sources") or []),
        "categories": list(doc.get("categories") or []),
        "memberships": list(doc.get("memberships") or []),
        "workspace_order": _workspace_order(doc),
    }


def _pre_pool_service():
    return PrePoolService(db=DBfreshquant)


def _shouban30_membership_category(item):
    plate_key = str(
        item.get("plate_key")
        or (item.get("extra") or {}).get("shouban30_plate_key")
        or ""
    ).strip()
    if plate_key:
        return f"plate:{plate_key}"
    return SHOUBAN30_PRE_POOL_CATEGORY


def _select_pre_pool_membership(doc, *, preferred_source=None):
    memberships = list(doc.get("memberships") or [])
    if preferred_source:
        preferred = [
            item
            for item in memberships
            if str(item.get("source") or "").strip() == str(preferred_source).strip()
        ]
        if preferred:
            memberships = preferred
    if not memberships:
        return {}
    return sorted(
        memberships,
        key=lambda item: (
            _workspace_order({"extra": item.get("extra") or {}}) is None,
            (
                _workspace_order({"extra": item.get("extra") or {}})
                if _workspace_order({"extra": item.get("extra") or {}}) is not None
                else 10**9
            ),
            item.get("added_at") or datetime.min,
            str(item.get("category") or ""),
        ),
    )[0]


def _serialize_pre_pool_doc(doc):
    primary = _select_pre_pool_membership(doc, preferred_source="shouban30")
    extra = dict(primary.get("extra") or {})
    if (
        doc.get("workspace_order") is not None
        and extra.get(SHOUBAN30_ORDER_FIELD) is None
    ):
        extra[SHOUBAN30_ORDER_FIELD] = doc.get("workspace_order")
    category = (
        SHOUBAN30_PRE_POOL_CATEGORY
        if "shouban30" in set(doc.get("sources") or [])
        else next(iter(doc.get("categories") or []), "")
    )
    return {
        "code": doc.get("code"),
        "code6": doc.get("code"),
        "name": doc.get("name"),
        "category": category,
        "datetime": doc.get("updated_at") or doc.get("datetime"),
        "expire_at": doc.get("expire_at"),
        "extra": extra,
        "sources": list(doc.get("sources") or []),
        "categories": list(doc.get("categories") or []),
        "memberships": list(doc.get("memberships") or []),
        "workspace_order": doc.get("workspace_order"),
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
        bootstrap_config.tdx.home or os.environ.get("TDX_HOME") or ""
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


def _upsert_pre_pool_item(pre_pool_service, item, context, *, order):
    next_item = dict(item)
    next_item["order"] = order
    compat_doc = _build_pre_pool_doc(next_item, context)
    pre_pool_service.upsert_code(
        code=next_item["code"],
        name=next_item["name"],
        source="shouban30",
        category=_shouban30_membership_category(next_item),
        added_at=compat_doc["datetime"],
        stop_loss_price=None,
        source_remark="shouban30",
        row_category=SHOUBAN30_PRE_POOL_CATEGORY,
        row_extra=compat_doc["extra"],
        extra=compat_doc["extra"],
        workspace_order=order,
    )


def _safe_sync_pre_pool_to_blk():
    try:
        return sync_pre_pool_to_blk()
    except RuntimeError as exc:
        return {"success": False, "message": str(exc)}


def _build_stock_pool_doc(source_doc, order):
    return _build_stock_pool_doc_from_source(source_doc, order)


def _build_stock_pool_doc_from_source(source_doc, order, existing_doc=None):
    source_extra = dict(source_doc.get("extra") or {})
    existing_extra = dict((existing_doc or {}).get("extra") or {})
    extra = dict(existing_extra)
    extra[SHOUBAN30_ORDER_FIELD] = (
        _workspace_order(existing_doc)
        if existing_doc is not None and _workspace_order(existing_doc) is not None
        else order
    )
    extra["shouban30_source"] = "pre_pool"
    extra["shouban30_from_category"] = SHOUBAN30_PRE_POOL_CATEGORY
    for key in (
        "shouban30_provider",
        "shouban30_plate_key",
        "shouban30_plate_name",
        "shouban30_hit_count_window",
        "shouban30_latest_trade_date",
    ):
        value = source_extra.get(key)
        if value not in (None, ""):
            extra[key] = value
    provenance = _merged_stock_pool_provenance(source_doc, existing_doc)
    return {
        "code": source_doc.get("code"),
        "name": (existing_doc or {}).get("name")
        or source_doc.get("name")
        or source_doc.get("code"),
        "category": SHOUBAN30_STOCK_POOL_CATEGORY,
        "datetime": (existing_doc or {}).get("datetime") or datetime.now(),
        "expire_at": (existing_doc or {}).get("expire_at")
        or source_doc.get("expire_at"),
        "stop_loss_price": (existing_doc or {}).get("stop_loss_price")
        or source_doc.get("stop_loss_price"),
        "extra": extra,
        "sources": provenance["sources"],
        "categories": provenance["categories"],
        "memberships": provenance["memberships"],
    }


def replace_pre_pool(items, context=None):
    context = dict(context or {})
    normalized_items = _normalize_items(items)
    pre_pool_service = _pre_pool_service()
    incoming_memberships = {
        (item["code"], _shouban30_membership_category(item))
        for item in normalized_items
    }
    deleted_count = 0
    for doc in pre_pool_service.list_codes(source="shouban30"):
        for membership in list(doc.get("memberships") or []):
            if str(membership.get("source") or "").strip() != "shouban30":
                continue
            membership_key = (doc.get("code"), membership.get("category"))
            if membership_key in incoming_memberships:
                continue
            if pre_pool_service.remove_membership(
                code=doc.get("code"),
                source="shouban30",
                category=membership.get("category"),
            ):
                deleted_count += 1
    for index, item in enumerate(normalized_items):
        _upsert_pre_pool_item(pre_pool_service, item, context, order=index)
    blk_sync = _safe_sync_pre_pool_to_blk()
    return {
        "saved_count": len(normalized_items),
        "deleted_count": deleted_count,
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
        "blk_sync": blk_sync,
    }


def append_pre_pool(items, context=None):
    context = dict(context or {})
    normalized_items = _normalize_items(items)
    pre_pool_service = _pre_pool_service()
    existing_docs = pre_pool_service.list_codes()
    existing_memberships = {
        (doc.get("code"), membership.get("category"))
        for doc in pre_pool_service.list_codes(source="shouban30")
        for membership in list(doc.get("memberships") or [])
        if str(membership.get("source") or "").strip() == "shouban30"
    }
    next_order = _next_workspace_order(existing_docs)
    appended_count = 0
    skipped_count = 0

    for item in normalized_items:
        membership_key = (item["code"], _shouban30_membership_category(item))
        if membership_key in existing_memberships:
            skipped_count += 1
            continue
        existing_doc = pre_pool_service.get_code(item["code"])
        assigned_order = (
            _workspace_order(existing_doc)
            if existing_doc is not None and _workspace_order(existing_doc) is not None
            else next_order
        )
        _upsert_pre_pool_item(pre_pool_service, item, context, order=assigned_order)
        existing_memberships.add(membership_key)
        if assigned_order == next_order:
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
    return [_serialize_pre_pool_doc(doc) for doc in _pre_pool_service().list_codes()]


def sync_pre_pool_to_blk():
    return _write_blk(list_pre_pool())


def sync_stock_pool_to_blk():
    return _write_blk(_sorted_stock_pool_docs())


def clear_pre_pool():
    deleted_count = 0
    pre_pool_service = _pre_pool_service()
    for doc in list_pre_pool():
        if pre_pool_service.delete_code(doc.get("code")):
            deleted_count += 1
    blk_sync = _safe_sync_pre_pool_to_blk()
    return {
        "deleted_count": deleted_count,
        "category": SHOUBAN30_PRE_POOL_CATEGORY,
        "blk_sync": blk_sync,
    }


def clear_stock_pool():
    return _clear_pool(
        "stock_pools",
        SHOUBAN30_STOCK_POOL_CATEGORY,
        sync_stock_pool_to_blk,
    )


def add_pre_pool_item_to_stock_pool(code6):
    code6 = _normalize_code6(code6)
    source = next((doc for doc in list_pre_pool() if doc.get("code") == code6), None)
    if source is None:
        raise ValueError("pre_pool item not found")

    existing = DBfreshquant["stock_pools"].find_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    if existing is not None:
        DBfreshquant["stock_pools"].update_one(
            {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY},
            {
                "$set": _build_stock_pool_doc_from_source(
                    source,
                    (
                        _workspace_order(existing)
                        if _workspace_order(existing) is not None
                        else 0
                    ),
                    existing_doc=existing,
                )
            },
        )
        return "already_exists"

    stock_docs = _ensure_stock_pool_orders()
    DBfreshquant["stock_pools"].insert_one(
        _build_stock_pool_doc(source, _next_workspace_order(stock_docs))
    )
    return "created"


def sync_pre_pool_to_stock_pool():
    pre_pool_docs = list_pre_pool()
    stock_pool_docs = _ensure_stock_pool_orders()
    existing_docs_by_code = {doc.get("code"): doc for doc in stock_pool_docs}
    existing_codes = set(existing_docs_by_code)
    next_order = _next_workspace_order(stock_pool_docs)
    appended_count = 0
    skipped_count = 0

    for source_doc in pre_pool_docs:
        code = source_doc.get("code")
        if code in existing_codes:
            existing_doc = existing_docs_by_code.get(code)
            DBfreshquant["stock_pools"].update_one(
                {"code": code, "category": SHOUBAN30_STOCK_POOL_CATEGORY},
                {
                    "$set": _build_stock_pool_doc_from_source(
                        source_doc,
                        (
                            _workspace_order(existing_doc)
                            if _workspace_order(existing_doc) is not None
                            else 0
                        ),
                        existing_doc=existing_doc,
                    )
                },
            )
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
    deleted = _pre_pool_service().delete_code(code6)
    blk_sync = _safe_sync_pre_pool_to_blk()
    return {"deleted": bool(deleted), "blk_sync": blk_sync}


def list_stock_pool():
    return [_serialize_pool_doc(doc) for doc in _sorted_stock_pool_docs()]


def _upsert_must_pool_item(code6):
    code6 = _normalize_code6(code6)
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


def add_stock_pool_item_to_must_pool(code6):
    code6 = _normalize_code6(code6)
    record = DBfreshquant["stock_pools"].find_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    if record is None:
        raise ValueError("stock_pool item not found")
    return _upsert_must_pool_item(code6)


def sync_stock_pool_to_must_pool():
    stock_pool_docs = _sorted_stock_pool_docs()
    created_count = 0
    updated_count = 0

    for record in stock_pool_docs:
        status = _upsert_must_pool_item(record.get("code"))
        if status == "created":
            created_count += 1
        else:
            updated_count += 1

    return {
        "created_count": created_count,
        "updated_count": updated_count,
        "total_count": len(stock_pool_docs),
        "category": SHOUBAN30_MUST_POOL_CATEGORY,
    }


def delete_stock_pool_item(code6):
    code6 = _normalize_code6(code6)
    deleted = DBfreshquant["stock_pools"].delete_one(
        {"code": code6, "category": SHOUBAN30_STOCK_POOL_CATEGORY}
    )
    return {"deleted": deleted.deleted_count > 0}
