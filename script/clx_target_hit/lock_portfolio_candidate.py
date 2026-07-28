"""Lock the capital-portfolio champion before opening AUDIT.

This command reads only TRAIN/VALIDATION outcomes and the already immutable
statistical candidate lock.  It writes a self-hashed ``portfolio_lock.json``;
the final report later evaluates that same winner on AUDIT without reselecting.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .build_final_report import (
        DEFAULT_ROOT,
        PORTFOLIO_SELECTION_WINDOWS,
        build_group_index,
        candidate_subset,
        canonical_sha,
        json_value,
        load_lock,
        parquet_columns,
        required_event_columns,
        sha256_file,
        simulate_acceptance,
        utc_now,
        validate_candidate_lock_bindings,
        validate_pipeline_evidence,
        write_json,
    )
except ImportError:
    from build_final_report import (
        DEFAULT_ROOT,
        PORTFOLIO_SELECTION_WINDOWS,
        build_group_index,
        candidate_subset,
        canonical_sha,
        json_value,
        load_lock,
        parquet_columns,
        required_event_columns,
        sha256_file,
        simulate_acceptance,
        utc_now,
        validate_candidate_lock_bindings,
        validate_pipeline_evidence,
        write_json,
    )


def read_development_events(
    path: Path,
    candidates: list[dict[str, object]],
) -> pd.DataFrame:
    columns = required_event_columns(candidates, portfolio=True)
    missing = sorted(set(columns).difference(parquet_columns(path)))
    if missing:
        first_dates = [
            column for column in missing if column.endswith("_first_hit_date")
        ]
        if first_dates:
            raise AssertionError(
                "portfolio lock requires actual per-stock first-touch dates; "
                f"missing {first_dates[:3]}"
            )
        raise AssertionError(f"development outcomes missing columns: {missing}")
    events = pd.read_parquet(path, columns=columns)
    stages = set(events["stage"].astype(str))
    if stages - {"TRAIN", "VALIDATION"} or not stages:
        raise AssertionError(
            f"portfolio selection must read TRAIN/VALIDATION only, got {stages}"
        )
    for column in ("reveal_date", "entry_date"):
        events[column] = pd.to_datetime(events[column], errors="raise")
    for candidate in candidates:
        horizon = int(candidate["horizon"])
        target = int(candidate["target_bps"]) // 100
        events[f"h{horizon}_exit_date"] = pd.to_datetime(
            events[f"h{horizon}_exit_date"],
            errors="coerce",
        )
        events[f"r{target}_first_hit_date"] = pd.to_datetime(
            events[f"r{target}_first_hit_date"],
            errors="coerce",
        )
    return events


def select_portfolio_winner(summaries: pd.DataFrame) -> pd.Series:
    train = summaries.loc[summaries["stage"] == "TRAIN"].set_index("candidate_id")
    validation = summaries.loc[summaries["stage"] == "VALIDATION"].set_index(
        "candidate_id"
    )
    paired = train.join(
        validation,
        how="inner",
        lsuffix="_train",
        rsuffix="_validation",
        validate="one_to_one",
    )
    paired["score"] = np.minimum(
        paired["annualized_return_train"],
        paired["annualized_return_validation"],
    )
    best = float(paired["score"].max())
    near = paired.loc[paired["score"] >= best - 0.005].copy()
    return near.sort_values(
        [
            "target_bps_train",
            "horizon_train",
            "trades_validation",
            "filter_count_train",
            "score",
        ],
        ascending=[False, True, False, True, False],
        kind="stable",
    ).iloc[0]


def seal_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize exactly as the JSON writer does before computing the lock hash."""

    normalized = json_value(payload)
    if not isinstance(normalized, dict):
        raise TypeError("portfolio lock payload must normalize to an object")
    normalized["lock_sha256"] = canonical_sha(normalized)
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--development-events", type=Path, default=None)
    parser.add_argument("--candidate-lock", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    root = args.root
    development_path = args.development_events or root / "event_outcomes.parquet"
    candidate_lock_path = args.candidate_lock or root / "candidate_lock.json"
    output = args.output or root / "portfolio_lock.json"
    lock_payload, candidates, verified = load_lock(candidate_lock_path)
    if not verified:
        raise AssertionError("candidate_lock.json self-hash mismatch")
    stage1_path = root / "stage1_grid.parquet"
    pipeline_evidence = validate_pipeline_evidence(
        outcome_manifest_path=root / "event_manifest.json",
        stage1_manifest_path=root / "stage1_manifest.json",
        outcomes_path=development_path,
        grid_path=stage1_path,
        expected_stages=("TRAIN", "VALIDATION"),
    )
    validate_candidate_lock_bindings(
        lock_payload,
        development_sha256=str(pipeline_evidence["outcomes_sha256"]),
        stage1_sha256=str(pipeline_evidence["grid_sha256"]),
        pipeline_evidence=pipeline_evidence,
    )
    events = read_development_events(development_path, candidates)
    group_index = build_group_index(events)
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        for stage in ("TRAIN", "VALIDATION"):
            subset = candidate_subset(
                events,
                group_index,
                candidate,
                stage,
            )
            _, _, summary = simulate_acceptance(
                subset,
                candidate,
                annualization_window=PORTFOLIO_SELECTION_WINDOWS[stage],
            )
            rows.append({**candidate, "stage": stage, **summary})
    summaries = pd.DataFrame(rows)
    winner = select_portfolio_winner(summaries)
    winner_id = str(winner.name)
    winner_candidate = next(
        candidate
        for candidate in candidates
        if str(candidate["candidate_id"]) == winner_id
    )
    stage_summaries = {
        stage.lower(): summaries.loc[
            (summaries["candidate_id"] == winner_id) & (summaries["stage"] == stage)
        ]
        .iloc[0]
        .to_dict()
        for stage in ("TRAIN", "VALIDATION")
    }
    payload = {
        "schema_version": "clx18-target-hit-portfolio-lock-v1",
        "locked_at": utc_now(),
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "ranking": (
            "maximize min(TRAIN,VALIDATION) annualized return; within 0.5pp "
            "prefer higher R, shorter H, larger VALIDATION trade count, "
            "fewer filters"
        ),
        "contract": {
            "initial_capital": 5_000_000,
            "equal_slots": 40,
            "slot_cash_cost": 125_000,
            "daily_entry_limit": 5,
            "same_day_order": "exits before entries",
            "same_code_overlap": "prohibited while position remains open",
            "selection_annualization_windows": {
                stage: {
                    "start": window[0],
                    "end": window[1],
                    "inclusive_calendar_days": True,
                }
                for stage, window in PORTFOLIO_SELECTION_WINDOWS.items()
            },
        },
        "winner": {
            **winner_candidate,
            "selection_score": float(winner["score"]),
            "stage_summaries": stage_summaries,
        },
        "inputs": {
            "candidate_lock_sha256": lock_payload["lock_sha256"],
            "candidate_lock_file_sha256": sha256_file(candidate_lock_path),
            "development_events_sha256": sha256_file(development_path),
            "pipeline_evidence": pipeline_evidence,
        },
        "candidate_count": len(candidates),
    }
    payload = seal_payload(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, payload, indent=2)
    summaries.to_parquet(
        output.parent / "portfolio_development_summaries.parquet",
        index=False,
    )
    state_path = root / "run_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            phase=4,
            status="PORTFOLIO_CANDIDATE_LOCKED_AUDIT_SEALED",
            updated_at=utc_now(),
            portfolio_candidate_id=winner_id,
            portfolio_lock_sha256=payload["lock_sha256"],
            current_command="compute AUDIT outcomes after both immutable locks",
            next_step="open AUDIT once, evaluate fixed statistical and portfolio locks",
        )
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, state_path)
    print(
        json.dumps(
            {
                "portfolio_lock": str(output),
                "lock_sha256": payload["lock_sha256"],
                "winner_candidate_id": winner_id,
                "candidate_count": len(candidates),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
