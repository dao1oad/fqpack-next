# -*- coding: utf-8 -*-

"""PR2：请求级剩余来源预算 + fail-closed 分配测试。"""

import pytest

from freshquant.order_management.guardian.allocation_policy import (
    SellAllocationPlanExhaustedError,
    allocate_sell_to_entry_slices_with_budget,
    stable_open_entry_slice_order,
)
from freshquant.order_management.guardian.arranger import (
    arrange_entry,
    build_position_entry_from_trade_fact,
)


def _entry(entry_id, symbol="000001", quantity=2300, price=21.36, trade_time=1000):
    entry = build_position_entry_from_trade_fact(
        {
            "trade_fact_id": f"fact_{entry_id}",
            "symbol": symbol,
            "side": "buy",
            "quantity": quantity,
            "price": price,
            "trade_time": trade_time,
            "date": 20240101,
            "time": "09:30:00",
        },
        entry_id=entry_id,
        source_ref_type="buy_cluster",
        source_ref_id=f"cluster:{entry_id}",
        entry_type="broker_execution_cluster",
    )
    return entry


def _fill(trade_fact_id, quantity, request_id="req_1", internal_order_id="ord_1"):
    return {
        "trade_fact_id": trade_fact_id,
        "symbol": "000001",
        "side": "sell",
        "quantity": quantity,
        "request_id": request_id,
        "internal_order_id": internal_order_id,
    }


def _v2_plan(*slice_specs, submit_quantity=None, requested_quantity=None):
    slices = [
        {
            "entry_id": entry_id,
            "entry_slice_id": entry_slice_id,
            "quantity": quantity,
            "guardian_price": guardian_price,
            "threshold_price": threshold_price,
        }
        for entry_id, entry_slice_id, quantity, guardian_price, threshold_price in slice_specs
    ]
    entries = []
    totals = {}
    for item in slices:
        totals[item["entry_id"]] = totals.get(item["entry_id"], 0) + item["quantity"]
    for entry_id, quantity in totals.items():
        entries.append({"entry_id": entry_id, "quantity": quantity})
    submit_quantity = submit_quantity or sum(item["quantity"] for item in slices)
    return {
        "version": 2,
        "requested_quantity": requested_quantity or submit_quantity,
        "submit_quantity": submit_quantity,
        "profitable_fill_count": len(slices),
        "slices": slices,
        "entries": entries,
    }


def test_multi_fill_shares_request_level_remaining_budget():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    entry_b = _entry("entry_b", quantity=2300, price=21.58, trade_time=2000)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    slices_b = arrange_entry(entry_b, lot_amount=50000, grid_interval=1.2)
    open_slices = slices_a + slices_b
    plan = _v2_plan(
        ("entry_a", slices_a[0]["entry_slice_id"], 2300, 21.36, "21.5736"),
        ("entry_b", slices_b[0]["entry_slice_id"], 2300, 21.58, "21.7958"),
        submit_quantity=4600,
    )

    # fill1 200 从 A 消费；fill2 2100 从 A 继续；fill3 2300 从 B。
    allocations = []
    already_slice = {}
    already_entry = {}
    for quantity in (200, 2100, 2300):
        result = allocate_sell_to_entry_slices_with_budget(
            entries=[entry_a, entry_b],
            open_slices=open_slices,
            sell_trade_fact=_fill(f"fill_{quantity}", quantity),
            source_plan=plan,
            already_allocated_by_slice=already_slice,
            already_allocated_by_entry=already_entry,
            request_id="req_1",
            internal_order_id="ord_1",
        )
        allocations.extend(result)
        for item in result:
            slice_id = item["entry_slice_id"]
            entry_id = item["entry_id"]
            already_slice[slice_id] = (
                already_slice.get(slice_id, 0) + item["allocated_quantity"]
            )
            already_entry[entry_id] = (
                already_entry.get(entry_id, 0) + item["allocated_quantity"]
            )

    by_entry = {}
    for item in allocations:
        by_entry[item["entry_id"]] = (
            by_entry.get(item["entry_id"], 0) + item["allocated_quantity"]
        )
    assert by_entry == {"entry_a": 2300, "entry_b": 2300}
    assert sum(item["allocated_quantity"] for item in allocations) == 4600


def test_out_of_order_fills_produce_same_final_allocation():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    entry_b = _entry("entry_b", quantity=2300, price=21.58, trade_time=2000)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    slices_b = arrange_entry(entry_b, lot_amount=50000, grid_interval=1.2)
    open_slices = slices_a + slices_b
    plan = _v2_plan(
        ("entry_a", slices_a[0]["entry_slice_id"], 2300, 21.36, "21.5736"),
        ("entry_b", slices_b[0]["entry_slice_id"], 2300, 21.58, "21.7958"),
        submit_quantity=4600,
    )

    def _run(order):
        entries = [dict(entry_a), dict(entry_b)]
        slices = [dict(item) for item in open_slices]
        allocations = []
        already_slice = {}
        already_entry = {}
        for quantity in order:
            result = allocate_sell_to_entry_slices_with_budget(
                entries=entries,
                open_slices=slices,
                sell_trade_fact=_fill(f"fill_{quantity}", quantity),
                source_plan=plan,
                already_allocated_by_slice=already_slice,
                already_allocated_by_entry=already_entry,
                request_id="req_1",
                internal_order_id="ord_1",
            )
            allocations.extend(result)
            for item in result:
                already_slice[item["entry_slice_id"]] = (
                    already_slice.get(item["entry_slice_id"], 0)
                    + item["allocated_quantity"]
                )
                already_entry[item["entry_id"]] = (
                    already_entry.get(item["entry_id"], 0) + item["allocated_quantity"]
                )
        return allocations

    allocations_in_order = _run([200, 2100, 2300])
    allocations_reversed = _run([2300, 2100, 200])

    def _by_entry(allocations):
        result = {}
        for item in allocations:
            result[item["entry_id"]] = (
                result.get(item["entry_id"], 0) + item["allocated_quantity"]
            )
        return result

    assert _by_entry(allocations_in_order) == {"entry_a": 2300, "entry_b": 2300}
    assert _by_entry(allocations_reversed) == {"entry_a": 2300, "entry_b": 2300}


def test_duplicate_callback_after_plan_exhausted_is_fail_closed():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    plan = _v2_plan(
        ("entry_a", slices_a[0]["entry_slice_id"], 2300, 21.36, "21.5736"),
        submit_quantity=2300,
    )
    already_slice = {slices_a[0]["entry_slice_id"]: 2300}
    already_entry = {"entry_a": 2300}

    with pytest.raises(SellAllocationPlanExhaustedError):
        allocate_sell_to_entry_slices_with_budget(
            entries=[entry_a],
            open_slices=slices_a,
            sell_trade_fact=_fill("fill_dup", 100),
            source_plan=plan,
            already_allocated_by_slice=already_slice,
            already_allocated_by_entry=already_entry,
            request_id="req_1",
            internal_order_id="ord_1",
        )


def test_no_silent_cross_plan_fallback_to_unplanned_slices():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    entry_unplanned = _entry("entry_z", quantity=2300, price=26.00, trade_time=3000)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    slices_z = arrange_entry(entry_unplanned, lot_amount=50000, grid_interval=1.2)
    plan = _v2_plan(
        ("entry_a", slices_a[0]["entry_slice_id"], 2300, 21.36, "21.5736"),
        submit_quantity=2300,
    )

    with pytest.raises(SellAllocationPlanExhaustedError) as exc_info:
        allocate_sell_to_entry_slices_with_budget(
            entries=[entry_a, entry_unplanned],
            open_slices=slices_a + slices_z,
            sell_trade_fact=_fill("fill_over", 2400),
            source_plan=plan,
            request_id="req_1",
            internal_order_id="ord_1",
        )
    assert "exceeds remaining request source plan" in str(exc_info.value)


def test_v1_entry_plan_is_still_supported_with_budget():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    plan = {
        "version": 1,
        "requested_quantity": 500,
        "submit_quantity": 500,
        "slices": [],
        "entries": [{"entry_id": "entry_a", "quantity": 500}],
    }
    result = allocate_sell_to_entry_slices_with_budget(
        entries=[entry_a],
        open_slices=slices_a,
        sell_trade_fact=_fill("fill_v1", 500),
        source_plan=plan,
        request_id="req_1",
        internal_order_id="ord_1",
    )
    assert sum(item["allocated_quantity"] for item in result) == 500
    assert all(item["entry_id"] == "entry_a" for item in result)


def test_allocation_without_plan_keeps_default_stable_order():
    entry_a = _entry("entry_a", quantity=300, price=10.0)
    slices_a = arrange_entry(entry_a, lot_amount=3000, grid_interval=1.03)
    result = allocate_sell_to_entry_slices_with_budget(
        entries=[entry_a],
        open_slices=slices_a,
        sell_trade_fact=_fill("fill_default", 250),
        request_id=None,
        internal_order_id=None,
    )
    assert sum(item["allocated_quantity"] for item in result) == 250


def test_stable_open_entry_slice_order_is_deterministic_regardless_of_input_order():
    slices = [
        {
            "entry_id": "e2",
            "entry_slice_id": "s2",
            "guardian_price": 10.61,
            "trade_time": 3,
            "slice_seq": 2,
        },
        {
            "entry_id": "e1",
            "entry_slice_id": "s1",
            "guardian_price": 10.0,
            "trade_time": 1,
            "slice_seq": 0,
        },
        {
            "entry_id": "e3",
            "entry_slice_id": "s3",
            "guardian_price": 10.3,
            "trade_time": 2,
            "slice_seq": 1,
        },
    ]
    ordered = stable_open_entry_slice_order(slices)
    assert [item["entry_slice_id"] for item in ordered] == ["s1", "s3", "s2"]
    assert stable_open_entry_slice_order(list(reversed(slices))) == ordered


def test_partial_fill_then_cancel_leaves_budget_remaining_consistent():
    entry_a = _entry("entry_a", quantity=2300, price=21.36)
    slices_a = arrange_entry(entry_a, lot_amount=50000, grid_interval=1.2)
    plan = _v2_plan(
        ("entry_a", slices_a[0]["entry_slice_id"], 2300, 21.36, "21.5736"),
        submit_quantity=2300,
    )
    already_slice = {}
    already_entry = {}
    partial = allocate_sell_to_entry_slices_with_budget(
        entries=[entry_a],
        open_slices=slices_a,
        sell_trade_fact=_fill("fill_partial", 1200),
        source_plan=plan,
        already_allocated_by_slice=already_slice,
        already_allocated_by_entry=already_entry,
        request_id="req_1",
        internal_order_id="ord_1",
    )
    already_slice[partial[0]["entry_slice_id"]] = partial[0]["allocated_quantity"]
    already_entry["entry_a"] = partial[0]["allocated_quantity"]

    # 撤单后剩余计划只允许再分配 1100，多出即 fail-closed。
    with pytest.raises(SellAllocationPlanExhaustedError):
        allocate_sell_to_entry_slices_with_budget(
            entries=[entry_a],
            open_slices=slices_a,
            sell_trade_fact=_fill("fill_after_cancel", 1200),
            source_plan=plan,
            already_allocated_by_slice=already_slice,
            already_allocated_by_entry=already_entry,
            request_id="req_1",
            internal_order_id="ord_1",
        )
