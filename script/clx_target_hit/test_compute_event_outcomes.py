from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).with_name("compute_event_outcomes.py")
SPEC = importlib.util.spec_from_file_location("compute_event_outcomes", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_failed_contract_checks_raise() -> None:
    with pytest.raises(AssertionError, match="source_row_count_unchanged"):
        MODULE.require_passed_checks(
            {
                "source_row_count_unchanged": False,
                "all_passed": False,
            }
        )


def test_calendar_formula_split_mask_is_available_as_a_diagnostic() -> None:
    calendar = pd.bdate_range("2019-10-01", "2024-04-01").to_numpy(
        dtype="datetime64[ns]"
    )
    validation = int(
        np.searchsorted(calendar, np.datetime64("2020-01-01"), side="left")
    )
    audit = int(np.searchsorted(calendar, np.datetime64("2024-01-01"), side="left"))
    horizon = 20
    positions = np.asarray(
        [
            validation - horizon - 1,
            validation - horizon,
            validation + horizon - 1,
            validation + horizon,
            audit - horizon - 1,
            audit - horizon,
            audit + horizon - 1,
            audit + horizon,
        ]
    )
    stages = np.asarray(
        [
            "TRAIN",
            "TRAIN",
            "VALIDATION",
            "VALIDATION",
            "VALIDATION",
            "VALIDATION",
            "AUDIT",
            "AUDIT",
        ]
    )
    eligible = MODULE.calendar_formula_split_mask(
        stages,
        calendar[positions],
        calendar,
        horizon,
    )
    assert eligible.tolist() == [True, False, False, True, True, False, False, True]


def test_calendar_formula_split_mask_rejects_non_calendar_reveal() -> None:
    calendar = pd.bdate_range("2019-01-01", "2024-02-01").to_numpy(
        dtype="datetime64[ns]"
    )
    with pytest.raises(AssertionError, match="absent from the calendar"):
        MODULE.calendar_formula_split_mask(
            np.asarray(["TRAIN"]),
            np.asarray([np.datetime64("2019-01-05")], dtype="datetime64[ns]"),
            calendar,
            5,
        )


def test_actual_stock_exit_crossing_boundary_is_purged() -> None:
    calendar = pd.bdate_range("2019-10-01", "2024-04-01").to_numpy(
        dtype="datetime64[ns]"
    )
    stages = np.asarray(["TRAIN", "TRAIN", "VALIDATION", "AUDIT"])
    reveal = np.asarray(
        [
            np.datetime64("2019-12-02"),
            np.datetime64("2019-12-02"),
            MODULE.embargo_start(calendar, np.datetime64("2020-01-01"), 5),
            MODULE.embargo_start(calendar, np.datetime64("2024-01-01"), 5),
        ],
        dtype="datetime64[ns]",
    )
    exit_dates = np.asarray(
        [
            np.datetime64("2019-12-31"),
            np.datetime64("2020-01-02"),
            np.datetime64("2024-01-02"),
            np.datetime64("2024-02-01"),
        ],
        dtype="datetime64[ns]",
    )
    eligible = MODULE.split_eligible_mask(
        stages,
        reveal,
        exit_dates,
        calendar,
        5,
    )
    assert eligible.tolist() == [True, False, False, True]
