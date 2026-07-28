from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from script.clx_target_hit.build_event_universe import (  # noqa: E402
    AUDIT_STAGES,
    DEVELOPMENT_STAGES,
    EVENT_COLUMNS,
    attach_market_features,
    build_filter_pass_mask,
    build_universe,
    canonical_sha,
    compare_legacy_eligible,
    enrich_stock_features,
    load_events,
    map_bar_files,
    run,
    sha256_file,
    verify_audit_lock,
)


def _event(
    *,
    code: str,
    model: str,
    reveal_date: pd.Timestamp,
    entry_date: pd.Timestamp,
    raw_entry_open: float,
    revision: int = 1,
    direction: int = 1,
    entry_status: str = "EXECUTABLE",
    split_id: str = "TRAIN",
    boundary_status: str = "ELIGIBLE",
) -> dict[str, object]:
    return {
        "signal_fact_id": f"{code}-{model}-{reveal_date.date()}-{revision}",
        "code": code,
        "model_code": model,
        "direction": direction,
        "reveal_date": reveal_date,
        "revision_no": revision,
        "occurrence": 1,
        "primary_entrypoint": 1,
        "primary_trigger_semantic": "MODEL_STRUCTURAL",
        "concurrent_trigger_mask": 5,
        "dedup_group_size": 1,
        "entry_trade_date": entry_date,
        "entry_status": entry_status,
        "raw_entry_open": raw_entry_open,
        "split_id": split_id,
        "split_boundary_status": boundary_status,
        "quality_mask": 0,
    }


def _write_event_part(
    root: Path,
    *,
    bucket: int,
    year: int,
    rows: list[dict[str, object]],
) -> Path:
    path = (
        root
        / "code_buckets"
        / f"code_bucket={bucket:03d}"
        / "event_outcomes"
        / f"reveal_year={year}"
        / "part-00000.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path, pd.DataFrame, np.ndarray]:
    dates = pd.bdate_range("2018-06-01", periods=700)
    closes = np.linspace(8.0, 18.0, len(dates))
    raw_opens = np.full(len(dates), 5.0)
    amounts = np.arange(len(dates), dtype=float) * 1_000.0 + 1_000_000.0

    snapshot = tmp_path / "snapshot" / "bars"
    bar_path = snapshot / "trade_year=2018" / "code=000001" / "part.parquet"
    bar_path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "trade_date": dates,
            "qfq_open": closes,
            "qfq_high": closes * 1.01,
            "qfq_low": closes * 0.99,
            "qfq_close": closes,
            "raw_open": raw_opens,
            "raw_amount": amounts,
        }
    ).to_parquet(bar_path, index=False)

    event_root = tmp_path / "events" / "event-study"
    train_reveal = dates[248]
    validation_reveal = dates[450]
    train_rows = [
        _event(
            code="000001",
            model="S0000",
            reveal_date=train_reveal,
            entry_date=dates[249],
            raw_entry_open=5.0,
            revision=1,
            boundary_status="ELIGIBLE",
        ),
        _event(
            code="000001",
            model="S0000",
            reveal_date=train_reveal,
            entry_date=dates[249],
            raw_entry_open=5.0,
            revision=2,
            boundary_status="PURGED",
        ),
        _event(
            code="000001",
            model="S0002",
            reveal_date=train_reveal,
            entry_date=dates[249],
            raw_entry_open=5.0,
            direction=-1,
        ),
        _event(
            code="000001",
            model="S0003",
            reveal_date=train_reveal,
            entry_date=dates[249],
            raw_entry_open=5.0,
            entry_status="NON_TRADING",
        ),
    ]
    validation_rows = [
        _event(
            code="000001",
            model="S0001",
            reveal_date=validation_reveal,
            entry_date=dates[451],
            raw_entry_open=5.0,
            split_id="VALIDATION",
            boundary_status="EMBARGOED",
        )
    ]
    _write_event_part(
        event_root,
        bucket=1,
        year=int(train_reveal.year),
        rows=train_rows,
    )
    _write_event_part(
        event_root,
        bucket=1,
        year=int(validation_reveal.year),
        rows=validation_rows,
    )

    # If development discovery accidentally opens AUDIT, Parquet inspection fails.
    audit_path = (
        event_root
        / "code_buckets"
        / "code_bucket=001"
        / "event_outcomes"
        / "reveal_year=2024"
        / "part-00000.parquet"
    )
    audit_path.parent.mkdir(parents=True)
    audit_path.write_bytes(b"must-not-be-read-before-lock")

    index = pd.DataFrame(
        {
            "date": dates,
            "close": np.concatenate(
                [
                    np.full(100, 100.0),
                    np.linspace(100.0, 150.0, 300),
                    np.linspace(150.0, 90.0, 300),
                ]
            ),
        }
    )
    return event_root, snapshot, index, amounts


def test_development_read_keeps_boundary_rows_and_latest_revision(
    tmp_path: Path,
) -> None:
    event_root, _, _, _ = _fixture_inputs(tmp_path)

    events, metadata = load_events(event_root, DEVELOPMENT_STAGES)

    assert len(events) == 2
    assert set(events["split_boundary_status"]) == {"PURGED", "EMBARGOED"}
    assert events.loc[events["model_code"].eq("S0000"), "revision_no"].item() == 2
    assert metadata["superseded_revision_rows"] == 1
    assert metadata["non_eligible_rows_after_latest_revision"] == 2
    assert max(metadata["opened_reveal_years"]) <= 2023


def test_build_universe_recomputes_entry_features_and_f7_causally(
    tmp_path: Path,
) -> None:
    event_root, snapshot, index, amounts = _fixture_inputs(tmp_path)
    events, _ = load_events(event_root, DEVELOPMENT_STAGES)
    files = map_bar_files(snapshot, {"000001"})

    universe, checks = build_universe(events, files, index)

    assert set(EVENT_COLUMNS).issubset(universe.columns)
    train = universe.loc[universe["model_code"].eq("S0000")].iloc[0]
    validation = universe.loc[universe["model_code"].eq("S0001")].iloc[0]
    assert train["recomputed_entry_index"] == 249
    assert train["raw_entry_open_recomputed"] == 5.0
    assert np.isnan(train["qfq_ma250_reveal"])
    assert int(train["filter_pass_mask"]) & 64 == 0
    assert validation["stock_above_ma250"] > 0
    assert int(validation["filter_pass_mask"]) & 64 == 64
    assert train["amount_median_20"] == pytest.approx(np.median(amounts[228:248]))
    assert checks["stock"]["source_entry_date_mismatches"] == 0
    assert checks["market"]["future_market_feature_rows"] == 0
    assert checks["universe"]["f7_missing_ma250_pass_rows"] == 0


def test_filter_mask_uses_f1_to_f7_missing_fails() -> None:
    frame = pd.DataFrame(
        {
            "raw_entry_open_recomputed": [5.0, 5.0],
            "stock_return_20": [-0.01, -0.01],
            "stock_drawdown_20": [-0.10, -0.10],
            "stock_volatility_20": [0.03, 0.03],
            "stock_above_ma60": [0.0, 0.0],
            "market_return_20": [0.0, 0.0],
            "stock_above_ma250": [0.01, np.nan],
        }
    )

    assert build_filter_pass_mask(frame).tolist() == [127, 63]


def test_legacy_stock_features_use_stage_window_but_f7_uses_full_history(
    tmp_path: Path,
) -> None:
    dates = pd.bdate_range("2003-01-01", periods=330)
    reveal_position = int(np.searchsorted(dates, pd.Timestamp("2004-01-12")))
    reveal_date = dates[reveal_position]
    entry_date = dates[reveal_position + 1]
    close = np.linspace(1.0, 10.0, len(dates))
    bar_path = tmp_path / "bars" / "code=000001" / "part.parquet"
    bar_path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "trade_date": dates,
            "qfq_open": close,
            "qfq_high": close * 1.01,
            "qfq_low": close * 0.99,
            "qfq_close": close,
            "raw_open": np.full(len(dates), 5.0),
            "raw_amount": np.full(len(dates), 1_000_000.0),
        }
    ).to_parquet(bar_path, index=False)
    events = pd.DataFrame(
        [
            _event(
                code="000001",
                model="S0000",
                reveal_date=reveal_date,
                entry_date=entry_date,
                raw_entry_open=5.0,
            )
        ]
    )
    events["stage"] = "TRAIN"

    enriched, checks = enrich_stock_features(
        events,
        {"000001": [bar_path]},
    )

    assert checks["missing_feature_window_rows"] == 0
    assert pd.isna(enriched.loc[0, "stock_return_20"])
    assert pd.isna(enriched.loc[0, "stock_above_ma60"])
    assert np.isfinite(enriched.loc[0, "qfq_ma250_reveal"])
    assert enriched.loc[0, "stock_above_ma250"] > 0


def test_audit_read_requires_candidate_lock_before_discovery(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="candidate-lock"):
        verify_audit_lock(
            AUDIT_STAGES,
            tmp_path / "missing-lock.json",
            tmp_path / "missing-portfolio-lock.json",
        )


def _write_audit_locks(tmp_path: Path) -> tuple[Path, Path]:
    candidate_path = tmp_path / "candidate_lock.json"
    candidate = {
        "schema_version": "clx18-target-hit-candidate-lock-v1",
        "locked_at": "2026-07-28T00:00:00+00:00",
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "candidates": [{"candidate_id": "candidate-1"}],
    }
    candidate["lock_sha256"] = canonical_sha(candidate)
    candidate_path.write_text(
        json.dumps(candidate),
        encoding="utf-8",
    )
    portfolio_path = tmp_path / "portfolio_lock.json"
    portfolio = {
        "schema_version": "clx18-target-hit-portfolio-lock-v1",
        "locked_at": "2026-07-28T00:01:00+00:00",
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "winner": {"candidate_id": "candidate-1"},
        "inputs": {
            "candidate_lock_sha256": candidate["lock_sha256"],
            "candidate_lock_file_sha256": sha256_file(candidate_path),
        },
    }
    portfolio["lock_sha256"] = canonical_sha(portfolio)
    portfolio_path.write_text(
        json.dumps(portfolio),
        encoding="utf-8",
    )
    return candidate_path, portfolio_path


def test_audit_read_requires_valid_bound_candidate_and_portfolio_locks(
    tmp_path: Path,
) -> None:
    candidate_path, portfolio_path = _write_audit_locks(tmp_path)

    evidence = verify_audit_lock(
        AUDIT_STAGES,
        candidate_path,
        portfolio_path,
    )

    assert evidence is not None
    assert evidence["candidate_lock"]["lock_sha256"]
    assert evidence["portfolio_lock"]["lock_sha256"]
    assert evidence["portfolio_binds_candidate"] is True

    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    portfolio["inputs"]["candidate_lock_sha256"] = "drift"
    unsigned = dict(portfolio)
    unsigned.pop("lock_sha256")
    portfolio["lock_sha256"] = canonical_sha(unsigned)
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not bound"):
        verify_audit_lock(AUDIT_STAGES, candidate_path, portfolio_path)


def test_development_does_not_read_lock_files(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate_lock.json"
    portfolio_path = tmp_path / "portfolio_lock.json"
    candidate_path.write_text("{not-json", encoding="utf-8")
    portfolio_path.write_text("{not-json", encoding="utf-8")

    assert (
        verify_audit_lock(
            DEVELOPMENT_STAGES,
            candidate_path,
            portfolio_path,
        )
        is None
    )


def test_precomputed_index_history_is_retained_at_first_available_date() -> None:
    events = pd.DataFrame({"reveal_date": pd.to_datetime(["2005-01-04"])})
    index = pd.DataFrame(
        {
            "date": pd.to_datetime(["2005-01-04", "2005-01-05"]),
            "close": [1200.0, 1210.0],
            "market_return_20": [-0.0723, -0.0610],
            "market_regime": ["DOWN", "DOWN"],
            "segment_id": ["DOWN-0007", "DOWN-0007"],
        }
    )

    attached, checks = attach_market_features(events, index)

    assert attached.loc[0, "market_return_20"] == pytest.approx(-0.0723)
    assert attached.loc[0, "market_regime"] == "DOWN"
    assert attached.loc[0, "segment_id"] == "DOWN-0007"
    assert checks["feature_source"] == "PRECOMPUTED_CAUSAL_COLUMNS"


def test_legacy_comparison_includes_filter_pass_mask(tmp_path: Path) -> None:
    universe = pd.DataFrame(
        {
            "stage": ["TRAIN"],
            "model_code": ["S0000"],
            "code": ["000001"],
            "reveal_date": pd.to_datetime(["2019-01-02"]),
            "concurrent_trigger_mask": [5],
            "filter_pass_mask": [64],
            "split_boundary_status": ["ELIGIBLE"],
        }
    )
    legacy_path = tmp_path / "legacy.parquet"
    universe.drop(columns="split_boundary_status").to_parquet(legacy_path, index=False)

    exact = compare_legacy_eligible(universe, legacy_path, DEVELOPMENT_STAGES)
    drifted = universe.copy()
    drifted["filter_pass_mask"] = 0
    drift = compare_legacy_eligible(drifted, legacy_path, DEVELOPMENT_STAGES)

    assert exact["eligible_key_mask_set_exact"] is True
    assert exact["legacy_filter_pass_mask_mismatch_rows"] == 0
    assert drift["eligible_key_mask_set_exact"] is False
    assert drift["legacy_filter_pass_mask_mismatch_rows"] == 1


def test_run_writes_compatible_parquet_manifest_and_checks(tmp_path: Path) -> None:
    event_root, snapshot, index, _ = _fixture_inputs(tmp_path)
    index_path = tmp_path / "index.parquet"
    output = tmp_path / "result" / "event_universe.parquet"
    index.to_parquet(index_path, index=False)

    manifest = run(
        argparse.Namespace(
            stages="TRAIN,VALIDATION",
            event_root=event_root,
            snapshot_root=snapshot,
            index_path=index_path,
            output=output,
            candidate_lock=None,
            portfolio_lock=None,
            legacy_eligible=None,
        )
    )

    written = pd.read_parquet(output)
    assert set(EVENT_COLUMNS).issubset(written.columns)
    assert manifest["checks"]["all_passed"] is True
    assert output.with_suffix(".manifest.json").is_file()
    assert output.with_suffix(".checks.json").is_file()
