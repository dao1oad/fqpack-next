from __future__ import annotations

import pytest

from script.clx_target_hit.compute_stage1 import (
    HORIZONS,
    is_contract_complete,
    load_reused_parts,
    require_passed_checks,
    validate_reused_part,
)
import polars as pl


def test_partial_smoke_is_not_full_contract_completion() -> None:
    assert not is_contract_complete((5,), include_contains=True)
    assert not is_contract_complete(HORIZONS, include_contains=False)
    assert is_contract_complete(HORIZONS, include_contains=True)


def test_failed_stage1_checks_raise() -> None:
    with pytest.raises(AssertionError, match="model_count_ok"):
        require_passed_checks(
            {
                "model_count_ok": False,
                "all_passed": False,
            }
        )


def test_reuse_requires_every_requested_part(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="stage1_grid_h5.parquet"):
        load_reused_parts(
            tmp_path,
            prefix="stage1",
            horizons=HORIZONS,
            stages=("TRAIN", "VALIDATION"),
            include_contains=True,
        )


def test_reused_part_rejects_horizon_dimension_drift() -> None:
    frame = pl.DataFrame(
        {
            "model_code": ["S0000"],
            "stage": ["TRAIN"],
            "trigger_view": ["EXACT"],
            "trigger_key": ["1"],
            "filter_key": ["RAW"],
            "n": [1],
            "unique_dates": [1],
            "hit_n": [1],
            "first_hit_median": [1.0],
            "unhit_mean_return": [None],
            "net_mean_return": [0.02],
            "horizon": [10],
            "target_bps": [200],
            "hit_rate": [1.0],
            "wilson_lower": [0.2],
            "wilson_upper": [1.0],
            "profit_factor": [float("inf")],
        }
    )
    with pytest.raises(AssertionError, match="horizon values"):
        validate_reused_part(
            frame,
            horizon=5,
            stages=("TRAIN", "VALIDATION"),
            include_contains=True,
        )


def test_reused_part_is_validated_and_hashed(tmp_path) -> None:
    rows = []
    for model_index in range(18):
        for stage in ("TRAIN", "VALIDATION"):
            for trigger_view, trigger_key in (
                ("EXACT", "1"),
                ("COUNT", "1"),
                ("ALL", "ALL"),
                ("CONTAINS", "1"),
            ):
                for filter_key in ("RAW", "F7"):
                    for target in range(2, 31):
                        rows.append(
                            {
                                "model_code": f"S{model_index:04d}",
                                "stage": stage,
                                "trigger_view": trigger_view,
                                "trigger_key": trigger_key,
                                "filter_key": filter_key,
                                "n": 10,
                                "unique_dates": 5,
                                "hit_n": 5,
                                "first_hit_median": 2.0,
                                "unhit_mean_return": -0.01,
                                "net_mean_return": 0.01,
                                "horizon": 5,
                                "target_bps": target * 100,
                                "hit_rate": 0.5,
                                "wilson_lower": 0.2,
                                "wilson_upper": 0.8,
                                "profit_factor": 2.0,
                            }
                        )
    path = tmp_path / "stage1_grid_h5.parquet"
    pl.DataFrame(rows).write_parquet(path)
    frames, evidence = load_reused_parts(
        tmp_path,
        prefix="stage1",
        horizons=(5,),
        stages=("TRAIN", "VALIDATION"),
        include_contains=True,
    )
    assert len(frames[0]) == len(rows)
    assert evidence[0]["horizon"] == 5
    assert len(str(evidence[0]["sha256"])) == 64
