"""Deterministic bounded-memory workload used by ranking_scale_fixture.sh."""

from __future__ import annotations

import json
import resource
import time
from datetime import date, timedelta

import polars as pl

from freshquant.backtest.clx.event_study import SplitPlan, SplitWindow
from freshquant.backtest.clx.ranking import (
    RankingConfig,
    SplitOutcomeStore,
    discover_and_freeze,
)


def main() -> None:
    days = []
    for year in (2022, 2023, 2024):
        start = date(year, 1, 1)
        days.extend(start + timedelta(days=index) for index in range(160))
    calendar = pl.DataFrame(
        {"trade_date": days, "session_no": list(range(1, len(days) + 1))},
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )
    plan = SplitPlan(
        (
            SplitWindow("TRAIN", days[0], days[159]),
            SplitWindow("VALIDATION", days[160], days[319]),
            SplitWindow("HOLDOUT", days[320], days[479]),
        )
    )
    rows = []
    sequence = 0
    for split_no, (split_id, base) in enumerate(
        (("TRAIN", 0), ("VALIDATION", 160), ("HOLDOUT", 320))
    ):
        for code_no in range(1, 201):
            code = f"{code_no:06d}"
            for local in range(5, 155, 5):
                reveal_date = days[base + local]
                occurrence = local % 5 + 1
                entrypoint = local % 7 + 1
                value = 0.004 + ((code_no + local + split_no) % 11) * 0.0004
                for model_id in (8, 13, 16):
                    sequence += 1
                    bit = 1 << (entrypoint - 1)
                    rows.append(
                        {
                            "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                            "signal_fact_id": f"scale-{sequence:09d}",
                            "code": code,
                            "reveal_date": reveal_date,
                            "expected_model_id": model_id,
                            "model_code": f"S{model_id:04d}",
                            "direction": 1,
                            "occurrence": occurrence,
                            "primary_entrypoint": entrypoint,
                            "primary_trigger_semantic": f"SCALE_TRIGGER_{entrypoint}",
                            "direction_base_trigger_mask": bit,
                            "synthetic_primary_mask": bit,
                            "concurrent_trigger_mask": bit,
                            "split_id": split_id,
                            "split_boundary_status": "ELIGIBLE",
                            "h5_status": "OK",
                            "h5_direction_adjusted_return": value,
                            "h5_mfe": value + 0.003,
                            "h5_mae": -0.002,
                        }
                    )
    outcomes = pl.DataFrame(rows, infer_schema_length=None)
    del rows
    config = RankingConfig(
        horizon=5,
        min_train_sample=10,
        min_validation_sample=10,
        min_train_density=0.0,
        min_validation_density=0.0,
        min_train_years=1,
        min_validation_years=1,
        min_events_per_year=3,
        max_train_fdr=1.0,
        max_validation_fdr=1.0,
        beam_width_per_stage=32,
        max_candidates_per_stage=1024,
        max_total_candidates=4096,
        max_seed_per_root=2,
        max_trigger_terms=2,
        jaccard_threshold=1.0,
        resonance_lookbacks=(0, 1, 3, 5),
    )
    started = time.perf_counter()
    result = discover_and_freeze(
        SplitOutcomeStore(outcomes),
        calendar,
        plan,
        config,
        source_identity={
            "event_set_id": "sha256:scale-event",
            "event_manifest_sha256": "sha256:scale-manifest",
        },
    )
    elapsed = time.perf_counter() - started
    rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    scale = result.search_audit["evaluation_scale"]
    assert scale["context_rows"] == 18_000
    assert scale["anchor_keys"] == 6_000
    assert scale["python_candidate_anchor_scans"] == 0
    assert result.search_audit["single_train_evaluated"] >= 100
    assert elapsed < 60.0
    assert rss_kib < 650_000
    print(
        json.dumps(
            {
                "status": "passed",
                "elapsed_seconds": round(elapsed, 6),
                "max_rss_kib": rss_kib,
                "single_candidates": result.search_audit["single_train_evaluated"],
                "frozen_candidates": len(result.rankings),
                **scale,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
