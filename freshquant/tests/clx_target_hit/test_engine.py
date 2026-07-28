from __future__ import annotations

import numpy as np
import pandas as pd

from freshquant.backtest.clx_target_hit.engine import (
    CONTRACT,
    aggregate_grid,
    evaluate_events,
    f7_subset_check,
    validate_monotonicity,
)


def fixture_events() -> pd.DataFrame:
    base = np.linspace(10.0, 13.5, 90)
    return pd.DataFrame(
        [
            {
                "event_id": "S0000-A",
                "model_code": "S0000",
                "stage": "TRAIN",
                "f7_pass": True,
                "entry_open": 10.0,
                "future_highs": base,
                "future_closes": base - 0.05,
            },
            {
                "event_id": "S0000-B",
                "model_code": "S0000",
                "stage": "VALIDATION",
                "f7_pass": False,
                "entry_open": 10.0,
                "future_highs": np.full(90, 10.01),
                "future_closes": np.linspace(9.9, 9.0, 90),
            },
        ]
    )


def test_full_contract_grid_and_fee_aware_first_hit() -> None:
    result = evaluate_events(fixture_events())
    assert len(result) == 2 * 522
    assert set(result["horizon"]) == set(CONTRACT.horizons)
    assert set(result["target_bps"]) == set(CONTRACT.targets_bps)
    hit = result[
        (result.event_id == "S0000-A")
        & (result.horizon == 90)
        & (result.target_bps == 200)
    ].iloc[0]
    assert hit["hit"]
    assert 1 <= hit["first_hit_day"] <= 90


def test_hit_membership_monotonicity_and_subsets() -> None:
    result = evaluate_events(fixture_events())
    assert validate_monotonicity(result)["passed"]


def test_f7_is_raw_subset_and_missing_fails() -> None:
    events = fixture_events()
    events["f7_pass"] = events["f7_pass"].astype(object)
    events.loc[1, "f7_pass"] = np.nan
    check = f7_subset_check(events)
    assert check == {"passed": True, "raw_n": 2, "f7_n": 1, "violations": 0}


def test_aggregate_publishes_required_statistics() -> None:
    result = evaluate_events(fixture_events(), horizons=[5], targets_bps=[200])
    grid = aggregate_grid(result, ["model_code", "stage"])
    assert {
        "hit_rate",
        "n",
        "wilson_lower",
        "first_hit_median",
        "unhit_mean_return",
        "net_mean_return",
        "profit_factor",
    }.issubset(grid.columns)
