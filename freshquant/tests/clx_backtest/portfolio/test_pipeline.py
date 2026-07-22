from __future__ import annotations

import hashlib
import json
import shutil
import stat
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import freshquant.backtest.clx.portfolio.pipeline as portfolio_pipeline
from freshquant.backtest.clx.combo_dsl import ComboDefinition, EventIndex, make_combo
from freshquant.backtest.clx.event_study import SplitPlan, SplitWindow
from freshquant.backtest.clx.model_registry import (
    canonical_json_bytes,
    model_registry_sha256,
)
from freshquant.backtest.clx.portfolio.pipeline import (
    FrozenPortfolioCombo,
    PortfolioArtifactError,
    build_frozen_combo_decisions,
    build_portfolio_artifact,
    invert_combo_direction,
    verify_portfolio_artifact,
)
from freshquant.backtest.clx.ranking import (
    HOLDOUT_LOCKED,
    Candidate,
    CandidateMetric,
    HoldoutReveal,
    RankingConfig,
    RankingResult,
    _calendar_logical_sha256,
    publish_ranking_artifact,
)
from freshquant.backtest.clx.ranking_io import (
    load_ranking_result,
    publish_holdout_artifact,
)


def _content_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _publish_manifest(root: Path, manifest: Mapping[str, Any]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.sha256").write_text(
        digest + "  manifest.json\n", encoding="ascii"
    )
    return digest


def _signal_combo(*, trigger_mask: bool = False) -> ComboDefinition:
    if trigger_mask:
        where = {
            "op": "trigger_mask",
            "source": "concurrent",
            "mode": "any",
            "ids": [1],
            "model": "S0000",
            "direction": 1,
        }
    else:
        where = {"op": "signal", "model": "S0000", "direction": 1}
    return make_combo(where, target_direction=1)


def _event(
    fact_id: str,
    day: date,
    split_id: str,
    direction: int,
) -> dict[str, Any]:
    return {
        "run_id": "portfolio-fixture-run",
        "signal_fact_id": fact_id,
        "code": "600001",
        "reveal_date": day,
        "expected_model_id": 0,
        "model_code": "S0000",
        "direction": direction,
        "occurrence": 1,
        "primary_entrypoint": 1,
        "primary_trigger_semantic": "FRACTAL",
        "direction_base_trigger_mask": 1,
        "synthetic_primary_mask": 0,
        "concurrent_trigger_mask": 1,
        "split_id": split_id,
        "split_boundary_status": "ELIGIBLE",
    }


def _ranking_row(
    run_id: str,
    ranking_set_id: str,
    candidate: Candidate,
    rank: int,
    score: float,
) -> dict[str, object]:
    definition = candidate.definition
    return {
        "run_id": run_id,
        "ranking_set_id": ranking_set_id,
        "combo_id": definition.combo_id,
        "frozen_rank": rank,
        "discovery_stage": candidate.discovery_stage,
        "candidate_family": candidate.candidate_family,
        "complexity": definition.complexity,
        "train_sample": 1,
        "validation_sample": 1,
        "holdout_sample": None,
        "horizon": 5,
        "validation_score": score,
        "score_components": {"fixture": score},
        "mean_return": 0.01,
        "win_rate": 1.0,
        "ci_low": 0.01,
        "ci_high": 0.01,
        "fdr_q_value": 0.1,
        "mfe": 0.02,
        "mae": -0.01,
        "signal_density": 0.1,
        "year_positive_ratio": 1.0,
        "worst_year": 2024,
        "worst_year_mean": 0.01,
        "portfolio_cagr": None,
        "portfolio_sharpe": None,
        "portfolio_max_drawdown": None,
        "holdout_state": HOLDOUT_LOCKED,
        "holdout_metrics": None,
        "model_roots": list(definition.model_roots),
        "independent_vote_count": len(definition.model_roots),
        "canonical_dsl": definition.canonical_json,
        "train_membership_digest": _content_id(["train"]),
        "validation_membership_digest": _content_id(["validation"]),
        "fdr_family": "VALIDATION|h5|fixture",
        "quality_mask": 0,
    }


def _metric(candidate: Candidate, split_id: str) -> CandidateMetric:
    return CandidateMetric(
        candidate=candidate,
        split_id=split_id,
        horizon=5,
        n_total=1,
        n_executable=1,
        n_censored=0,
        mean_return=0.01,
        median_return=0.01,
        std=None,
        win_rate=1.0,
        ci_low=0.01,
        ci_high=0.01,
        mfe=0.02,
        mae=-0.01,
        signal_density=0.1,
        year_positive_ratio=1.0,
        worst_year=2024,
        worst_year_mean=0.01,
        p_value=0.1,
        fdr_q_value=0.1,
        membership=frozenset({"fixture"}),
        membership_digest=_content_id([split_id, "fixture"]),
        year_counts=((2024, 1),),
        discovery_score=0.01,
    )


def _build_inputs(root: Path) -> dict[str, Any]:
    days = tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(12))
    calendar = pl.DataFrame(
        {"trade_date": days, "session_no": range(1, len(days) + 1)},
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )
    snapshot = root / "snapshot"
    (snapshot / "calendar").mkdir(parents=True)
    (snapshot / "bars/code=600001").mkdir(parents=True)
    calendar_path = snapshot / "calendar/part-00000.parquet"
    bar_path = snapshot / "bars/code=600001/part-00000.parquet"
    calendar.write_parquet(calendar_path)
    pl.DataFrame(
        {
            "code": ["600001"] * len(days),
            "trade_date": days,
            "raw_open": [10.0 + index / 100 for index in range(len(days))],
            "raw_close": [10.0 + index / 100 for index in range(len(days))],
            "raw_volume": [1_000_000.0] * len(days),
        }
    ).write_parquet(bar_path)
    snapshot_id = "fixture-snapshot"
    snapshot_manifest = {
        "state": "COMPLETE",
        "snapshot_id": snapshot_id,
        "dataset": {
            "calendar_file": {
                "path": "calendar/part-00000.parquet",
                "file_sha256": hashlib.sha256(calendar_path.read_bytes()).hexdigest(),
            },
            "bar_files": [
                {
                    "path": "bars/code=600001/part-00000.parquet",
                    "partition": {"code": "600001"},
                    "file_sha256": hashlib.sha256(bar_path.read_bytes()).hexdigest(),
                }
            ],
        },
    }
    snapshot_sha = _publish_manifest(snapshot, snapshot_manifest)

    plan = SplitPlan(
        (
            SplitWindow("TRAIN", days[0], days[3]),
            SplitWindow("VALIDATION", days[4], days[7]),
            SplitWindow("HOLDOUT", days[8], days[-1]),
        ),
    )
    rows = [
        _event("train-positive", days[1], "TRAIN", 1),
        _event("validation-positive", days[4], "VALIDATION", 1),
        _event("validation-negative", days[6], "VALIDATION", -1),
        _event("holdout-positive", days[8], "HOLDOUT", 1),
        _event("holdout-negative", days[10], "HOLDOUT", -1),
    ]
    events = root / "events"
    (events / "event_outcomes").mkdir(parents=True)
    event_artifacts = []
    for split_id in ("TRAIN", "VALIDATION", "HOLDOUT"):
        split_rows = [row for row in rows if row["split_id"] == split_id]
        relative = f"event_outcomes/split_id={split_id}/part-00000.parquet"
        (events / relative).parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(split_rows).write_parquet(events / relative)
        reveal_dates = [row["reveal_date"] for row in split_rows]
        event_artifacts.append(
            {
                "dataset": "event_outcomes",
                "path": relative,
                "min_reveal_date": min(reveal_dates).isoformat(),
                "max_reveal_date": max(reveal_dates).isoformat(),
                "file_sha256": hashlib.sha256(
                    (events / relative).read_bytes()
                ).hexdigest(),
            }
        )
    event_manifest = {
        "state": "COMPLETE",
        "run_id": "portfolio-fixture-run",
        "event_set_id": "fixture-event-set",
        "snapshot": {
            "snapshot_id": snapshot_id,
            "manifest_sha256": snapshot_sha,
        },
        "split_plan": plan.to_dict(),
        "artifacts": event_artifacts,
    }
    event_sha = _publish_manifest(events, event_manifest)

    config = RankingConfig(
        min_train_sample=1,
        min_validation_sample=1,
        min_train_density=0.0,
        min_validation_density=0.0,
        min_train_years=1,
        min_validation_years=1,
        min_events_per_year=1,
        max_train_fdr=1.0,
        max_validation_fdr=1.0,
    )
    source_identity: dict[str, str] = {
        "event_set_id": str(event_manifest["event_set_id"]),
        "event_manifest_sha256": event_sha,
    }
    config_payload = {
        "schema_version": "clx-combination-ranking-v1",
        "model_registry_sha256": model_registry_sha256(),
        "source_identity": source_identity,
        "calendar_logical_sha256": _calendar_logical_sha256(calendar),
        "split_plan": plan.to_dict(),
        "config": config.to_dict(),
        "causal_clock": "reveal_date/session_no backward-only",
        "vote_unit": "distinct_independence_root",
    }
    config_id = _content_id(config_payload)
    ranking_set_id = _content_id(
        {"config_id": config_id, "run_id": event_manifest["run_id"]}
    )
    candidates = (
        Candidate(_signal_combo(), "A1", "fixture"),
        Candidate(_signal_combo(trigger_mask=True), "A3", "fixture"),
    )
    rankings = tuple(
        _ranking_row(
            str(event_manifest["run_id"]), ranking_set_id, candidate, index, 3 - index
        )
        for index, candidate in enumerate(candidates, start=1)
    )
    freeze_payload = {
        "freeze_schema_version": "clx-ranking-freeze-v1",
        "ranking_set_id": ranking_set_id,
        "config_id": config_id,
        "run_id": event_manifest["run_id"],
        "source_identity": source_identity,
        "calendar_logical_sha256": _calendar_logical_sha256(calendar),
        "split_plan": plan.to_dict(),
        "horizon": 5,
        "validation_score_weights": [
            list(item) for item in config.validation_score_weights
        ],
        "frozen_order": [candidate.definition.combo_id for candidate in candidates],
        "frozen_scores": [row["validation_score"] for row in rankings],
        "canonical_dsl_sha256": {
            candidate.definition.combo_id: _content_id(candidate.definition.canonical)
            for candidate in candidates
        },
        "holdout_state": HOLDOUT_LOCKED,
        "holdout_successful_reads_before_freeze": 0,
    }
    freeze = {**freeze_payload, "freeze_id": _content_id(freeze_payload)}
    ranking = root / "ranking"
    publish_ranking_artifact(
        RankingResult(
            ranking_set_id=ranking_set_id,
            config_id=config_id,
            run_id=str(event_manifest["run_id"]),
            source_identity=source_identity,
            calendar_logical_sha256=_calendar_logical_sha256(calendar),
            config=config,
            split_plan=plan,
            candidates=candidates,
            metrics=tuple(
                _metric(candidate, split)
                for candidate in candidates
                for split in ("TRAIN", "VALIDATION")
            ),
            rankings=rankings,
            freeze_record=freeze,
            search_audit={"fixture": True},
        ),
        ranking,
    )

    portfolio_config = root / "portfolio-config.json"
    portfolio_config.write_text(
        json.dumps(
            {
                "initial_cash_cny": "10000000",
                "target_weight": "0.10",
                "max_holdings": 10,
                "lot_size_default": 100,
                "decision_clock": "T_CLOSE",
                "first_attempt": "NEXT_MARKET_SESSION_RAW_OPEN",
                "buy_rule": "FROZEN_POSITIVE_DIRECTION_COMBO",
                "exit_rule": "DIRECTION_INVERTED_SAME_CANONICAL_DSL",
                "negative_signal_priority": "EXIT_AND_SAME_DAY_BUY_VETO",
                "selection": {
                    "split": "VALIDATION",
                    "direction": 1,
                    "frozen_rank_top_n": 20,
                },
                "price_domain": "RAW",
                "fee_schedule": "DEFAULT_FEE_SCHEDULE",
                "limit_schedule": "DEFAULT_LIMIT_SCHEDULE",
                "slippage_model": "DEFAULT_SLIPPAGE_MODEL",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "snapshot": snapshot,
        "events": events,
        "ranking": ranking,
        "config": portfolio_config,
        "calendar": calendar,
        "event_frame": pl.DataFrame(rows),
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _make_tree_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            path.chmod(0o644)
    root.chmod(0o755)


def test_strict_direction_inversion_is_an_involution_and_preserves_roots() -> None:
    combo = ComboDefinition.from_value(
        {
            "target_direction": 1,
            "where": {
                "op": "and",
                "args": [
                    {"op": "signal", "model": ["S0008", "S0013"], "direction": 1},
                    {
                        "op": "trigger_mask",
                        "source": "concurrent",
                        "mode": "any",
                        "ids": [1, 3],
                        "event_filter": {
                            "model": "S0008",
                            "direction": 1,
                        },
                    },
                ],
            },
        }
    )
    inverse = invert_combo_direction(combo)
    restored = invert_combo_direction(inverse)
    assert restored.canonical_json == combo.canonical_json
    assert restored.combo_id == combo.combo_id
    assert inverse.model_roots == combo.model_roots == ("S0008",)


def test_parent_child_count_keeps_one_root_after_direction_inversion() -> None:
    days = (date(2024, 1, 2), date(2024, 1, 3))
    calendar = pl.DataFrame({"trade_date": days, "session_no": (1, 2)})
    combo = ComboDefinition.from_value(
        {
            "target_direction": 1,
            "where": {
                "op": "count",
                "expr": {
                    "op": "signal",
                    "model": ["S0008", "S0013"],
                    "direction": 1,
                },
                "min": 1,
                "max": 1,
                "distinct": "independence_root",
                "sessions": 0,
            },
        }
    )
    rows = []
    for model_id in (8, 13):
        row = _event(f"positive-{model_id}", days[0], "VALIDATION", 1)
        row.update(expected_model_id=model_id, model_code=f"S{model_id:04d}")
        rows.append(row)
    for model_id in (8, 13):
        row = _event(f"negative-{model_id}", days[1], "VALIDATION", -1)
        row.update(expected_model_id=model_id, model_code=f"S{model_id:04d}")
        rows.append(row)
    events = pl.DataFrame(rows)
    index = EventIndex(events, calendar)
    assert index.matches(combo, "600001", days[0])
    assert index.matches(invert_combo_direction(combo), "600001", days[1])


def test_decisions_are_close_anchored_and_inverse_is_exit(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path / "inputs")
    combos = (
        FrozenPortfolioCombo(1, _signal_combo(), 1.0),
        FrozenPortfolioCombo(2, _signal_combo(trigger_mask=True), 0.5),
    )
    decisions = build_frozen_combo_decisions(
        inputs["event_frame"], inputs["calendar"], combos, "VALIDATION"
    )
    for rows in decisions.values():
        assert [
            (row.reveal_date.day, row.direction, row.source_signal_fact_ids)
            for row in rows
        ] == [
            (5, 1, ("validation-positive",)),
            (7, -1, ("validation-negative",)),
        ]


def test_decision_sources_are_the_causal_sequence_members_only() -> None:
    days = tuple(date(2024, 1, 2) + timedelta(days=offset) for offset in range(4))
    calendar = pl.DataFrame(
        {"trade_date": days, "session_no": tuple(range(1, len(days) + 1))}
    )
    prior = _event("prior", days[0], "VALIDATION", 1)
    prior.update(expected_model_id=1, model_code="S0001")
    unrelated = _event("unrelated", days[1], "VALIDATION", -1)
    unrelated.update(expected_model_id=2, model_code="S0002")
    anchor = _event("anchor", days[2], "VALIDATION", 1)
    events = pl.DataFrame([prior, unrelated, anchor])
    combo = make_combo(
        {
            "op": "sequence",
            "args": [
                {"op": "signal", "model": "S0001", "direction": 1},
                {"op": "signal", "model": "S0000", "direction": 1},
            ],
            "max_gap_sessions": 3,
            "anchor_last": True,
        },
        target_direction=1,
    )

    decisions = build_frozen_combo_decisions(
        events,
        calendar,
        (FrozenPortfolioCombo(1, combo, 1.0),),
        "VALIDATION",
    )[combo.combo_id]

    assert len(decisions) == 1
    assert decisions[0].reveal_date == days[2]
    assert decisions[0].source_signal_fact_ids == ("anchor", "prior")


def test_portfolio_rejects_a_source_free_negative_match() -> None:
    day = date(2024, 1, 2)
    calendar = pl.DataFrame({"trade_date": [day], "session_no": [1]})
    events = pl.DataFrame([_event("anchor", day, "VALIDATION", 1)])
    combo = make_combo(
        {
            "op": "not",
            "expr": {"op": "signal", "model": "S0001", "direction": 1},
        },
        target_direction=1,
    )

    with pytest.raises(PortfolioArtifactError, match="has no source signal facts"):
        build_frozen_combo_decisions(
            events,
            calendar,
            (FrozenPortfolioCombo(1, combo, 1.0),),
            "VALIDATION",
        )


def test_portfolio_rejects_a_historical_only_trace_without_decision_anchor() -> None:
    days = (date(2024, 1, 2), date(2024, 1, 3))
    calendar = pl.DataFrame({"trade_date": days, "session_no": (1, 2)})
    prior = _event("prior", days[0], "VALIDATION", 1)
    prior.update(expected_model_id=1, model_code="S0001")
    unrelated_anchor = _event("unrelated-anchor", days[1], "VALIDATION", 1)
    unrelated_anchor.update(expected_model_id=2, model_code="S0002")
    combo = make_combo(
        {
            "op": "within",
            "expr": {"op": "signal", "model": "S0001", "direction": 1},
            "sessions": 1,
        },
        target_direction=1,
    )

    with pytest.raises(PortfolioArtifactError, match="no same-day direction anchor"):
        build_frozen_combo_decisions(
            pl.DataFrame([prior, unrelated_anchor]),
            calendar,
            (FrozenPortfolioCombo(1, combo, 1.0),),
            "VALIDATION",
        )


def test_artifact_resume_double_run_and_holdout_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _build_inputs(tmp_path / "inputs")
    locked_holdout = (
        inputs["events"] / "event_outcomes/split_id=HOLDOUT/part-00000.parquet"
    )
    holdout_bytes = locked_holdout.read_bytes()
    locked_holdout.write_bytes(b"physically locked before reveal")
    output_a = tmp_path / "portfolio-a"
    first = build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        output_a,
        inputs["config"],
        max_combos=1,
    )
    assert first["state"] == "INCOMPLETE"
    assert first["completed_combos"] == 1
    completed_checkpoint = next(
        path.parent
        for path in output_a.rglob("checkpoint.json")
        if ".staging-" not in str(path)
    )
    assert stat.S_IMODE(completed_checkpoint.stat().st_mode) == 0o555
    abandoned = (
        output_a
        / "splits/split_id=VALIDATION/source_frozen_rank=00002"
        / ".staging-999"
    )
    abandoned.mkdir(parents=True)
    (abandoned / "partial").write_text("crashed", encoding="utf-8")
    completed = build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        output_a,
        inputs["config"],
        resume=True,
    )
    assert completed["status"] == "verified"
    assert completed["combo_count"] == 2
    assert completed["successful_holdout_reads"] == 0
    assert completed["reconciliation_rows"] == 8
    assert not abandoned.exists()
    assert stat.S_IMODE(output_a.stat().st_mode) == 0o555

    output_b = tmp_path / "portfolio-b"
    second = build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        output_b,
        inputs["config"],
    )
    assert second["manifest_sha256"] == completed["manifest_sha256"]
    assert _tree_bytes(output_a) == _tree_bytes(output_b)
    assert verify_portfolio_artifact(output_b) == second
    build_config = json.loads(
        (output_b / "build_config.json").read_text(encoding="utf-8")
    )
    assert (
        build_config["identity"]["decision_source_contract"]
        == "CANONICAL_DSL_MATCH_TRACE_ONLY"
    )

    previous_schema = tmp_path / "portfolio-previous-schema"
    shutil.copytree(output_b, previous_schema)
    _make_tree_writable(previous_schema)
    previous_manifest = json.loads(
        (previous_schema / "manifest.json").read_text(encoding="utf-8")
    )
    previous_manifest["schema_version"] = "clx-portfolio-artifact-v1"
    _publish_manifest(previous_schema, previous_manifest)
    with pytest.raises(PortfolioArtifactError, match="schema version"):
        verify_portfolio_artifact(previous_schema)

    with pytest.raises(PortfolioArtifactError, match="unique ranking reveal"):
        build_portfolio_artifact(
            inputs["snapshot"],
            inputs["events"],
            inputs["ranking"],
            tmp_path / "holdout-denied",
            inputs["config"],
            split_id="HOLDOUT",
        )

    locked_holdout.write_bytes(holdout_bytes)
    ranking_result = load_ranking_result(inputs["ranking"])
    holdout_metrics = tuple(
        _metric(candidate, "HOLDOUT") for candidate in ranking_result.candidates
    )
    metrics_by_combo = {
        metric.candidate.definition.combo_id: metric.to_dict()
        for metric in holdout_metrics
    }
    revealed_rankings = tuple(
        {
            **row,
            "holdout_state": "REVEALED",
            "holdout_sample": metrics_by_combo[row["combo_id"]]["n_executable"],
            "holdout_metrics": metrics_by_combo[row["combo_id"]],
        }
        for row in ranking_result.rankings
    )
    reveal_payload = {
        "freeze_id": ranking_result.freeze_record["freeze_id"],
        "ranking_set_id": ranking_result.ranking_set_id,
        "frozen_order": [row["combo_id"] for row in revealed_rankings],
        "holdout_metric_digests": {
            row["combo_id"]: _content_id(row["holdout_metrics"])
            for row in revealed_rankings
        },
        "successful_holdout_reads": 1,
    }
    reveal = HoldoutReveal(
        freeze_id=ranking_result.freeze_record["freeze_id"],
        reveal_id=_content_id(reveal_payload),
        metrics=holdout_metrics,
        rankings=revealed_rankings,
        access_audit=(
            {
                "operation": "REVEAL_HOLDOUT",
                "run_id": ranking_result.run_id,
                "split_id": "HOLDOUT",
                "purpose": "FINAL_REVEAL",
                "decision": "ALLOW",
                "reason": "FROZEN_RULES_ONE_TIME_REVEAL",
                "freeze_id": ranking_result.freeze_record["freeze_id"],
                "claim_id": "sha256:" + "c" * 64,
                "attempt_no": 0,
            },
            {
                "operation": "OPEN_PARQUET",
                "run_id": ranking_result.run_id,
                "purpose": "LOAD_HOLDOUT",
                "dataset": "event_outcomes",
                "holdout": True,
                "decision": "ALLOW",
                "freeze_id": ranking_result.freeze_record["freeze_id"],
                "claim_id": "sha256:" + "c" * 64,
                "attempt_no": 0,
            },
        ),
    )
    ranking_sha = hashlib.sha256(
        (inputs["ranking"] / "manifest.json").read_bytes()
    ).hexdigest()
    reveal_dir = tmp_path / "holdout-reveal"
    publish_holdout_artifact(
        reveal,
        ranking_result,
        reveal_dir,
        ranking_manifest_sha256=ranking_sha,
    )
    invalid_claim_reveal = tmp_path / "holdout-reveal-invalid-claim"
    shutil.copytree(reveal_dir, invalid_claim_reveal)
    _make_tree_writable(invalid_claim_reveal)
    invalid_audit_path = invalid_claim_reveal / "audit/event_access.json"
    invalid_audit = json.loads(invalid_audit_path.read_text(encoding="utf-8"))
    invalid_audit[0]["claim_id"] = "sha256:" + "C" * 64
    invalid_audit_path.write_text(
        json.dumps(invalid_audit, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    invalid_reveal_manifest = json.loads(
        (invalid_claim_reveal / "manifest.json").read_text(encoding="utf-8")
    )
    invalid_audit_meta = next(
        item
        for item in invalid_reveal_manifest["artifacts"]
        if item["dataset"] == "event_access_audit"
    )
    invalid_audit_meta["file_sha256"] = hashlib.sha256(
        invalid_audit_path.read_bytes()
    ).hexdigest()
    invalid_audit_meta["logical_sha256"] = _content_id(invalid_audit)
    _publish_manifest(invalid_claim_reveal, invalid_reveal_manifest)
    portfolio_pipeline._seal_tree(invalid_claim_reveal)
    with pytest.raises(PortfolioArtifactError, match="authorization identity"):
        build_portfolio_artifact(
            inputs["snapshot"],
            inputs["events"],
            inputs["ranking"],
            tmp_path / "holdout-invalid-claim",
            inputs["config"],
            split_id="HOLDOUT",
            reveal_dir=invalid_claim_reveal,
        )

    holdout_output = tmp_path / "holdout-portfolio"
    holdout = build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        holdout_output,
        inputs["config"],
        split_id="HOLDOUT",
        reveal_dir=reveal_dir,
    )
    assert holdout["status"] == "verified"
    assert holdout["holdout_state"] == "REVEALED"
    assert holdout["successful_holdout_reads"] == 1
    assert holdout["upstream_reveal_successful_reads"] == 1

    portfolio_manifest = json.loads(
        (holdout_output / "manifest.json").read_text(encoding="utf-8")
    )
    event_manifest = json.loads(
        (inputs["events"] / "manifest.json").read_text(encoding="utf-8")
    )
    event_manifest_sha = hashlib.sha256(
        (inputs["events"] / "manifest.json").read_bytes()
    ).hexdigest()
    reveal_manifest_sha = hashlib.sha256(
        (reveal_dir / "manifest.json").read_bytes()
    ).hexdigest()
    expected_sources = sorted(
        [
            {
                "path": item["path"],
                "file_sha256": item["file_sha256"],
            }
            for item in event_manifest["artifacts"]
            if item["dataset"] == "event_outcomes"
        ],
        key=lambda item: item["path"],
    )
    access = portfolio_manifest["holdout_access"]
    assert access["successful_holdout_reads"] == 1
    assert access["upstream_reveal_successful_reads"] == 1
    assert access["authorization"] == {
        "run_id": ranking_result.run_id,
        "event_set_id": event_manifest["event_set_id"],
        "event_manifest_sha256": event_manifest_sha,
        "ranking_set_id": ranking_result.ranking_set_id,
        "ranking_manifest_sha256": ranking_sha,
        "freeze_id": ranking_result.freeze_record["freeze_id"],
        "reveal_id": reveal.reveal_id,
        "reveal_manifest_sha256": reveal_manifest_sha,
        "claim_id": "sha256:" + "c" * 64,
        "attempt_no": 0,
    }
    assert access["event_source_registry"] == {
        "source_count": len(expected_sources),
        "source_digest": _content_id(expected_sources),
        "sources": expected_sources,
    }
    assert holdout["holdout_event_source_count"] == len(expected_sources)
    assert holdout["holdout_event_source_digest"] == _content_id(expected_sources)

    def tampered_holdout_portfolio(name: str, mutate: Any) -> Path:
        target = tmp_path / name
        shutil.copytree(holdout_output, target)
        _make_tree_writable(target)
        tampered_manifest = json.loads(
            (target / "manifest.json").read_text(encoding="utf-8")
        )
        tampered_build = json.loads(
            (target / "build_config.json").read_text(encoding="utf-8")
        )
        mutate(tampered_manifest, tampered_build)
        portfolio_set_id = _content_id(tampered_build["identity"])
        tampered_build["portfolio_set_id"] = portfolio_set_id
        tampered_manifest["portfolio_set_id"] = portfolio_set_id
        (target / "build_config.json").write_text(
            json.dumps(tampered_build, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n",
            encoding="utf-8",
        )
        _publish_manifest(target, tampered_manifest)
        return target

    tampered_authorization = tampered_holdout_portfolio(
        "holdout-tampered-authorization",
        lambda manifest, build: (
            manifest["holdout_access"]["authorization"].update(
                {"event_set_id": "different-event"}
            ),
            build["identity"]["holdout_authorization"].update(
                {"event_set_id": "different-event"}
            ),
        ),
    )
    with pytest.raises(PortfolioArtifactError, match="authorization identity"):
        verify_portfolio_artifact(tampered_authorization)

    tampered_claim = tampered_holdout_portfolio(
        "holdout-tampered-claim",
        lambda manifest, build: (
            manifest["holdout_access"]["authorization"].update(
                {"claim_id": "sha256:" + "C" * 64}
            ),
            build["identity"]["holdout_authorization"].update(
                {"claim_id": "sha256:" + "C" * 64}
            ),
        ),
    )
    with pytest.raises(PortfolioArtifactError, match="claim/attempt"):
        verify_portfolio_artifact(tampered_claim)

    tampered_registry = tampered_holdout_portfolio(
        "holdout-tampered-registry",
        lambda manifest, build: (
            manifest["holdout_access"]["event_source_registry"].update(
                {"source_count": len(expected_sources) + 1}
            ),
            build["identity"]["holdout_event_source_registry"].update(
                {"source_count": len(expected_sources) + 1}
            ),
        ),
    )
    with pytest.raises(PortfolioArtifactError, match="registry digest"):
        verify_portfolio_artifact(tampered_registry)

    def fail_event_scan(*_args, **_kwargs):
        raise AssertionError("complete portfolio resume scanned event outcomes")

    monkeypatch.setattr(portfolio_pipeline, "_load_event_context", fail_event_scan)
    resumed_holdout = build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        holdout_output,
        inputs["config"],
        split_id="HOLDOUT",
        reveal_dir=reveal_dir,
        resume=True,
    )
    assert resumed_holdout == holdout


def test_source_manifest_chain_and_physical_hashes_are_enforced(
    tmp_path: Path,
) -> None:
    changed_snapshot = _build_inputs(tmp_path / "changed-snapshot")
    manifest_path = changed_snapshot["snapshot"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["unexpected_mutation"] = True
    _publish_manifest(changed_snapshot["snapshot"], manifest)
    with pytest.raises(
        PortfolioArtifactError, match="snapshot manifest identities differ"
    ):
        build_portfolio_artifact(
            changed_snapshot["snapshot"],
            changed_snapshot["events"],
            changed_snapshot["ranking"],
            tmp_path / "changed-snapshot-output",
            changed_snapshot["config"],
        )

    changed_event = _build_inputs(tmp_path / "changed-event")
    event_path = (
        changed_event["events"]
        / "event_outcomes/split_id=VALIDATION/part-00000.parquet"
    )
    event_path.write_bytes(event_path.read_bytes() + b"tampered")
    with pytest.raises(PortfolioArtifactError, match="event outcome artifact hash"):
        build_portfolio_artifact(
            changed_event["snapshot"],
            changed_event["events"],
            changed_event["ranking"],
            tmp_path / "changed-event-output",
            changed_event["config"],
        )

    changed_bar = _build_inputs(tmp_path / "changed-bar")
    bar_path = changed_bar["snapshot"] / "bars/code=600001/part-00000.parquet"
    bar_path.write_bytes(bar_path.read_bytes() + b"tampered")
    with pytest.raises(PortfolioArtifactError, match="snapshot bar artifact hash"):
        build_portfolio_artifact(
            changed_bar["snapshot"],
            changed_bar["events"],
            changed_bar["ranking"],
            tmp_path / "changed-bar-output",
            changed_bar["config"],
        )


def test_verifier_rejects_cross_source_checkpoint_even_with_rehashed_registry(
    tmp_path: Path,
) -> None:
    inputs = _build_inputs(tmp_path / "inputs")
    output = tmp_path / "portfolio"
    build_portfolio_artifact(
        inputs["snapshot"],
        inputs["events"],
        inputs["ranking"],
        output,
        inputs["config"],
    )
    tampered = tmp_path / "tampered"
    shutil.copytree(output, tampered)
    _make_tree_writable(tampered)
    manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
    checkpoint_path = tampered / manifest["checkpoint_paths"][0] / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["source_identity"]["snapshot_id"] = "different-snapshot"
    checkpoint_payload = dict(checkpoint)
    checkpoint_payload.pop("checkpoint_sha256")
    checkpoint["checkpoint_sha256"] = _content_id(checkpoint_payload)
    checkpoint_path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["checkpoints"][0]["checkpoint_sha256"] = checkpoint["checkpoint_sha256"]
    _publish_manifest(tampered, manifest)

    with pytest.raises(PortfolioArtifactError, match="checkpoint contract identity"):
        verify_portfolio_artifact(tampered)
