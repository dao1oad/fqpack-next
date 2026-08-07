# -*- coding: utf-8 -*-

"""PR2：guardian_sell_sources version=2 来源协议测试。"""

from freshquant.order_management.guardian.sell_semantics import (
    GUARDIAN_SELL_SOURCES_VERSION,
    build_guardian_sell_source_plan_v2,
    extract_guardian_sell_source_plan,
)


def _eligible(entry_id, entry_slice_id, guardian_price, quantity, threshold_price):
    return {
        "entry_id": entry_id,
        "entry_slice_id": entry_slice_id,
        "guardian_price": guardian_price,
        "threshold_price": threshold_price,
        "eligible_quantity": quantity,
    }


def test_v2_plan_keeps_unique_slice_identity_and_unique_entries():
    plan = build_guardian_sell_source_plan_v2(
        [
            _eligible("entry_a", "slice_a1", 21.36, 2300, "21.5736"),
            _eligible("entry_a", "slice_a2", 21.58, 2300, "21.7958"),
            _eligible("entry_b", "slice_b1", 22.41, 1000, "22.6341"),
        ],
        requested_quantity=5600,
        submit_quantity=5600,
        profitable_fill_count=3,
    )

    assert plan["version"] == GUARDIAN_SELL_SOURCES_VERSION
    assert [item["entry_slice_id"] for item in plan["slices"]] == [
        "slice_a1",
        "slice_a2",
        "slice_b1",
    ]
    assert all(
        item.get("entry_slice_id") for item in plan["slices"]
    ), "slices 必须携带 entry_slice_id"
    assert [item["entry_id"] for item in plan["entries"]] == ["entry_a", "entry_b"]
    assert sum(item["quantity"] for item in plan["slices"]) == 5600
    assert sum(item["quantity"] for item in plan["entries"]) == 5600
    assert plan["submit_quantity"] == 5600


def test_v2_plan_orders_entries_by_guardian_price_ascending():
    plan = build_guardian_sell_source_plan_v2(
        [
            _eligible("entry_high", "slice_high", 22.41, 2200, "22.6341"),
            _eligible("entry_low", "slice_low", 21.32, 2300, "21.5332"),
        ],
        requested_quantity=4500,
        submit_quantity=4500,
        profitable_fill_count=2,
    )
    assert [item["entry_id"] for item in plan["entries"]] == [
        "entry_low",
        "entry_high",
    ]


def test_v2_plan_falls_back_to_entries_when_slice_ids_missing():
    plan = build_guardian_sell_source_plan_v2(
        [
            {"entry_id": "entry_old", "guardian_price": 9.8, "quantity": 100},
            {"entry_id": "entry_new", "guardian_price": 9.5, "quantity": 1000},
        ],
        requested_quantity=1100,
        submit_quantity=1100,
        profitable_fill_count=2,
    )
    assert plan["slices"] == []
    assert [item["entry_id"] for item in plan["entries"]] == [
        "entry_new",
        "entry_old",
    ]
    assert sum(item["quantity"] for item in plan["entries"]) == 1100


def test_v2_plan_aggregates_duplicate_entry_rows_into_one_canonical_row():
    plan = build_guardian_sell_source_plan_v2(
        [
            _eligible("entry_a", "slice_a1", 20.40, 2400, "20.6040"),
            _eligible("entry_a", "slice_a2", 20.76, 2300, "20.9676"),
        ],
        requested_quantity=4700,
        submit_quantity=4700,
        profitable_fill_count=2,
    )
    assert len(plan["entries"]) == 1
    assert plan["entries"][0] == {"entry_id": "entry_a", "quantity": 4700}


def test_v2_plan_never_contains_non_eligible_slices():
    # 调用方只传入 eligible_slices；builder 不接受 un-eligible 输入。
    plan = build_guardian_sell_source_plan_v2(
        [_eligible("entry_a", "slice_a1", 21.58, 2300, "21.7958")],
        requested_quantity=2300,
        submit_quantity=2300,
        profitable_fill_count=1,
    )
    assert sum(item["quantity"] for item in plan["slices"]) == 2300
    assert sum(item["quantity"] for item in plan["entries"]) == 2300


def test_extract_guardian_sell_source_plan_reads_v2_and_v1():
    v2_payload = {
        "strategy_context": {
            "guardian_sell_sources": {
                "version": 2,
                "submit_quantity": 100,
                "slices": [
                    {
                        "entry_id": "entry_a",
                        "entry_slice_id": "slice_a1",
                        "quantity": 100,
                    }
                ],
                "entries": [{"entry_id": "entry_a", "quantity": 100}],
            }
        }
    }
    plan_v2 = extract_guardian_sell_source_plan(v2_payload)
    assert plan_v2["version"] == 2
    assert plan_v2["slices"][0]["entry_slice_id"] == "slice_a1"

    v1_payload = {
        "strategy_context": {
            "guardian_sell_sources": {
                "entries": [{"entry_id": "entry_a", "quantity": 100}]
            }
        }
    }
    plan_v1 = extract_guardian_sell_source_plan(v1_payload)
    assert plan_v1["version"] == 1
    assert plan_v1["slices"] == []
    assert plan_v1["entries"][0]["entry_id"] == "entry_a"


def test_extract_guardian_sell_source_plan_returns_empty_for_plain_payload():
    assert extract_guardian_sell_source_plan({"quantity": 100}) == {}
