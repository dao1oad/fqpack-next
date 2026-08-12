# -*- coding: utf-8 -*-

"""#582 PR4：账本守恒不变量纯函数测试。"""

from freshquant.order_management.ledger_invariants import (
    check_all_ledger_invariants,
    check_entry_member_conservation,
    check_ledger_vs_positions,
    check_slice_conservation,
)


def _entry(entry_id, symbol, original, remaining, members=None, status="OPEN"):
    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "original_quantity": original,
        "remaining_quantity": remaining,
        "status": status,
        "aggregation_members": members,
    }


def test_entry_member_conservation_passes_when_quantities_match():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[
                {"broker_order_key": "k1", "quantity": 300},
                {"broker_order_key": "k2", "quantity": 7100},
            ],
        )
    ]

    assert check_entry_member_conservation(entries) == []


def test_entry_member_conservation_reports_mismatch():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[{"broker_order_key": "k1", "quantity": 300}],
        )
    ]

    violations = check_entry_member_conservation(entries)

    assert len(violations) == 1
    assert violations[0]["entry_quantity"] == 7400
    assert violations[0]["member_quantity"] == 300


def test_entry_member_conservation_skips_legacy_entries_without_members():
    entries = [_entry("entry_1", "600104", 94700, 94700, members=None)]

    assert check_entry_member_conservation(entries) == []


def test_slice_conservation_reports_drift():
    entries = [
        _entry("entry_1", "600104", 7400, 7400),
        _entry("entry_2", "600917", 96900, 96900),
    ]
    slices = [
        {"entry_id": "entry_1", "original_quantity": 4800},
        {"entry_id": "entry_1", "original_quantity": 2600},
        {"entry_id": "entry_2", "original_quantity": 96900},
    ]

    assert check_slice_conservation(entries, slices) == []
    slices[0]["original_quantity"] = 4801
    violations = check_slice_conservation(entries, slices)
    assert len(violations) == 1
    assert violations[0]["entry_id"] == "entry_1"
    assert violations[0]["slice_quantity"] == 7401


def test_ledger_vs_positions_normalizes_symbol_suffix_and_merges_base_t():
    positions = [
        {"stock_code": "600104.SH", "volume": 102100},
        {"stock_code": "600917.SH", "volume": 96900},
    ]
    entries = [
        _entry("entry_base", "600104", 94700, 94700),
        _entry("entry_t", "600104", 7400, 7400),
        _entry("entry_600917", "600917", 96900, 96900),
    ]

    assert check_ledger_vs_positions(positions, entries) == []


def test_ledger_vs_positions_excludes_closed_entries():
    positions = [{"stock_code": "600104.SH", "volume": 102100}]
    entries = [
        _entry("entry_base", "600104", 94700, 94700),
        _entry("entry_closed", "600104", 7400, 0, status="CLOSED"),
    ]

    violations = check_ledger_vs_positions(positions, entries)

    assert len(violations) == 1
    assert violations[0]["broker_quantity"] == 102100
    assert violations[0]["ledger_quantity"] == 94700


def test_check_all_returns_grouped_violations():
    entries = [
        _entry(
            "entry_1",
            "600104",
            7400,
            7400,
            members=[{"broker_order_key": "k1", "quantity": 300}],
        )
    ]
    slices = [{"entry_id": "entry_1", "original_quantity": 7401}]
    positions = [{"stock_code": "600104.SH", "volume": 102100}]

    result = check_all_ledger_invariants(
        positions=positions,
        entries=entries,
        slices=slices,
    )

    assert len(result["entry_member_conservation"]) == 1
    assert len(result["slice_conservation"]) == 1
    assert len(result["ledger_vs_positions"]) == 1
