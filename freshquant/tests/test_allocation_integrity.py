# -*- coding: utf-8 -*-

from freshquant.order_management.allocation_integrity import (
    find_exit_allocation_integrity_errors,
)


def _entry(
    entry_id="E1", symbol="600000", original_quantity=1000, remaining_quantity=400
):
    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "original_quantity": original_quantity,
        "remaining_quantity": remaining_quantity,
    }


def _slice(
    entry_slice_id="S1",
    entry_id="E1",
    symbol="600000",
    original_quantity=600,
    remaining_quantity=0,
):
    return {
        "entry_slice_id": entry_slice_id,
        "entry_id": entry_id,
        "symbol": symbol,
        "original_quantity": original_quantity,
        "remaining_quantity": remaining_quantity,
    }


def _allocation(
    allocation_id="A1",
    entry_id="E1",
    entry_slice_id="S1",
    symbol="600000",
    allocated_quantity=600,
):
    return {
        "allocation_id": allocation_id,
        "entry_id": entry_id,
        "entry_slice_id": entry_slice_id,
        "symbol": symbol,
        "allocated_quantity": allocated_quantity,
    }


def _error_types(errors):
    return sorted(error.get("reference_type") for error in errors)


def test_healthy_ledger_returns_zero_errors():
    entries = [
        _entry("E1", "600000", original_quantity=1000, remaining_quantity=400),
        _entry("E2", "600000", original_quantity=500, remaining_quantity=500),
    ]
    slices = [
        _slice("S1", "E1", "600000", original_quantity=600, remaining_quantity=0),
        _slice("S2", "E1", "600000", original_quantity=400, remaining_quantity=400),
    ]
    allocations = [
        _allocation("A1", "E1", "S1", "600000", allocated_quantity=600),
    ]
    assert (
        find_exit_allocation_integrity_errors(
            position_entries=entries,
            entry_slices=slices,
            exit_allocations=allocations,
        )
        == []
    )


def test_missing_entry_reference_is_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[],
        entry_slices=[_slice("S1", "E1", "600000")],
        exit_allocations=[_allocation("A1", "E1", "S1", "600000")],
    )
    assert "entry_id" in _error_types(errors)
    entry_error = next(
        error for error in errors if error["reference_type"] == "entry_id"
    )
    assert entry_error["reference_id"] == "E1"


def test_missing_slice_reference_is_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[_entry("E1", "600000")],
        entry_slices=[],
        exit_allocations=[_allocation("A1", "E1", "S1", "600000")],
    )
    assert "entry_slice_id" in _error_types(errors)
    slice_error = next(
        error for error in errors if error["reference_type"] == "entry_slice_id"
    )
    assert slice_error["reference_id"] == "S1"


def test_slice_owned_by_wrong_entry_is_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[_entry("E1", "600000")],
        entry_slices=[_slice("S1", "E2", "600000")],
        exit_allocations=[_allocation("A1", "E1", "S1", "600000")],
    )
    owner_errors = [
        error for error in errors if error["reference_type"] == "entry_slice_owner"
    ]
    assert len(owner_errors) == 1
    assert owner_errors[0]["expected_entry_id"] == "E1"
    assert owner_errors[0]["actual_entry_id"] == "E2"


def test_mixed_symbol_504_scenario_is_reported_on_all_three_surfaces():
    # #504 场景：allocation 引用的 entry/slice symbol 不一致
    errors = find_exit_allocation_integrity_errors(
        position_entries=[_entry("E1", "688772")],
        entry_slices=[_slice("S1", "E1", "600917")],
        exit_allocations=[
            {
                "allocation_id": "A1",
                "entry_id": "E1",
                "entry_slice_id": "S1",
                "symbol": "600917",
                "allocated_quantity": 100,
            }
        ],
    )
    error_types = _error_types(errors)
    assert "entry_slice_symbol" in error_types
    assert "allocation_entry_symbol" in error_types
    assert "allocation_entry_slice_symbol" not in error_types


def test_allocated_quantity_over_remaining_is_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[
            _entry("E1", "600000", original_quantity=1000, remaining_quantity=100)
        ],
        entry_slices=[
            _slice("S1", "E1", "600000", original_quantity=600, remaining_quantity=0)
        ],
        exit_allocations=[
            _allocation("A1", "E1", "S1", "600000", allocated_quantity=900)
        ],
    )
    error_types = _error_types(errors)
    assert "entry_slice_allocation_quantity" in error_types


def test_invalid_allocated_quantity_is_reported():
    allocation = _allocation("A1", "E1", "S1", "600000", allocated_quantity=100)
    allocation["allocated_quantity"] = "abc"
    errors = find_exit_allocation_integrity_errors(
        position_entries=[_entry("E1", "600000")],
        entry_slices=[_slice("S1", "E1", "600000")],
        exit_allocations=[allocation],
    )
    error_types = _error_types(errors)
    assert "allocated_quantity" in error_types


def test_duplicate_ids_are_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[_entry("E1", "600000"), _entry("E1", "600000")],
        entry_slices=[_slice("S1", "E1", "600000"), _slice("S1", "E1", "600000")],
        exit_allocations=[
            _allocation("A1", "E1", "S1", "600000"),
            _allocation("A1", "E1", "S1", "600000"),
        ],
    )
    error_types = _error_types(errors)
    assert "duplicate_entry_id" in error_types
    assert "duplicate_entry_slice_id" in error_types
    assert "duplicate_allocation_id" in error_types


def test_remaining_over_original_bounds_is_reported():
    errors = find_exit_allocation_integrity_errors(
        position_entries=[
            _entry("E1", "600000", original_quantity=100, remaining_quantity=200)
        ],
        entry_slices=[],
        exit_allocations=[],
    )
    error_types = _error_types(errors)
    assert "entry_id_quantity_bounds" in error_types


def test_partial_allocation_matches_conservation():
    entries = [_entry("E1", "600000", original_quantity=1000, remaining_quantity=400)]
    slices = [
        _slice("S1", "E1", "600000", original_quantity=600, remaining_quantity=0),
        _slice("S2", "E1", "600000", original_quantity=400, remaining_quantity=400),
    ]
    allocations = [
        _allocation("A1", "E1", "S1", "600000", allocated_quantity=600),
    ]
    assert (
        find_exit_allocation_integrity_errors(
            position_entries=entries,
            entry_slices=slices,
            exit_allocations=allocations,
        )
        == []
    )
