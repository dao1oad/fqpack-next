# -*- coding: utf-8 -*-

from __future__ import annotations

from freshquant.order_management.repository import OrderManagementRepository

POSITION_TYPE_BASE = "base"
POSITION_TYPE_T = "t"


def position_type_of(value) -> str:
    """读取侧统一口径：``position_type`` 缺失/未知一律按 base 处理。

    双账本（#549）约定：T 账本由运行时 ingest 显式打标 ``t``；底仓、回填、
    重建与旧数据默认按 base。消除"回填后、部署前旧代码写入无标记 slice"
    窗口期两账本都不可见的问题。
    """

    if str(value or "").strip().lower() == POSITION_TYPE_T:
        return POSITION_TYPE_T
    return POSITION_TYPE_BASE


def get_entry_view(entry_id, repository=None):
    """读侧唯一入口：按 entry_id 返回 V2 position entry 视图。

    6a 收口后 V2 为唯一真值；legacy buy_lot 兜底已移除。
    """

    repository = repository or OrderManagementRepository()
    entry_id_text = str(entry_id or "").strip()
    if not entry_id_text:
        return None
    entry = repository.find_position_entry(entry_id_text)
    if entry is None:
        return None
    return _normalize_entry(entry)


def list_open_entry_views(symbol=None, repository=None):
    """读侧唯一入口：V2 position entries 的开放持仓视图。"""

    repository = repository or OrderManagementRepository()
    rows = []
    for item in repository.list_position_entries(symbol=symbol):
        normalized = _normalize_entry(item)
        if int(normalized.get("remaining_quantity") or 0) <= 0:
            continue
        rows.append(normalized)

    rows.sort(
        key=lambda item: (
            int(item.get("trade_time") or 0),
            int(item.get("date") or 0),
            str(item.get("time") or ""),
            str(item.get("entry_id") or ""),
        ),
        reverse=True,
    )
    return rows


def list_open_entry_slices(symbol=None, entry_ids=None, repository=None):
    """读侧唯一入口：V2 开放 entry slices 视图（原 list_open_entry_slices_compat）。"""

    repository = repository or OrderManagementRepository()
    normalized_entry_ids = {
        str(item).strip() for item in list(entry_ids or []) if str(item).strip()
    }
    rows = []
    for item in repository.list_open_entry_slices(
        symbol=symbol,
        entry_ids=list(normalized_entry_ids) if normalized_entry_ids else None,
    ):
        rows.append(_normalize_entry_slice(item))

    rows.sort(
        key=lambda item: (
            float(item.get("guardian_price") or 0.0),
            int(item.get("slice_seq") or 0),
            str(item.get("entry_slice_id") or ""),
        ),
        reverse=True,
    )
    return rows


def _normalize_entry(entry):
    row = dict(entry)
    row["entry_id"] = str(row.get("entry_id") or "").strip()
    row["entry_price"] = row.get("entry_price", row.get("buy_price_real"))
    row["entry_type"] = row.get("entry_type") or "position_entry"
    row["status"] = row.get("status") or "OPEN"
    row["sell_history"] = list(row.get("sell_history") or [])
    return row


def _normalize_entry_slice(item):
    row = dict(item)
    row["entry_slice_id"] = str(row.get("entry_slice_id") or "").strip()
    row["entry_id"] = str(row.get("entry_id") or "").strip()
    row["status"] = row.get("status") or "OPEN"
    return row
