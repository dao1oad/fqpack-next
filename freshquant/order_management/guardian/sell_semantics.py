# -*- coding: utf-8 -*-

from typing import Any

from freshquant.order_management.guardian.read_model import (
    build_arranged_fill_read_model,
)

GUARDIAN_SELL_SOURCES_VERSION = 2


def build_guardian_sell_source_entries(fill_list, *, quantity):
    remaining = int(quantity or 0)
    if remaining <= 0:
        return []

    source_entries = []
    for item in reversed(list(fill_list or [])):
        if remaining <= 0:
            break
        entry_id = str(item.get("entry_id") or "").strip()
        if not entry_id:
            continue
        available_quantity = int(item.get("quantity") or 0)
        if available_quantity <= 0:
            continue
        allocated_quantity = min(available_quantity, remaining)
        source_entries.append(
            {
                "entry_id": entry_id,
                "quantity": allocated_quantity,
            }
        )
        remaining -= allocated_quantity
    return source_entries


def resolve_guardian_sell_source_entries_from_open_slices(
    open_slices,
    *,
    exit_price,
    quantity,
):
    target_quantity = int(quantity or 0)
    try:
        target_price = float(exit_price or 0.0)
    except (TypeError, ValueError):
        return []
    if target_quantity <= 0 or target_price <= 0:
        return []

    fill_list = build_arranged_fill_read_model(open_slices or [])
    profitable_quantity = 0
    for item in reversed(fill_list):
        try:
            fill_price = float(item.get("price") or 0.0)
        except (TypeError, ValueError):
            break
        if target_price > fill_price:
            profitable_quantity += int(item.get("quantity") or 0)
            continue
        break

    if profitable_quantity < target_quantity:
        return []
    return build_guardian_sell_source_entries(fill_list, quantity=target_quantity)


def build_guardian_sell_source_plan_v2(
    eligible_slices,
    *,
    requested_quantity,
    submit_quantity,
    profitable_fill_count,
):
    """构建 ``guardian_sell_sources`` version=2 来源计划。

    - ``slices`` 是精确执行合同：每个 slice 一行，携带 ``entry_slice_id``、
      ``guardian_price`` 与逐 slice 独立 ``threshold_price``；
    - ``entries`` 是按 entry 聚合后的唯一行（同一 ``entry_id`` 只出现一次），
      供旧读链/展示/复盘使用；
    - 守恒不变量：``sum(slices.quantity) == sum(entries.quantity) ==
      submit_quantity``；
    - 来源计划只能包含已达到独立阈值的 slice（由调用方传入
      ``eligible_slices``）。
    """

    rows: list[dict[str, Any]] = []
    entry_rows: list[dict[str, Any]] = []
    for raw_item in list(eligible_slices or []):
        item = dict(raw_item or {})
        entry_id = str(item.get("entry_id") or "").strip()
        entry_slice_id = str(item.get("entry_slice_id") or "").strip()
        if not entry_id:
            continue
        quantity = int(
            item.get("eligible_quantity")
            or item.get("quantity")
            or item.get("remaining_quantity")
            or 0
        )
        if quantity <= 0:
            continue
        row = {
            "entry_id": entry_id,
            "entry_slice_id": entry_slice_id,
            "quantity": quantity,
            "guardian_price": item.get("guardian_price"),
            "threshold_price": item.get("threshold_price"),
        }
        entry_rows.append(row)
        if entry_slice_id:
            rows.append(row)

    rows.sort(
        key=lambda item: (
            _stable_price_sort_key(item.get("guardian_price")),
            str(item.get("entry_slice_id") or ""),
        )
    )
    entry_rows.sort(
        key=lambda item: (
            _stable_price_sort_key(item.get("guardian_price")),
            str(item.get("entry_id") or ""),
        )
    )
    totals: dict[str, int] = {}
    for row in entry_rows:
        totals[row["entry_id"]] = totals.get(row["entry_id"], 0) + row["quantity"]
    entries: list[dict[str, Any]] = []
    seen_entry_ids: set[str] = set()
    for row in entry_rows:
        if row["entry_id"] in seen_entry_ids:
            continue
        seen_entry_ids.add(row["entry_id"])
        entries.append(
            {"entry_id": row["entry_id"], "quantity": totals[row["entry_id"]]}
        )
    return {
        "version": GUARDIAN_SELL_SOURCES_VERSION,
        "requested_quantity": int(requested_quantity or 0),
        "submit_quantity": int(submit_quantity or 0),
        "profitable_fill_count": int(profitable_fill_count or 0),
        "slices": rows,
        "entries": entries,
    }


def extract_guardian_sell_source_plan(payload) -> dict[str, Any]:
    """从请求/回报载荷中提取来源计划，兼容 v2 与历史 v1。"""

    context = dict((payload or {}).get("strategy_context") or {})
    sell_sources = dict(context.get("guardian_sell_sources") or {})
    if not sell_sources:
        return {}
    version = int(sell_sources.get("version") or 1)
    slices = list(sell_sources.get("slices") or [])
    entries = list(sell_sources.get("entries") or [])
    return {
        "version": version,
        "requested_quantity": int(sell_sources.get("requested_quantity") or 0),
        "submit_quantity": int(sell_sources.get("submit_quantity") or 0),
        "profitable_fill_count": int(sell_sources.get("profitable_fill_count") or 0),
        "slices": [
            {
                "entry_id": str(item.get("entry_id") or "").strip(),
                "entry_slice_id": str(item.get("entry_slice_id") or "").strip(),
                "quantity": int(item.get("quantity") or 0),
                "guardian_price": item.get("guardian_price"),
                "threshold_price": item.get("threshold_price"),
            }
            for item in slices
        ],
        "entries": [
            {
                "entry_id": str(item.get("entry_id") or "").strip(),
                "quantity": int(item.get("quantity") or 0),
            }
            for item in entries
        ],
    }


def normalize_preferred_entry_quantities(
    preferred_entry_quantities,
    *,
    remaining_quantity,
):
    remaining = int(remaining_quantity or 0)
    if remaining <= 0:
        return []

    normalized = []
    for item in list(preferred_entry_quantities or []):
        if remaining <= 0:
            break
        entry_id = str((item or {}).get("entry_id") or "").strip()
        quantity = int((item or {}).get("quantity") or 0)
        if not entry_id or quantity <= 0:
            continue
        allocated_quantity = min(quantity, remaining)
        normalized.append(
            {
                "entry_id": entry_id,
                "quantity": allocated_quantity,
            }
        )
        remaining -= allocated_quantity
    return normalized


def _stable_price_sort_key(value) -> tuple:
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value or ""))


__all__ = [
    "GUARDIAN_SELL_SOURCES_VERSION",
    "build_guardian_sell_source_entries",
    "build_guardian_sell_source_plan_v2",
    "extract_guardian_sell_source_plan",
    "normalize_preferred_entry_quantities",
    "resolve_guardian_sell_source_entries_from_open_slices",
]
