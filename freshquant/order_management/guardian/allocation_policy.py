# -*- coding: utf-8 -*-

from typing import Any

from freshquant.order_management.guardian.sell_semantics import (
    normalize_preferred_entry_quantities,
)
from freshquant.order_management.ids import new_allocation_id


class SellAllocationPlanExhaustedError(ValueError):
    """剩余来源计划不足以解释券商成交，fail-closed，不允许静默猜测来源。"""


def stable_open_entry_slice_order(slices):
    """显式稳定排序：guardian_price ASC, trade_time ASC, slice_seq ASC, id ASC。

    分配按最低价优先消费；禁止依赖 Mongo natural order 或调用方传入顺序。
    """

    return sorted(
        list(slices or []),
        key=lambda item: (
            _stable_price_sort_key(item.get("guardian_price")),
            int(item.get("trade_time") or 0),
            int(item.get("slice_seq") or 0),
            str(item.get("entry_slice_id") or item.get("lot_slice_id") or ""),
        ),
    )


def allocate_sell_to_slices(buy_lots, open_slices, sell_trade_fact):
    remaining_sell_quantity = sell_trade_fact["quantity"]
    allocations = []
    buy_lot_by_id = {item["buy_lot_id"]: item for item in buy_lots}

    for slice_document in stable_open_entry_slice_order(open_slices):
        if remaining_sell_quantity <= 0:
            break
        if slice_document["remaining_quantity"] <= 0:
            continue

        allocated_quantity = min(
            slice_document["remaining_quantity"], remaining_sell_quantity
        )
        slice_document["remaining_quantity"] -= allocated_quantity
        slice_document["remaining_amount"] = round(
            slice_document["guardian_price"] * slice_document["remaining_quantity"],
            2,
        )
        if slice_document["remaining_quantity"] == 0:
            slice_document["status"] = "closed"

        buy_lot = buy_lot_by_id[slice_document["buy_lot_id"]]
        buy_lot["remaining_quantity"] -= allocated_quantity
        if buy_lot["remaining_quantity"] == 0:
            buy_lot["status"] = "closed"
        else:
            buy_lot["status"] = "partial"

        allocation = {
            "allocation_id": new_allocation_id(),
            "sell_trade_fact_id": sell_trade_fact["trade_fact_id"],
            "buy_lot_id": slice_document["buy_lot_id"],
            "lot_slice_id": slice_document["lot_slice_id"],
            "guardian_price": slice_document["guardian_price"],
            "allocated_quantity": allocated_quantity,
        }
        allocations.append(allocation)
        buy_lot["sell_history"].append(allocation)
        remaining_sell_quantity -= allocated_quantity

    if remaining_sell_quantity > 0:
        raise ValueError("sell quantity exceeds open guardian slices")

    open_slices.sort(key=lambda item: item["sort_key"], reverse=True)
    return allocations


def allocate_sell_to_entry_slices(
    entries,
    open_slices,
    sell_trade_fact,
    *,
    preferred_entry_quantities=None,
    request_id=None,
    internal_order_id=None,
):
    remaining_sell_quantity = sell_trade_fact["quantity"]
    allocations = []
    entry_by_id = {item["entry_id"]: item for item in entries}
    open_slices = stable_open_entry_slice_order(open_slices)

    preferred_plan = normalize_preferred_entry_quantities(
        preferred_entry_quantities,
        remaining_quantity=remaining_sell_quantity,
    )
    if preferred_plan:
        remaining_sell_quantity = _allocate_preferred_entry_slices(
            allocations=allocations,
            entry_by_id=entry_by_id,
            open_slices=open_slices,
            remaining_sell_quantity=remaining_sell_quantity,
            preferred_plan=preferred_plan,
            sell_trade_fact=sell_trade_fact,
            request_id=request_id,
            internal_order_id=internal_order_id,
        )

    for slice_document in open_slices:
        if remaining_sell_quantity <= 0:
            break
        if slice_document["remaining_quantity"] <= 0:
            continue

        allocated_quantity = min(
            int(slice_document["remaining_quantity"] or 0), remaining_sell_quantity
        )
        slice_document["remaining_quantity"] = (
            int(slice_document["remaining_quantity"] or 0) - allocated_quantity
        )
        slice_document["remaining_amount"] = round(
            slice_document["guardian_price"] * slice_document["remaining_quantity"],
            2,
        )
        if slice_document["remaining_quantity"] == 0:
            slice_document["status"] = "CLOSED"

        entry = entry_by_id[slice_document["entry_id"]]
        entry["remaining_quantity"] -= allocated_quantity
        if entry["remaining_quantity"] == 0:
            entry["status"] = "CLOSED"
        else:
            entry["status"] = "PARTIALLY_EXITED"

        allocation = {
            "allocation_id": new_allocation_id(),
            "exit_trade_fact_id": sell_trade_fact["trade_fact_id"],
            "entry_id": slice_document["entry_id"],
            "entry_slice_id": slice_document["entry_slice_id"],
            "guardian_price": slice_document["guardian_price"],
            "allocated_quantity": allocated_quantity,
            "request_id": request_id,
            "internal_order_id": internal_order_id,
        }
        allocations.append(allocation)
        entry.setdefault("sell_history", []).append(allocation)
        remaining_sell_quantity -= allocated_quantity

    if remaining_sell_quantity > 0:
        raise ValueError("sell quantity exceeds open entry slices")

    return allocations


def allocate_sell_to_entry_slices_with_budget(
    entries,
    open_slices,
    sell_trade_fact,
    *,
    source_plan=None,
    already_allocated_by_slice=None,
    already_allocated_by_entry=None,
    request_id=None,
    internal_order_id=None,
):
    """请求级剩余来源预算 + fail-closed 分配。

    - ``source_plan`` 来自 ``extract_guardian_sell_source_plan(payload)``；
    - ``already_allocated_*`` 是同一请求此前 fill 已写入
      ``om_exit_allocations`` 的累计量，跨 fill 共享；
    - 分配只允许消费剩余计划内的 entry/slice；剩余计划不足以解释本次
      broker fill 时抛 ``SellAllocationPlanExhaustedError``，把 degraded 证据
      留给上层，绝不静默回退到计划外 slice；
    - 无来源计划（非 Guardian 卖单）时保持既有稳定默认顺序兜底。
    """

    remaining_sell_quantity = int(sell_trade_fact.get("quantity") or 0)
    if remaining_sell_quantity <= 0:
        return []
    allocations: list[dict[str, Any]] = []
    entry_by_id = {item["entry_id"]: item for item in entries}
    open_slices = stable_open_entry_slice_order(open_slices)

    plan = dict(source_plan or {})
    plan_slices = list(plan.get("slices") or [])
    plan_entries = list(plan.get("entries") or [])
    has_plan = bool(plan_slices or plan_entries)

    already_by_slice = {
        str(key or ""): int(value or 0)
        for key, value in (already_allocated_by_slice or {}).items()
    }
    already_by_entry = {
        str(key or ""): int(value or 0)
        for key, value in (already_allocated_by_entry or {}).items()
    }
    if not plan_slices and plan_entries:
        already_by_slice = {}

    slice_budget = {
        str(item.get("entry_slice_id") or "").strip(): max(
            int(item.get("quantity") or 0)
            - already_by_slice.get(
                str(item.get("entry_slice_id") or "").strip(),
                0,
            ),
            0,
        )
        for item in plan_slices
        if str(item.get("entry_slice_id") or "").strip()
    }
    entry_budget = {
        str(item.get("entry_id") or "").strip(): max(
            int(item.get("quantity") or 0)
            - already_by_entry.get(str(item.get("entry_id") or "").strip(), 0),
            0,
        )
        for item in plan_entries
        if str(item.get("entry_id") or "").strip()
    }

    if has_plan:
        # 预校验：剩余计划可分配总量必须覆盖本次 fill，否则在改写任何
        # entry/slice 之前 fail-closed，避免“部分消费后抛异常”留下不一致账本。
        plan_available = 0
        for slice_document in open_slices:
            if int(slice_document.get("remaining_quantity") or 0) <= 0:
                continue
            entry_id = str(slice_document.get("entry_id") or "").strip()
            slice_id = str(slice_document.get("entry_slice_id") or "").strip()
            if entry_id not in entry_budget or entry_budget.get(entry_id, 0) <= 0:
                continue
            if slice_budget and slice_id not in slice_budget:
                continue
            slice_plan_remaining = slice_budget.get(
                slice_id,
                entry_budget.get(entry_id, 0),
            )
            if slice_plan_remaining <= 0:
                continue
            plan_available += min(
                int(slice_document.get("remaining_quantity") or 0),
                slice_plan_remaining,
                entry_budget.get(entry_id, 0),
            )
        if plan_available < remaining_sell_quantity:
            raise SellAllocationPlanExhaustedError(
                "sell fill quantity exceeds remaining request source plan: "
                f"request_id={request_id or ''} "
                f"internal_order_id={internal_order_id or ''} "
                f"unexplained_quantity={remaining_sell_quantity - plan_available} "
                f"plan_available={plan_available} "
                f"plan_version={plan.get('version') or 1}"
            )

    for slice_document in open_slices:
        if remaining_sell_quantity <= 0:
            break
        if int(slice_document.get("remaining_quantity") or 0) <= 0:
            continue
        entry_id = str(slice_document.get("entry_id") or "").strip()
        slice_id = str(slice_document.get("entry_slice_id") or "").strip()
        if has_plan:
            if entry_id not in entry_budget or entry_budget.get(entry_id, 0) <= 0:
                continue
            if slice_budget and slice_id not in slice_budget:
                continue
            slice_plan_remaining = slice_budget.get(
                slice_id,
                entry_budget.get(entry_id, 0),
            )
            if slice_plan_remaining <= 0:
                continue
            allocated_quantity = min(
                int(slice_document.get("remaining_quantity") or 0),
                remaining_sell_quantity,
                slice_plan_remaining,
                entry_budget.get(entry_id, 0),
            )
        else:
            allocated_quantity = min(
                int(slice_document.get("remaining_quantity") or 0),
                remaining_sell_quantity,
            )
        if allocated_quantity <= 0:
            continue
        _consume_entry_slice(
            allocations=allocations,
            entry_by_id=entry_by_id,
            slice_document=slice_document,
            sell_trade_fact=sell_trade_fact,
            allocated_quantity=allocated_quantity,
            request_id=request_id,
            internal_order_id=internal_order_id,
            source_plan_version=plan.get("version"),
        )
        remaining_sell_quantity -= allocated_quantity
        if has_plan:
            entry_budget[entry_id] -= allocated_quantity
            if slice_id in slice_budget:
                slice_budget[slice_id] -= allocated_quantity

    if remaining_sell_quantity > 0:
        if has_plan:
            raise SellAllocationPlanExhaustedError(
                "sell fill quantity exceeds remaining request source plan: "
                f"request_id={request_id or ''} "
                f"internal_order_id={internal_order_id or ''} "
                f"unexplained_quantity={remaining_sell_quantity} "
                f"plan_version={plan.get('version') or 1}"
            )
        raise ValueError("sell quantity exceeds open entry slices")
    return allocations


def _allocate_preferred_entry_slices(
    *,
    allocations,
    entry_by_id,
    open_slices,
    remaining_sell_quantity,
    preferred_plan,
    sell_trade_fact,
    request_id=None,
    internal_order_id=None,
):
    remaining = int(remaining_sell_quantity or 0)
    for source_entry in list(preferred_plan or []):
        entry_id = str(source_entry.get("entry_id") or "").strip()
        entry_remaining = int(source_entry.get("quantity") or 0)
        if remaining <= 0 or not entry_id or entry_remaining <= 0:
            continue
        for slice_document in open_slices:
            if remaining <= 0 or entry_remaining <= 0:
                break
            if str(slice_document.get("entry_id") or "").strip() != entry_id:
                continue
            if int(slice_document.get("remaining_quantity") or 0) <= 0:
                continue
            allocated_quantity = min(
                int(slice_document["remaining_quantity"] or 0),
                remaining,
                entry_remaining,
            )
            if allocated_quantity <= 0:
                continue
            _consume_entry_slice(
                allocations=allocations,
                entry_by_id=entry_by_id,
                slice_document=slice_document,
                sell_trade_fact=sell_trade_fact,
                allocated_quantity=allocated_quantity,
                request_id=request_id,
                internal_order_id=internal_order_id,
            )
            remaining -= allocated_quantity
            entry_remaining -= allocated_quantity
    return remaining


def _consume_entry_slice(
    *,
    allocations,
    entry_by_id,
    slice_document,
    sell_trade_fact,
    allocated_quantity,
    request_id=None,
    internal_order_id=None,
    source_plan_version=None,
):
    slice_document["remaining_quantity"] = int(
        slice_document.get("remaining_quantity") or 0
    ) - int(allocated_quantity or 0)
    slice_document["remaining_amount"] = round(
        float(slice_document.get("guardian_price") or 0.0)
        * int(slice_document["remaining_quantity"] or 0),
        2,
    )
    if int(slice_document["remaining_quantity"]) == 0:
        slice_document["status"] = "CLOSED"

    entry = entry_by_id[slice_document["entry_id"]]
    entry["remaining_quantity"] = int(entry.get("remaining_quantity") or 0) - int(
        allocated_quantity or 0
    )
    if int(entry["remaining_quantity"]) == 0:
        entry["status"] = "CLOSED"
    else:
        entry["status"] = "PARTIALLY_EXITED"

    allocation = {
        "allocation_id": new_allocation_id(),
        "exit_trade_fact_id": sell_trade_fact["trade_fact_id"],
        "entry_id": slice_document["entry_id"],
        "entry_slice_id": slice_document["entry_slice_id"],
        "guardian_price": slice_document["guardian_price"],
        "allocated_quantity": int(allocated_quantity or 0),
        "request_id": request_id,
        "internal_order_id": internal_order_id,
        "source_plan_version": source_plan_version,
    }
    allocations.append(allocation)
    entry.setdefault("sell_history", []).append(allocation)


def _stable_price_sort_key(value) -> tuple:
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value or ""))
