from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from freshquant.backtest.clx.event_study import (
    CORPORATE_ACTION_NOT_FULLY_LEDGERED,
    DEDUP_RULE,
    ENTRY_MISSING_BAR,
    HoldoutAccess,
    HoldoutAccessError,
    OUTCOME_MISSING_EXIT_BAR,
    OUTCOME_OK,
    SPLIT_ELIGIBLE,
    SPLIT_EMBARGOED,
    SPLIT_PURGED,
    SplitPlan,
    SplitWindow,
    _read_hashed_manifest,
    build_event_metrics_frame,
    build_event_outcomes_frame,
    build_event_study,
    verify_event_study,
)


def _calendar(count: int = 150) -> pl.DataFrame:
    start = date(2024, 1, 1)
    return pl.DataFrame(
        {
            "trade_date": [start + timedelta(days=index) for index in range(count)],
            "session_no": list(range(1, count + 1)),
        },
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )


def _plan(calendar: pl.DataFrame) -> SplitPlan:
    days = calendar["trade_date"].to_list()
    return SplitPlan(
        (
            SplitWindow("TRAIN", days[0], days[49]),
            SplitWindow("VALIDATION", days[50], days[99]),
            SplitWindow("HOLDOUT", days[100], days[149]),
        )
    )


def _bars(calendar: pl.DataFrame) -> pl.DataFrame:
    rows = []
    days = calendar["trade_date"].to_list()
    for code in ("000001", "000002", "000003"):
        for index, day in enumerate(days):
            if code == "000002" and index == 3:
                continue
            if code == "000003" and index == 5:
                continue
            raw_open = 100.0 + index
            rows.append(
                {
                    "code": code,
                    "trade_date": day,
                    "raw_open": raw_open,
                    "raw_high": raw_open + 2.0,
                    "raw_low": raw_open - 1.0,
                    "raw_close": raw_open + 1.0,
                    "raw_volume": 1000.0,
                    "adj_factor": 1.0 if index < 5 else 0.5,
                    "quality_mask": 0,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "code": pl.String,
            "trade_date": pl.Date,
            "raw_open": pl.Float64,
            "raw_high": pl.Float64,
            "raw_low": pl.Float64,
            "raw_close": pl.Float64,
            "raw_volume": pl.Float64,
            "adj_factor": pl.Float64,
            "quality_mask": pl.UInt16,
        },
    )


def _signal(
    fact_id: str,
    calendar: pl.DataFrame,
    reveal_index: int,
    *,
    code: str = "000001",
    signal_index: int | None = None,
    revision_no: int = 1,
    event_kind: str = "ADD",
    actionable: bool = True,
    direction: int = 1,
    model_id: int = 0,
    occurrence: int = 1,
    primary_entrypoint: int = 1,
    primary_semantic: str = "FRACTAL",
    base_mask: int = 1,
    synthetic_mask: int = 0,
) -> dict[str, object]:
    days = calendar["trade_date"].to_list()
    if signal_index is None:
        signal_index = reveal_index
    return {
        "signal_fact_id": fact_id,
        "code": code,
        "expected_model_id": model_id,
        "model_code": f"S{model_id:04d}",
        "signal_date": days[signal_index],
        "reveal_date": days[reveal_index],
        "revision_no": revision_no,
        "event_kind": event_kind,
        "direction": direction,
        "occurrence": occurrence,
        "primary_entrypoint": primary_entrypoint,
        "primary_trigger_semantic": primary_semantic,
        "direction_base_trigger_mask": base_mask,
        "synthetic_primary_mask": synthetic_mask,
        "concurrent_trigger_mask": base_mask | synthetic_mask,
        "actionable": actionable,
        "quality_mask": 0,
        "code_bucket": int(code[-2:]) % 8,
    }


def _signals(calendar: pl.DataFrame) -> pl.DataFrame:
    rows = [
        _signal("old-add", calendar, 2, signal_index=1),
        _signal("new-add", calendar, 2, signal_index=2),
        _signal(
            "winner-replace",
            calendar,
            2,
            signal_index=2,
            revision_no=2,
            event_kind="REPLACE",
            base_mask=5,
        ),
        _signal(
            "future-remove",
            calendar,
            4,
            signal_index=2,
            revision_no=3,
            event_kind="REMOVE",
            actionable=False,
        ),
        _signal("missing-entry", calendar, 2, code="000002", model_id=1),
        _signal(
            "missing-exit",
            calendar,
            2,
            code="000003",
            model_id=2,
            primary_entrypoint=3,
            primary_semantic="S0002_LEGACY_FRACTAL",
            base_mask=0,
            synthetic_mask=4,
        ),
        _signal("purged", calendar, 35, model_id=3),
        _signal("embargoed", calendar, 55, model_id=4),
        _signal("validation", calendar, 75, model_id=5, direction=-1),
        _signal("holdout", calendar, 125, model_id=6),
    ]
    return pl.DataFrame(rows, infer_schema_length=None)


def test_manual_raw_outcome_clock_dedup_and_corporate_action_disclosure() -> None:
    calendar = _calendar()
    outcomes, summary = build_event_outcomes_frame(
        _signals(calendar), _bars(calendar), calendar, _plan(calendar), run_id="run"
    )

    assert summary["actionable_duplicates_removed"] == 2
    assert summary["remove_revisions_ignored"] == 1
    assert DEDUP_RULE == summary["dedup_rule"]
    assert outcomes.filter(pl.col("event_kind") == "REMOVE").is_empty()
    row = outcomes.filter(pl.col("signal_fact_id") == "winner-replace").row(
        0, named=True
    )
    days = calendar["trade_date"].to_list()
    assert row["entry_trade_date"] == days[3]
    assert row["raw_entry_open"] == 103.0
    assert row["h1_exit_date"] == days[3]
    assert row["h3_exit_date"] == days[5]
    assert row["h1_status"] == OUTCOME_OK
    assert row["h3_status"] == OUTCOME_OK
    assert math.isclose(row["h3_raw_return"], 106.0 / 103.0 - 1.0)
    assert math.isclose(row["h3_direction_adjusted_return"], 106.0 / 103.0 - 1.0)
    assert math.isclose(row["h3_mfe"], 107.0 / 103.0 - 1.0)
    assert math.isclose(row["h3_mae"], 102.0 / 103.0 - 1.0)
    assert row["h3_adj_factor_jump_count"] == 1
    assert row["h3_corporate_action_status"] == "CORPORATE_ACTION_NOT_FULLY_LEDGERED"
    assert row["quality_mask"] & CORPORATE_ACTION_NOT_FULLY_LEDGERED


def test_missing_entry_and_fixed_exit_are_censored_without_rolling_or_fill() -> None:
    calendar = _calendar()
    outcomes, _ = build_event_outcomes_frame(
        _signals(calendar), _bars(calendar), calendar, _plan(calendar)
    )
    entry = outcomes.filter(pl.col("signal_fact_id") == "missing-entry").row(
        0, named=True
    )
    assert entry["entry_status"] == ENTRY_MISSING_BAR
    assert entry["raw_entry_open"] is None
    assert entry["h1_raw_return"] is None

    exit_row = outcomes.filter(pl.col("signal_fact_id") == "missing-exit").row(
        0, named=True
    )
    assert exit_row["h3_exit_date"] == calendar["trade_date"][5]
    assert exit_row["h3_status"] == OUTCOME_MISSING_EXIT_BAR
    assert exit_row["h3_raw_exit_close"] is None
    assert exit_row["h3_raw_return"] is None
    assert exit_row["h1_status"] == OUTCOME_OK


def test_twenty_session_purge_embargo_and_holdout_access_contract() -> None:
    calendar = _calendar()
    plan = _plan(calendar)
    outcomes, _ = build_event_outcomes_frame(
        _signals(calendar), _bars(calendar), calendar, plan
    )
    statuses = {
        row["signal_fact_id"]: row["split_boundary_status"]
        for row in outcomes.iter_rows(named=True)
    }
    assert statuses["winner-replace"] == SPLIT_ELIGIBLE
    assert statuses["purged"] == SPLIT_PURGED
    assert statuses["embargoed"] == SPLIT_EMBARGOED
    assert statuses["validation"] == SPLIT_ELIGIBLE
    assert statuses["holdout"] == SPLIT_ELIGIBLE

    with pytest.raises(HoldoutAccessError, match="HOLDOUT_LOCKED"):
        build_event_metrics_frame(
            outcomes,
            calendar,
            plan,
            requested_splits=("HOLDOUT",),
            bootstrap_replicates=20,
        )
    with pytest.raises(HoldoutAccessError, match="HOLDOUT_LOCKED"):
        build_event_metrics_frame(
            outcomes,
            calendar,
            plan,
            requested_splits=("HOLDOUT",),
            access=HoldoutAccess("freeze", True, 2),
            bootstrap_replicates=20,
        )
    revealed = build_event_metrics_frame(
        outcomes,
        calendar,
        plan,
        requested_splits=("HOLDOUT",),
        access=HoldoutAccess("freeze", True, 1),
        bootstrap_replicates=20,
    )
    assert set(revealed["split_id"]) == {"HOLDOUT"}


def test_segment_metrics_are_deterministic_and_exclude_boundary_guards() -> None:
    calendar = _calendar()
    plan = _plan(calendar)
    outcomes, _ = build_event_outcomes_frame(
        _signals(calendar), _bars(calendar), calendar, plan, run_id="stable-run"
    )
    first = build_event_metrics_frame(
        outcomes, calendar, plan, bootstrap_replicates=200
    )
    second = build_event_metrics_frame(
        outcomes, calendar, plan, bootstrap_replicates=200
    )
    assert first.equals(second)
    expected_segment_types = {
        "SINGLE_MODEL",
        "OCCURRENCE",
        "PRIMARY_TRIGGER_SEMANTIC",
        "DIRECTION_BASE_TRIGGER_MASK",
        "SYNTHETIC_PRIMARY_MASK",
        "CONCURRENT_TRIGGER_MASK",
        "MODEL_X_DIRECTION",
        "MODEL_X_DIRECTION_X_PRIMARY_TRIGGER",
        "MODEL_X_PRIMARY_TRIGGER_SEMANTIC",
        "MODEL_X_OCCURRENCE",
        "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER",
        "MODEL_X_CONCURRENT_TRIGGER_MASK",
        "MODEL_X_BASE_TRIGGER_ID",
        "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC",
        "MODEL_X_SYNTHETIC_TRIGGER_ID",
    }
    assert expected_segment_types == set(first["segment_type"])
    combined = first.filter(
        (pl.col("split_id") == "VALIDATION")
        & (pl.col("segment_type") == "MODEL_X_OCCURRENCE_X_PRIMARY_TRIGGER")
        & (pl.col("segment_value") == "S0005|occurrence=1|primary=FRACTAL")
        & (pl.col("horizon") == 1)
    ).row(0, named=True)
    assert combined["n_executable"] == 1
    direction = first.filter(
        (pl.col("split_id") == "VALIDATION")
        & (pl.col("segment_type") == "MODEL_X_DIRECTION")
        & (pl.col("segment_value") == "S0005|direction=-1")
        & (pl.col("horizon") == 1)
    ).row(0, named=True)
    assert direction["n_executable"] == 1
    synthetic = first.filter(
        (pl.col("segment_type") == "MODEL_X_SYNTHETIC_PRIMARY_SEMANTIC")
        & (pl.col("segment_value") == "S0002|primary=S0002_LEGACY_FRACTAL")
        & (pl.col("horizon") == 1)
    )
    assert synthetic.height == 1
    base_trigger_ids = set(
        first.filter(
            (pl.col("split_id") == "TRAIN")
            & (pl.col("segment_type") == "MODEL_X_BASE_TRIGGER_ID")
            & pl.col("segment_value").str.starts_with("S0000|")
            & (pl.col("horizon") == 1)
        )["segment_value"]
    )
    assert base_trigger_ids == {
        "S0000|entrypoint=1",
        "S0000|entrypoint=3",
    }
    model = first.filter(
        (pl.col("split_id") == "TRAIN")
        & (pl.col("segment_type") == "SINGLE_MODEL")
        & (pl.col("segment_value") == "S0003")
        & (pl.col("horizon") == 20)
    ).row(0, named=True)
    assert model["n_total"] == 1
    assert model["n_executable"] == 0
    assert model["n_purged_or_embargoed"] == 1
    assert model["mean"] is None
    assert model["signal_density"] == 0.0
    assert first["fdr_q_value"].drop_nulls().is_between(0.0, 1.0).all()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, SplitPlan]:
    calendar = _calendar()
    bars = _bars(calendar)
    signals = _signals(calendar)
    snapshot = tmp_path / "snapshot"
    signal_root = tmp_path / "signals"
    snapshot.mkdir()
    signal_root.mkdir()

    calendar_path = snapshot / "calendar/part-00000.parquet"
    calendar_path.parent.mkdir(parents=True)
    calendar.write_parquet(calendar_path)
    bar_metas = []
    for code, frame in bars.partition_by("code", as_dict=True).items():
        if isinstance(code, tuple):
            code = code[0]
        relative = f"bars/code={code}/part-00000.parquet"
        path = snapshot / relative
        path.parent.mkdir(parents=True)
        frame.write_parquet(path)
        bar_metas.append(
            {
                "path": relative,
                "sha256": _file_sha(path),
                "partition": {"code": code},
            }
        )
    snapshot_manifest = {
        "schema_version": "clx-mongo-snapshot-v1",
        "snapshot_id": "sha256:fixture-snapshot",
        "dataset": {
            "calendar_file": {
                "path": "calendar/part-00000.parquet",
                "sha256": _file_sha(calendar_path),
            },
            "bar_files": sorted(bar_metas, key=lambda item: item["path"]),
        },
    }
    snapshot_manifest_path = snapshot / "manifest.json"
    snapshot_manifest_path.write_text(
        json.dumps(snapshot_manifest, sort_keys=True), encoding="utf-8"
    )
    (snapshot / "manifest.sha256").write_text(_file_sha(snapshot_manifest_path) + "\n")

    facts_path = signal_root / "facts/part-00000.parquet"
    facts_path.parent.mkdir(parents=True)
    signals.write_parquet(facts_path)
    signal_manifest = {
        "state": "COMPLETE",
        "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "signal_set_id": "sha256:fixture-signals",
        "artifacts": [
            {
                "dataset": "signal_revisions",
                "path": "facts/part-00000.parquet",
                "file_sha256": _file_sha(facts_path),
            }
        ],
    }
    signal_manifest_path = signal_root / "manifest.json"
    signal_manifest_path.write_text(
        json.dumps(signal_manifest, sort_keys=True), encoding="utf-8"
    )
    (signal_root / "manifest.sha256").write_text(_file_sha(signal_manifest_path) + "\n")
    return snapshot, signal_root, _plan(calendar)


def test_artifact_build_verify_and_manifest_hash_compatibility(tmp_path: Path) -> None:
    snapshot, signal_root, plan = _write_inputs(tmp_path)
    result = build_event_study(
        snapshot,
        signal_root,
        tmp_path / "events",
        plan,
        bootstrap_replicates=20,
    )
    assert result == verify_event_study(tmp_path / "events")
    assert result["event_outcomes"] == 7
    assert result["holdout_metrics_materialized"] is False

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    payload = {"snapshot_id": "legacy"}
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # Recompute after removing the hash, matching the legacy canonical contract.
    unhashed = {"snapshot_id": "legacy"}
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(unhashed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (legacy / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest, recorded = _read_hashed_manifest(legacy, kind="snapshot")
    assert manifest["snapshot_id"] == "legacy"
    assert recorded == payload["manifest_sha256"]


def _artifact_frame(root: Path, dataset: str) -> pl.DataFrame:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    frames = [
        pl.read_parquet(root / item["path"])
        for item in manifest["artifacts"]
        if item["dataset"] == dataset
    ]
    return pl.concat(frames, how="vertical") if frames else pl.DataFrame()


def test_bucket_resume_is_value_equivalent_and_manifest_deterministic(
    tmp_path: Path,
) -> None:
    snapshot, signal_root, plan = _write_inputs(tmp_path)
    interrupted_root = tmp_path / "events-resumed"
    interrupted = build_event_study(
        snapshot,
        signal_root,
        interrupted_root,
        plan,
        bootstrap_replicates=50,
        max_buckets=1,
    )
    assert interrupted["state"] == "INCOMPLETE"
    assert interrupted["completed_buckets"] == 1
    assert not (interrupted_root / "manifest.sha256").exists()
    stale_staging = (
        interrupted_root / "code_buckets/.code_bucket=999.staging-dead-process"
    )
    stale_staging.mkdir()
    (stale_staging / "partial.parquet").write_bytes(b"partial")
    resumed = build_event_study(
        snapshot,
        signal_root,
        interrupted_root,
        plan,
        bootstrap_replicates=50,
        resume=True,
    )
    assert not stale_staging.exists()
    fresh_root = tmp_path / "events-fresh"
    fresh = build_event_study(
        snapshot,
        signal_root,
        fresh_root,
        plan,
        bootstrap_replicates=50,
    )
    assert resumed == fresh
    assert (interrupted_root / "manifest.json").read_bytes() == (
        fresh_root / "manifest.json"
    ).read_bytes()

    calendar = _calendar()
    legacy_outcomes, _ = build_event_outcomes_frame(
        _signals(calendar),
        _bars(calendar),
        calendar,
        plan,
        run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
    )
    legacy_metrics = build_event_metrics_frame(
        legacy_outcomes, calendar, plan, bootstrap_replicates=50
    )
    streamed_outcomes = _artifact_frame(interrupted_root, "event_outcomes").sort(
        [
            "reveal_date",
            "code",
            "expected_model_id",
            "direction",
            "signal_fact_id",
        ]
    )
    streamed_metrics = _artifact_frame(interrupted_root, "event_metrics")
    assert_frame_equal(streamed_outcomes, legacy_outcomes, check_exact=True)
    assert_frame_equal(streamed_metrics, legacy_metrics, check_exact=True)

    manifest = json.loads(
        (interrupted_root / "manifest.json").read_text(encoding="utf-8")
    )
    memory_contract = manifest["memory_contract"]
    assert memory_contract["bars"]["full_market_python_bar_map"] is False
    assert memory_contract["bars"]["max_materialized_bar_rows_per_code"] <= 150
    assert memory_contract["outcomes"] == "PARQUET_BUCKETS_NOT_FULL_MARKET_PYTHON_ROWS"
    assert memory_contract["floating_point_order"] == (
        "LEGACY_REVEAL_CODE_MODEL_DIRECTION_FACT"
    )
