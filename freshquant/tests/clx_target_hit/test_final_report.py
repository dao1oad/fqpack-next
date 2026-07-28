from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest

from script.clx_target_hit.build_final_report import (
    HORIZONS,
    PORTFOLIO_SELECTION_WINDOWS,
    TARGETS,
    Candidate,
    audit_gate_evidence,
    canonical_sha,
    compact_grid_payload,
    date_block_bootstrap,
    load_portfolio_lock,
    portfolio_equity_curve,
    simulate_acceptance,
    universe_lineage_identity,
    validate_candidate_lock_bindings,
    validate_portfolio_lock_bindings,
    write_json,
)
from script.clx_target_hit.compute_event_outcomes import enrich_code
from script.clx_target_hit.lock_portfolio_candidate import (
    seal_payload,
    select_portfolio_winner,
)
from script.clx_target_hit.select_and_challenge import mark_phase2, mark_phase3


def candidate() -> Candidate:
    return {
        "candidate_id": "candidate-a",
        "model_code": "S0000",
        "trigger_view": "EXACT",
        "trigger_key": "1",
        "trigger_label": "模型结构",
        "required_filter_mask": 0,
        "filter_key": "RAW",
        "filter_count": 0,
        "horizon": 5,
        "target_bps": 200,
        "source_phase": "PHASE1",
    }


def event(
    event_id: str,
    code: str,
    reveal_date: str,
    entry_date: str,
    exit_date: str,
    *,
    amount: float = 1_000_000,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "model_code": "S0000",
        "code": code,
        "reveal_date": pd.Timestamp(reveal_date),
        "entry_date": pd.Timestamp(entry_date),
        "stage": "TRAIN",
        "year": 2019,
        "quarter": "2019Q1",
        "market_regime": "UP",
        "segment_id": "SEG1",
        "concurrent_trigger_mask": 1,
        "filter_pass_mask": 0,
        "amount_median_20": amount,
        "qfq_entry_open_recomputed": 10.0,
        "h5_purged": True,
        "h5_exit_date": pd.Timestamp(exit_date),
        "h5_timeout_net": -0.01,
        "r2_first_hit_day": 2,
        "r2_first_hit_date": pd.Timestamp(exit_date),
    }


def test_outcome_keeps_actual_stock_first_touch_date() -> None:
    dates = pd.bdate_range("2018-01-02", periods=92)
    # Removing a stock session makes market-calendar offset an invalid proxy.
    dates = dates.delete(1)
    highs = np.full(len(dates), 10.0)
    highs[2:] = 10.30
    bars = pd.DataFrame(
        {
            "trade_date": dates,
            "qfq_open": 10.0,
            "qfq_high": highs,
            "qfq_close": 10.0,
        }
    )
    group = pd.DataFrame(
        [
            {
                "code": "000001",
                "recomputed_entry_index": 0,
                "entry_date": dates[0],
                "qfq_entry_open_recomputed": 10.0,
                "reveal_date": dates[0] - pd.Timedelta(days=1),
                "stage": "TRAIN",
            }
        ]
    )
    result = enrich_code(group, bars, dates.to_numpy(dtype="datetime64[ns]"))
    assert result.loc[0, "r2_first_hit_day"] == 3
    assert result.loc[0, "r2_first_hit_date"] == dates[2]


def test_date_block_bootstrap_is_reproducible() -> None:
    dates = pd.Series(
        pd.to_datetime(["2020-01-01"] * 3 + ["2020-01-02"] * 2 + ["2020-01-03"])
    )
    hit = np.asarray([1, 1, 0, 0, 1, 1], dtype=bool)
    first = date_block_bootstrap(dates, hit, samples=300, seed=7)
    second = date_block_bootstrap(dates, hit, samples=300, seed=7)
    assert first == second
    assert 0 <= first[0] <= first[1] <= 1


def test_phase3_triple_must_beat_strongest_pair_parent() -> None:
    common = {
        "base_candidate_id": "base",
        "model_code": "S0000",
        "trigger_view": "EXACT",
        "trigger_key": "1",
        "trigger_label": "模型结构",
        "filter_key": "F1+F2",
        "filter_count": 2,
        "horizon": 20,
        "target_bps": 500,
        "source_phase": "PHASE3",
        "n_train": 400,
        "n_validation": 200,
        "net_mean_return_train": 0.02,
        "net_mean_return_validation": 0.02,
        "year_hit_rates_json_train": '{"2018": 0.6, "2019": 0.6}',
        "year_hit_rates_json_validation": '{"2021": 0.6, "2022": 0.6}',
        "regime_hit_rates_json_train": '{"UP": 0.6, "DOWN": 0.6}',
        "regime_hit_rates_json_validation": '{"UP": 0.6, "DOWN": 0.6}',
    }
    # Pair mask 3 is stronger than the triple child mask 7.
    pair_parent = {
        **common,
        "required_filter_mask": 3,
        "wilson_lower_train": 0.60,
        "wilson_lower_validation": 0.60,
    }
    other_parents = [
        {
            **common,
            "required_filter_mask": mask,
            "wilson_lower_train": 0.50,
            "wilson_lower_validation": 0.50,
        }
        for mask in (5, 6)
    ]
    child = {
        **common,
        "required_filter_mask": 7,
        "filter_key": "F1+F2+F3",
        "filter_count": 3,
        "wilson_lower_train": 0.58,
        "wilson_lower_validation": 0.58,
    }
    phase2 = pd.DataFrame(other_parents)
    result = mark_phase3(pd.DataFrame([pair_parent, child]), phase2)
    assert not bool(result.loc[result["required_filter_mask"] == 7, "passed"].iloc[0])


def test_phase2_requires_train_and_validation_net_mean_non_degradation() -> None:
    common = {
        "base_candidate_id": "base",
        "n_train": 400,
        "n_validation": 200,
        "year_count_train": 4,
        "year_count_validation": 3,
        "regime_count_train": 2,
        "regime_count_validation": 2,
        "year_hit_rates_json_train": '{"2018": 0.6, "2019": 0.6}',
        "year_hit_rates_json_validation": '{"2021": 0.6, "2022": 0.6}',
        "regime_hit_rates_json_train": '{"UP": 0.6, "DOWN": 0.6}',
        "regime_hit_rates_json_validation": '{"UP": 0.6, "DOWN": 0.6}',
    }
    baseline = {
        **common,
        "required_filter_mask": 0,
        "wilson_lower_train": 0.50,
        "wilson_lower_validation": 0.50,
        "net_mean_return_train": 0.02,
        "net_mean_return_validation": 0.02,
    }
    child = {
        **common,
        "required_filter_mask": 1,
        "wilson_lower_train": 0.55,
        "wilson_lower_validation": 0.55,
        "net_mean_return_train": 0.01,
        "net_mean_return_validation": 0.02,
    }
    result = mark_phase2(pd.DataFrame([baseline, child]))
    assert not bool(result.loc[result["required_filter_mask"] == 1, "passed"].iloc[0])


def test_portfolio_same_day_exit_precedes_entry_and_daily_cap() -> None:
    rows = [
        event("A", "000001", "2019-01-01", "2019-01-02", "2019-01-03"),
        event("B", "000001", "2019-01-02", "2019-01-03", "2019-01-04"),
    ]
    trades, rejections, summary = simulate_acceptance(
        pd.DataFrame(rows),
        candidate(),
    )
    assert len(trades) == 2
    assert summary["overlap_removed"] == 0
    assert rejections.empty

    crowded = pd.DataFrame(
        [
            event(
                f"C{index}",
                f"{index + 2:06d}",
                "2019-02-01",
                "2019-02-04",
                "2019-02-05",
                amount=10_000_000 - index,
            )
            for index in range(6)
        ]
    )
    crowded_trades, crowded_rejections, _ = simulate_acceptance(
        crowded,
        candidate(),
    )
    assert len(crowded_trades) == 5
    assert (crowded_rejections["reason"] == "DAILY_SIGNAL_LIMIT").sum() == 1


def test_portfolio_selection_annualizes_on_fixed_stage_window() -> None:
    rows = pd.DataFrame(
        [event("A", "000001", "2019-01-01", "2019-01-02", "2019-01-03")]
    )
    _, _, summary = simulate_acceptance(
        rows,
        candidate(),
        annualization_window=PORTFOLIO_SELECTION_WINDOWS["TRAIN"],
    )
    start, end = PORTFOLIO_SELECTION_WINDOWS["TRAIN"]
    days = (end - start).days + 1
    ending_equity = cast(float, summary["ending_equity"])
    expected = (ending_equity / 5_000_000) ** (365.25 / days) - 1
    assert summary["annualization_basis"] == "FIXED_STAGE_WINDOW"
    assert summary["annualization_days"] == days
    assert summary["annualized_return"] == pytest.approx(expected)


def test_portfolio_lock_hashes_the_normalized_json_payload(tmp_path: Path) -> None:
    payload = seal_payload(
        {
            "schema_version": "clx18-target-hit-portfolio-lock-v1",
            "profit_factor": float("inf"),
            "missing_metric": float("nan"),
            "locked_at": pd.Timestamp("2026-01-02T03:04:05Z"),
        }
    )
    path = tmp_path / "portfolio_lock.json"
    write_json(path, payload, indent=2)
    reloaded, verified = load_portfolio_lock(path)
    assert verified
    assert reloaded["profit_factor"] is None
    assert reloaded["missing_metric"] is None


def test_portfolio_curve_marks_open_positions_at_daily_qfq_close(
    tmp_path: Path,
) -> None:
    rows = pd.DataFrame(
        [event("A", "000001", "2019-01-01", "2019-01-02", "2019-01-03")]
    )
    trades, _, _ = simulate_acceptance(rows, candidate())
    bars_dir = tmp_path / "bars" / "code=000001"
    bars_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2019-01-02", "2019-01-03"]),
            "qfq_close": [9.0, 10.3],
        }
    ).to_parquet(bars_dir / "part.parquet", index=False)
    calendar = tmp_path / "calendar.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2019-01-02", "2019-01-03"])}).to_parquet(
        calendar, index=False
    )
    curve = portfolio_equity_curve(
        trades,
        bars_root=tmp_path / "bars",
        calendar_path=calendar,
    )
    expected_liquidation = trades.loc[0, "quantity"] * 9.0 * (1 - 0.0002)
    expected_equity = 5_000_000 - trades.loc[0, "slot_capital"] + expected_liquidation
    assert curve.loc[0, "equity"] == expected_equity
    assert curve["drawdown"].min() < 0
    assert curve.loc[1, "equity"] == 5_002_500


def test_universe_lineage_ignores_stage_specific_event_paths() -> None:
    source_manifest: dict[str, object] = {
        "inputs": {
            "event_root": "/sealed/events",
            "event_manifest": {"sha256": "event-sha"},
            "snapshot_root": "/sealed/snapshot/bars",
            "snapshot_manifest": {"sha256": "snapshot-sha"},
            "index": {"sha256": "index-sha"},
        }
    }
    development: dict[str, object] = {
        "events_path": "event_universe.parquet",
        "source_manifest": source_manifest,
    }
    audit: dict[str, object] = {
        "events_path": "event_universe_audit.parquet",
        "source_manifest": source_manifest,
    }
    assert universe_lineage_identity(development) == universe_lineage_identity(audit)
    audit_source_manifest = cast(
        dict[str, object],
        json.loads(json.dumps(source_manifest)),
    )
    audit["source_manifest"] = audit_source_manifest
    audit_inputs = cast(dict[str, object], audit_source_manifest["inputs"])
    audit_index = cast(dict[str, object], audit_inputs["index"])
    audit_index["sha256"] = "different"
    assert universe_lineage_identity(development) != universe_lineage_identity(audit)


def test_audit_gate_binds_both_locks_before_universe_read() -> None:
    candidate_lock: dict[str, object] = {
        "locked_at": "2026-01-01T00:00:00Z",
        "lock_sha256": "candidate-sha",
    }
    portfolio_lock: dict[str, object] = {
        "locked_at": "2026-01-01T01:00:00Z",
        "lock_sha256": "portfolio-sha",
    }
    portfolio_binding: dict[str, object] = {
        "lock_sha256": "portfolio-sha",
        "audit_read": False,
    }
    manifest: dict[str, object] = {
        "contract": {
            "universe": {
                "source_manifest": {
                    "generated_at": "2026-01-01T02:00:00Z",
                    "audit_gate": {
                        "candidate_lock": {
                            "lock_sha256": "candidate-sha",
                            "audit_read": False,
                        },
                        "portfolio_lock": portfolio_binding,
                        "portfolio_binds_candidate": True,
                    },
                }
            }
        }
    }
    evidence = audit_gate_evidence(manifest, candidate_lock, portfolio_lock)
    assert evidence["passed"]
    portfolio_binding["lock_sha256"] = "drift"
    assert not audit_gate_evidence(manifest, candidate_lock, portfolio_lock)["passed"]


def test_final_lock_bindings_reject_drift() -> None:
    candidate_inputs: dict[str, object] = {
        "development_outcomes_sha256": "events",
        "stage1_grid_sha256": "grid",
    }
    candidate_lock: dict[str, object] = {
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "inputs": candidate_inputs,
    }
    validate_candidate_lock_bindings(
        candidate_lock,
        development_sha256="events",
        stage1_sha256="grid",
    )
    candidate_inputs["stage1_grid_sha256"] = "drift"
    with pytest.raises(AssertionError, match="stage1 grid"):
        validate_candidate_lock_bindings(
            candidate_lock,
            development_sha256="events",
            stage1_sha256="grid",
        )

    portfolio_lock: dict[str, object] = {
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "inputs": {
            "candidate_lock_sha256": "candidate",
            "development_events_sha256": "events",
        },
    }
    validate_portfolio_lock_bindings(
        portfolio_lock,
        candidate_lock_sha256="candidate",
        development_sha256="events",
    )
    portfolio_lock["audit_read"] = True
    with pytest.raises(AssertionError, match="AUDIT"):
        validate_portfolio_lock_bindings(
            portfolio_lock,
            candidate_lock_sha256="candidate",
            development_sha256="events",
        )


def test_compact_report_grid_is_one_complete_heatmap() -> None:
    rows = []
    for model in ("S0000", "S0001"):
        for horizon in HORIZONS:
            for target in TARGETS:
                rows.append(
                    {
                        "model_code": model,
                        "stage": "VALIDATION",
                        "trigger_view": "EXACT",
                        "trigger_key": "1",
                        "filter_key": "RAW",
                        "horizon": horizon,
                        "target_bps": target * 100,
                    }
                )
    compact, facets, selection = compact_grid_payload(
        pd.DataFrame(rows),
        {"practical_robust": [{"model_code": "S0001", "trigger_key": "1"}]},
    )
    assert len(compact) == 522
    assert facets["model_code"] == ["S0000", "S0001"]
    assert selection["model_code"] == "S0001"


def test_portfolio_lock_compares_stage_annualized_returns() -> None:
    rows = []
    for candidate_id, annualized, totals in (
        ("A", (0.03, 0.08), (0.50, 0.10)),
        ("B", (0.05, 0.05), (0.20, 0.05)),
    ):
        for stage, annual, total in zip(
            ("TRAIN", "VALIDATION"),
            annualized,
            totals,
            strict=True,
        ):
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "stage": stage,
                    "annualized_return": annual,
                    "total_return": total,
                    "target_bps": 500,
                    "horizon": 20,
                    "trades": 200,
                    "filter_count": 1,
                }
            )
    assert select_portfolio_winner(pd.DataFrame(rows)).name == "B"


def test_final_report_cli_runs_on_compact_real_schema_fixture(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    output = tmp_path / "output"
    root.mkdir()
    candidate_record = candidate()
    lock = {
        "schema_version": "clx18-target-hit-candidate-lock-v1",
        "locked_at": "2024-01-01T00:00:00+00:00",
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "ranking": "fixture",
        "categories": [
            {"category": "LITERAL_HIGHEST", "candidate_id": "candidate-a"},
            {"category": "PRACTICAL_ROBUST", "candidate_id": "candidate-a"},
            {"category": "MODEL_S0000", "candidate_id": "candidate-a"},
            *[
                {
                    "category": f"TARGET_R{target}",
                    "candidate_id": "candidate-a",
                }
                for target in TARGETS
            ],
            *[
                {
                    "category": f"HORIZON_H{horizon}",
                    "candidate_id": "candidate-a",
                }
                for horizon in HORIZONS
            ],
        ],
        "candidates": [candidate_record],
        "inputs": {},
    }
    event_rows = []
    for stage, dates in {
        "TRAIN": ("2018-01-02", "2018-01-03"),
        "VALIDATION": ("2021-01-04", "2021-01-05"),
        "AUDIT": ("2025-01-02", "2025-01-03"),
    }.items():
        for index, date in enumerate(dates):
            row = event(
                f"{stage}-{index}",
                f"{index + 1:06d}",
                date,
                date,
                date,
            )
            row["stage"] = stage
            row["r2_first_hit_day"] = 1 if index == 0 else 0
            row["r2_first_hit_date"] = pd.Timestamp(date) if index == 0 else pd.NaT
            event_rows.append(row)
    events = pd.DataFrame(event_rows)
    events.loc[events["stage"] != "AUDIT"].to_parquet(
        root / "event_outcomes.parquet",
        index=False,
    )
    events.loc[events["stage"] == "AUDIT"].to_parquet(
        root / "event_outcomes_audit.parquet",
        index=False,
    )

    lower = 0.09452865480086614
    grid_rows = []
    for stage in ("TRAIN", "VALIDATION", "AUDIT"):
        for horizon in HORIZONS:
            for target in TARGETS:
                grid_rows.append(
                    {
                        "model_code": "S0000",
                        "stage": stage,
                        "trigger_view": "EXACT",
                        "trigger_key": "1",
                        "filter_key": "RAW",
                        "horizon": horizon,
                        "target_bps": target * 100,
                        "n": 2,
                        "unique_dates": 2,
                        "hit_n": 1,
                        "hit_rate": 0.5,
                        "wilson_lower": lower,
                        "wilson_upper": 1 - lower,
                        "first_hit_median": 1.0,
                        "unhit_mean_return": -0.01,
                        "net_mean_return": (target / 100 - 0.01) / 2,
                        "profit_factor": target,
                    }
                )
    grid = pd.DataFrame(grid_rows)
    grid.loc[grid["stage"] != "AUDIT"].to_parquet(
        root / "stage1_grid.parquet",
        index=False,
    )
    grid.loc[grid["stage"] == "AUDIT"].to_parquet(
        root / "audit_grid.parquet",
        index=False,
    )
    from script.clx_target_hit.build_final_report import (
        sha256_file,
        validate_pipeline_evidence,
    )

    source_manifest = {
        "inputs": {
            "event_root": "/sealed/events",
            "event_manifest": {"sha256": "event-sha"},
            "snapshot_root": "/sealed/snapshot/bars",
            "snapshot_manifest": {"sha256": "snapshot-sha"},
            "index": {"sha256": "index-sha"},
        }
    }
    universe = {
        "events_path": "event_universe.parquet",
        "selection": "fixture",
        "requested_stages": ["TRAIN", "VALIDATION"],
        "source_manifest": source_manifest,
    }
    audit_universe = {
        **universe,
        "events_path": "event_universe_audit.parquet",
        "requested_stages": ["AUDIT"],
        "source_manifest": json.loads(json.dumps(source_manifest)),
    }
    contract = {
        "universe": universe,
        "purge_embargo": {"leading": "per-H", "trailing": "per-H"},
    }
    (root / "event_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "clx18-target-hit-events-v1",
                "generated_at": "2024-01-01T12:00:00+00:00",
                "contract": contract,
                "outputs": [{"sha256": sha256_file(root / "event_outcomes.parquet")}],
                "checks": {"all_passed": True},
            }
        ),
        encoding="utf-8",
    )
    (root / "audit_event_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "clx18-target-hit-events-v1",
                "generated_at": "2024-01-02T00:00:00+00:00",
                "contract": {"universe": audit_universe},
                "outputs": [
                    {"sha256": sha256_file(root / "event_outcomes_audit.parquet")}
                ],
                "checks": {"all_passed": True},
            }
        ),
        encoding="utf-8",
    )
    for prefix, stages, event_name, grid_name in (
        (
            "stage1",
            ["TRAIN", "VALIDATION"],
            "event_outcomes.parquet",
            "stage1_grid.parquet",
        ),
        ("audit", ["AUDIT"], "event_outcomes_audit.parquet", "audit_grid.parquet"),
    ):
        (root / f"{prefix}_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "clx18-target-hit-stage1-v1",
                    "input": {"sha256": sha256_file(root / event_name)},
                    "outputs": [{"sha256": sha256_file(root / grid_name)}],
                    "checks": {
                        "all_passed": True,
                        "contract_complete": True,
                        "stages": stages,
                    },
                }
            ),
            encoding="utf-8",
        )

    development_evidence = validate_pipeline_evidence(
        outcome_manifest_path=root / "event_manifest.json",
        stage1_manifest_path=root / "stage1_manifest.json",
        outcomes_path=root / "event_outcomes.parquet",
        grid_path=root / "stage1_grid.parquet",
        expected_stages=("TRAIN", "VALIDATION"),
    )
    lock["inputs"] = {
        "stage1_grid_sha256": development_evidence["grid_sha256"],
        "development_outcomes_sha256": development_evidence["outcomes_sha256"],
        "pipeline_evidence": development_evidence,
    }
    lock["lock_sha256"] = canonical_sha(lock)
    (root / "candidate_lock.json").write_text(
        json.dumps(lock),
        encoding="utf-8",
    )
    portfolio_lock = {
        "schema_version": "clx18-target-hit-portfolio-lock-v1",
        "locked_at": "2024-01-01T12:00:00+00:00",
        "selection_stages": ["TRAIN", "VALIDATION"],
        "audit_read": False,
        "winner": {"candidate_id": "candidate-a"},
        "inputs": {
            "candidate_lock_sha256": lock["lock_sha256"],
            "candidate_lock_file_sha256": sha256_file(root / "candidate_lock.json"),
            "development_events_sha256": development_evidence["outcomes_sha256"],
            "pipeline_evidence": development_evidence,
        },
    }
    portfolio_lock["lock_sha256"] = canonical_sha(portfolio_lock)
    write_json(root / "portfolio_lock.json", portfolio_lock, indent=2)

    audit_outcome_manifest_path = root / "audit_event_manifest.json"
    audit_outcome_manifest = json.loads(
        audit_outcome_manifest_path.read_text(encoding="utf-8")
    )
    audit_source = audit_outcome_manifest["contract"]["universe"]["source_manifest"]
    audit_source["generated_at"] = "2024-01-01T18:00:00+00:00"
    audit_source["audit_gate"] = {
        "candidate_lock": {
            "lock_sha256": lock["lock_sha256"],
            "audit_read": False,
        },
        "portfolio_lock": {
            "lock_sha256": portfolio_lock["lock_sha256"],
            "audit_read": False,
        },
        "portfolio_binds_candidate": True,
    }
    audit_outcome_manifest_path.write_text(
        json.dumps(audit_outcome_manifest),
        encoding="utf-8",
    )

    command = [
        sys.executable,
        str(
            Path(__file__).resolve().parents[3]
            / "script"
            / "clx_target_hit"
            / "build_final_report.py"
        ),
        "--root",
        str(root),
        "--output",
        str(output),
        "--skip-portfolio",
        "--expected-model-count",
        "1",
        "--bootstrap-samples",
        "20",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["checks"]["passed"]
    assert len(report["grid"]) == 522
    assert report["grid_total_rows"] == 3 * 522
