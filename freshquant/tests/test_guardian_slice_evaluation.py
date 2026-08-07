# -*- coding: utf-8 -*-

"""PR1：Guardian 唯一逐切片卖出判定领域函数测试。

覆盖 bug 文档中的三类事实：
- 逐切片独立止盈阈值（002262 案例：21.58 信号只应卖出 2300）；
- Decimal/最小价位规范化消除 21.580000000000002 > 21.58 浮点边界；
- ATR 模式逐 slice 使用同一历史阈值参数，不允许复用最低 slice 绝对阈值；
- Guardian 与 Position Review 对同一切片输入产生一致的 eligibility 结果。
"""

from decimal import Decimal

from freshquant.order_management.guardian.slice_evaluation import (
    build_slice_threshold,
    evaluate_guardian_sell_slices,
    normalize_price_to_tick,
    resolve_sell_threshold_config,
)


def _slice(entry_id, entry_slice_id, guardian_price, remaining_quantity):
    return {
        "entry_id": entry_id,
        "entry_slice_id": entry_slice_id,
        "guardian_price": guardian_price,
        "remaining_quantity": remaining_quantity,
    }


def test_002262_float_boundary_signal_only_sells_lowest_slice():
    slices = [
        _slice("entry_4f11", "entryslice_b8df", 21.36, 2300),
        _slice("entry_e72f", "entryslice_57c7", 21.58, 2300),
    ]
    result = evaluate_guardian_sell_slices(
        slices,
        signal_price=21.580000000000002,
        threshold_config={"mode": "percent", "percent": 1},
    )

    assert result["raw_quantity"] == 2300
    assert [item["entry_slice_id"] for item in result["eligible_slices"]] == [
        "entryslice_b8df"
    ]
    evidence_by_slice = {
        item["entry_slice_id"]: item for item in result["threshold_evidence"]
    }
    assert evidence_by_slice["entryslice_b8df"]["eligible"] is True
    assert evidence_by_slice["entryslice_b8df"]["threshold_price"] == "21.5736"
    assert evidence_by_slice["entryslice_57c7"]["eligible"] is False
    assert evidence_by_slice["entryslice_57c7"]["threshold_price"] == "21.7958"
    assert evidence_by_slice["entryslice_57c7"]["signal_price_normalized"] == "21.58"


def test_signal_below_slice_threshold_is_not_sellable():
    slices = [_slice("entry_e72f", "entryslice_57c7", 21.58, 2300)]
    result = evaluate_guardian_sell_slices(
        slices,
        signal_price=21.79,
        threshold_config={"mode": "percent", "percent": 1},
    )
    assert result["raw_quantity"] == 0
    assert result["eligible_slices"] == []
    assert result["threshold_evidence"][0]["eligible"] is False


def test_signal_at_normalized_threshold_boundary_is_inclusive():
    slices = [_slice("entry_e72f", "entryslice_57c7", 21.58, 2300)]
    result = evaluate_guardian_sell_slices(
        slices,
        signal_price=21.7958,
        threshold_config={"mode": "percent", "percent": 1},
    )
    # 21.7958 -> tick 21.80 >= 21.7958，边界按 >= 包含
    assert result["raw_quantity"] == 2300
    assert result["threshold_evidence"][0]["eligible"] is True


def test_atr_mode_evaluates_each_slice_with_same_historical_delta():
    slices = [
        _slice("entry_low", "slice_low", 20.76, 2400),
        _slice("entry_high", "slice_high", 21.78, 2200),
    ]
    result = evaluate_guardian_sell_slices(
        slices,
        signal_price=21.56,
        threshold_config={"mode": "atr", "threshold_delta": 0.2176},
    )

    # 20.76 + 0.2176 = 20.9776 -> 21.56 达标；21.78 + 0.2176 = 21.9976 -> 不达标
    assert result["raw_quantity"] == 2400
    evidence_by_slice = {
        item["entry_slice_id"]: item for item in result["threshold_evidence"]
    }
    assert evidence_by_slice["slice_low"]["eligible"] is True
    assert evidence_by_slice["slice_low"]["threshold_price"] == "20.9776"
    assert evidence_by_slice["slice_high"]["eligible"] is False
    assert evidence_by_slice["slice_high"]["threshold_price"] == "21.9976"


def test_percent_config_resolution_from_threshold_result():
    config = resolve_sell_threshold_config(
        {
            "base_price": 21.32,
            "top_river_price": 21.5332,
            "config": {"mode": "percent", "percent": 1},
        }
    )
    assert config == {"mode": "percent", "percent": 1.0}


def test_atr_config_resolution_derives_delta_from_top_minus_base():
    config = resolve_sell_threshold_config(
        {
            "base_price": 21.32,
            "top_river_price": 21.9876,
            "config": {"mode": "atr", "atr": {"period": 20, "multiplier": 1}},
        }
    )
    assert config["mode"] == "atr"
    assert config["threshold_delta"] == "0.6676"


def test_normalize_price_to_tick_removes_float_representation_noise():
    assert normalize_price_to_tick(21.580000000000002) == Decimal("21.58")
    assert normalize_price_to_tick("21.58") == Decimal("21.58")
    assert normalize_price_to_tick(21.7958) == Decimal("21.80")


def test_build_slice_threshold_percent_precision():
    threshold = build_slice_threshold(
        "21.58",
        {"mode": "percent", "percent": 1},
    )
    assert threshold["threshold_price"] == "21.7958"
    assert threshold["threshold_mode"] == "percent"
    assert threshold["threshold_ratio"] == "0.0100"


def test_guardian_and_position_review_share_identical_eligibility():
    # Position Review 的 active inventory 结构（guardian_price/remaining_quantity）
    # 与 Guardian arranged fill 结构（price/quantity）都应得到同一 eligibility。
    inventory_style = [
        _slice("entry_a", "slice_a", 10.0, 300),
        _slice("entry_b", "slice_b", 10.3, 200),
    ]
    fill_style = [
        {
            "entry_id": "entry_a",
            "entry_slice_id": "slice_a",
            "price": 10.0,
            "quantity": 300,
        },
        {
            "entry_id": "entry_b",
            "entry_slice_id": "slice_b",
            "price": 10.3,
            "quantity": 200,
        },
    ]
    config = {"mode": "percent", "percent": 1}
    from_inventory = evaluate_guardian_sell_slices(
        inventory_style,
        signal_price=10.5,
        threshold_config=config,
    )
    from_fills = evaluate_guardian_sell_slices(
        fill_style,
        signal_price=10.5,
        threshold_config=config,
    )
    assert from_inventory["raw_quantity"] == from_fills["raw_quantity"] == 500
    assert [item["eligible"] for item in from_inventory["threshold_evidence"]] == [
        item["eligible"] for item in from_fills["threshold_evidence"]
    ]


def test_zero_or_negative_remaining_slices_are_skipped():
    slices = [
        _slice("entry_a", "slice_a", 10.0, 0),
        _slice("entry_b", "slice_b", 10.5, 100),
    ]
    result = evaluate_guardian_sell_slices(
        slices,
        signal_price=11.0,
        threshold_config={"mode": "percent", "percent": 1},
    )
    assert result["raw_quantity"] == 100
    assert len(result["threshold_evidence"]) == 1
