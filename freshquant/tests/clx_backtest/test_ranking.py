from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from freshquant.backtest.clx._file_lock import seal_tree_durable
from freshquant.backtest.clx.combo_dsl import (
    ComboDefinition,
    DslValidationError,
    EventIndex,
    ModelRelations,
    make_combo,
)
from freshquant.backtest.clx.event_study import SplitPlan, SplitWindow
from freshquant.backtest.clx.model_registry import (
    S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
)
from freshquant.backtest.clx.ranking import (
    HOLDOUT_LOCKED,
    HOLDOUT_REVEALED,
    HoldoutAlreadyRevealedError,
    HoldoutLockedError,
    PersistentHoldoutLedger,
    RankingConfig,
    SplitOutcomeStore,
    benjamini_hochberg,
    discover_and_freeze,
    generate_multi_model_candidates,
    generate_single_model_candidates,
    publish_ranking_artifact,
    reveal_holdout,
    verify_ranking_artifact,
)


def _calendar() -> pl.DataFrame:
    start = date(2024, 1, 1)
    return pl.DataFrame(
        {
            "trade_date": [start + timedelta(days=index) for index in range(180)],
            "session_no": list(range(1, 181)),
        },
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )


def _plan(calendar: pl.DataFrame) -> SplitPlan:
    days = calendar["trade_date"].to_list()
    return SplitPlan(
        (
            SplitWindow("TRAIN", days[0], days[59]),
            SplitWindow("VALIDATION", days[60], days[119]),
            SplitWindow("HOLDOUT", days[120], days[179]),
        )
    )


def _event(
    fact_id: str,
    calendar: pl.DataFrame,
    index: int,
    split: str,
    *,
    code: str,
    model_id: int,
    direction: int = 1,
    occurrence: int = 1,
    primary_entrypoint: int = 7,
    semantic: str = "MACD_CROSS",
    base_mask: int = 32,
    synthetic_mask: int = 64,
    value: float = 0.02,
) -> dict[str, object]:
    return {
        "run_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "signal_fact_id": fact_id,
        "code": code,
        "reveal_date": calendar["trade_date"][index],
        "expected_model_id": model_id,
        "model_code": f"S{model_id:04d}",
        "direction": direction,
        "occurrence": occurrence,
        "primary_entrypoint": primary_entrypoint,
        "primary_trigger_semantic": semantic,
        "direction_base_trigger_mask": base_mask,
        "synthetic_primary_mask": synthetic_mask,
        "concurrent_trigger_mask": base_mask | synthetic_mask,
        "split_id": split,
        "split_boundary_status": "ELIGIBLE",
        "h5_status": "OK",
        "h5_direction_adjusted_return": value,
        "h5_mfe": abs(value) + 0.01,
        "h5_mae": -0.01,
    }


def _outcomes(calendar: pl.DataFrame, *, holdout_scale: float = -1.0) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    split_dates = {
        "TRAIN": [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35],
        "VALIDATION": [81, 84, 87, 90, 93, 96, 99],
        "HOLDOUT": [141, 145, 149, 153, 157],
    }
    sequence = 0
    for split, indices in split_dates.items():
        for position, index in enumerate(indices):
            code = "000001" if position % 2 == 0 else "000002"
            value = 0.01 + (position % 3) * 0.002
            if split == "HOLDOUT":
                value *= holdout_scale
            # S0008 and its S0013 subset deliberately co-occur.  They remain a
            # single independent vote.  S0016 is the second root.  One missing
            # and one extra S0016 anchor keep its bitmap distinct, so a genuine
            # two-root intersection survives exact-membership pruning.
            for model_id in (8, 13, 16):
                if model_id == 16 and position == 1:
                    continue
                sequence += 1
                base = 32 if (position % 2 == 0 or model_id == 16) else 0
                synthetic = 64
                rows.append(
                    _event(
                        f"fact-{sequence:04d}",
                        calendar,
                        index,
                        split,
                        code=code,
                        model_id=model_id,
                        occurrence=2 if model_id == 16 else 1,
                        base_mask=base,
                        synthetic_mask=synthetic,
                        value=value,
                    )
                )
        extra_index = {"TRAIN": 38, "VALIDATION": 98, "HOLDOUT": 165}[split]
        sequence += 1
        rows.append(
            _event(
                f"fact-{sequence:04d}",
                calendar,
                extra_index,
                split,
                code="000003",
                model_id=16,
                occurrence=2,
                base_mask=32,
                synthetic_mask=64,
                value=(0.015 if split != "HOLDOUT" else 0.015 * holdout_scale),
            )
        )
    # This dimension exists only in VALIDATION and must never enter discovery.
    rows.append(
        _event(
            "validation-only-model",
            calendar,
            90,
            "VALIDATION",
            code="000003",
            model_id=7,
            occurrence=99,
            primary_entrypoint=2,
            semantic="PIN_BAR",
            base_mask=2,
            synthetic_mask=0,
            value=0.5,
        )
    )
    return pl.DataFrame(rows, infer_schema_length=None)


def _config() -> RankingConfig:
    return RankingConfig(
        horizon=5,
        min_train_sample=3,
        min_validation_sample=3,
        min_train_density=0.0,
        min_validation_density=0.0,
        min_train_years=1,
        min_validation_years=1,
        min_events_per_year=2,
        max_train_fdr=1.0,
        max_validation_fdr=1.0,
        beam_width_per_stage=24,
        max_candidates_per_stage=256,
        max_total_candidates=1024,
        max_seed_per_root=2,
        jaccard_threshold=1.0,
        resonance_lookbacks=(0, 1, 3),
    )


def _source() -> dict[str, str]:
    return {
        "event_set_id": "sha256:event-fixture-v1",
        "event_manifest_sha256": "sha256:event-manifest-fixture-v1",
    }


def test_dsl_canonicalizes_commutative_nodes_sets_and_defaults() -> None:
    relations = ModelRelations()
    left = ComboDefinition.from_value(
        {
            "action": "BUY_CANDIDATE",
            "where": {
                "op": "and",
                "args": [
                    {"op": "signal", "model": "S0016", "direction": 1},
                    {
                        "op": "trigger_mask",
                        "source": "direction_base",
                        "mode": "all",
                        "ids": [7, 6, 7],
                        "model": "S0016",
                        "direction": 1,
                    },
                ],
            },
        },
        relations=relations,
    )
    right = ComboDefinition.from_value(
        {
            "dsl_version": "1.0",
            "anchor": "reveal_date",
            "target_direction": 1,
            "action": "BUY_CANDIDATE",
            "where": {
                "args": [
                    {
                        "direction": {"in": [1]},
                        "model": {"in": ["S0016"]},
                        "ids": [6, 7],
                        "mode": "all",
                        "source": "direction_base",
                        "op": "trigger_mask",
                    },
                    {"direction": {"in": [1]}, "model": "S0016", "op": "signal"},
                ],
                "op": "and",
            },
        },
        relations=relations,
    )
    assert left.combo_id == right.combo_id
    assert left.canonical_json == right.canonical_json
    with pytest.raises(DslValidationError, match="model-local"):
        ComboDefinition.from_value(
            {
                "action": "BUY_CANDIDATE",
                "where": {"op": "signal", "occurrence": {"in": [2]}},
            },
            relations=relations,
        )


def test_base_synthetic_and_concurrent_sources_are_not_conflated() -> None:
    calendar = _calendar()
    frame = pl.DataFrame(
        [
            _event(
                "mask",
                calendar,
                2,
                "TRAIN",
                code="000001",
                model_id=8,
                base_mask=32,
                synthetic_mask=64,
            )
        ]
    )
    index = EventIndex(frame, calendar)

    def mask_combo(source: str, entrypoint: int) -> ComboDefinition:
        return make_combo(
            {
                "op": "trigger_mask",
                "source": source,
                "mode": "all",
                "ids": [entrypoint],
                "model": "S0008",
                "direction": 1,
            },
            target_direction=1,
        )

    base_six = mask_combo("direction_base", 6)
    base_seven = mask_combo("direction_base", 7)
    synthetic_seven = mask_combo("synthetic_primary", 7)
    concurrent_seven = mask_combo("concurrent", 7)
    day = calendar["trade_date"][2]
    assert index.matches(base_six, "000001", day)
    assert not index.matches(base_seven, "000001", day)
    assert index.matches(synthetic_seven, "000001", day)
    assert index.matches(concurrent_seven, "000001", day)
    assert (
        len(
            {
                base_six.combo_id,
                base_seven.combo_id,
                synthetic_seven.combo_id,
                concurrent_seven.combo_id,
            }
        )
        == 4
    )


def test_s0002_strong_swing_candidates_keep_primary_and_mask_dimensions_separate() -> (
    None
):
    calendar = _calendar()
    frame = pl.DataFrame(
        [
            _event(
                "s0002-synthetic",
                calendar,
                2,
                "TRAIN",
                code="000001",
                model_id=2,
                primary_entrypoint=4,
                semantic=S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                base_mask=0,
                synthetic_mask=8,
            ),
            _event(
                "s0002-shared",
                calendar,
                3,
                "TRAIN",
                code="000001",
                model_id=2,
                primary_entrypoint=4,
                semantic=S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,
                base_mask=8,
                synthetic_mask=0,
            ),
        ]
    )
    candidates = generate_single_model_candidates(frame, _config(), ModelRelations())

    def nodes(value: object) -> list[dict[str, object]]:
        if isinstance(value, dict):
            output = [value]
            for child in value.values():
                output.extend(nodes(child))
            return output
        if isinstance(value, list):
            return [node for child in value for node in nodes(child)]
        return []

    by_stage = {
        stage: [
            json.loads(item.definition.canonical_json)
            for item in candidates
            if item.discovery_stage == stage
        ]
        for stage in ("A2", "A3", "B")
    }
    for stage in ("A2", "A3"):
        primary_nodes = [
            node
            for document in by_stage[stage]
            for node in nodes(document)
            if node.get("op") == "signal"
            and node.get("model") == {"in": ["S0002"]}
            and node.get("primary_entrypoint") == {"in": [4]}
        ]
        assert primary_nodes
        semantics = set()
        for node in primary_nodes:
            semantic = node.get("primary_trigger_semantic")
            if isinstance(semantic, dict):
                values = semantic["in"]
                assert isinstance(values, list)
                semantics.add(tuple(values))
        assert semantics == {(S0002_STRONG_SWING_ENTRYPOINT4_SEMANTIC,)}

    trigger_sources = set()
    for document in by_stage["B"]:
        for node in nodes(document):
            event_filter = node.get("event_filter")
            if (
                node.get("op") == "trigger_mask"
                and isinstance(event_filter, dict)
                and event_filter.get("model") == {"in": ["S0002"]}
                and node.get("ids") == [4]
            ):
                trigger_sources.add(node["source"])
    assert trigger_sources == {
        "direction_base",
        "synthetic_primary",
        "concurrent",
    }


def test_within_and_sequence_are_strictly_backward_from_reveal_session() -> None:
    calendar = _calendar()
    frame = pl.DataFrame(
        [
            _event(
                "older",
                calendar,
                10,
                "TRAIN",
                code="000001",
                model_id=8,
            ),
            _event(
                "newer",
                calendar,
                12,
                "TRAIN",
                code="000001",
                model_id=16,
            ),
        ]
    )
    index = EventIndex(frame, calendar)
    within = make_combo(
        {
            "op": "within",
            "expr": {"op": "signal", "model": "S0016", "direction": 1},
            "sessions": 3,
        },
        target_direction=1,
    )
    assert not index.matches(within, "000001", calendar["trade_date"][11])
    assert index.matches(within, "000001", calendar["trade_date"][15])
    assert not index.matches(within, "000001", calendar["trade_date"][16])

    forward = make_combo(
        {
            "op": "sequence",
            "args": [
                {"op": "signal", "model": "S0008", "direction": 1},
                {"op": "signal", "model": "S0016", "direction": 1},
            ],
            "max_gap_sessions": 3,
            "anchor_last": True,
        },
        target_direction=1,
    )
    reverse = make_combo(
        {
            "op": "sequence",
            "args": [
                {"op": "signal", "model": "S0016", "direction": 1},
                {"op": "signal", "model": "S0008", "direction": 1},
            ],
            "max_gap_sessions": 3,
            "anchor_last": True,
        },
        target_direction=1,
    )
    anchor = calendar["trade_date"][12]
    assert index.matches(forward, "000001", anchor)
    assert not index.matches(reverse, "000001", anchor)


def test_match_trace_presence_matches_boolean_dsl_evaluation() -> None:
    calendar = _calendar()
    days = calendar["trade_date"].to_list()
    events = pl.DataFrame(
        [
            _event(
                "prior",
                calendar,
                1,
                "TRAIN",
                code="000001",
                model_id=8,
            ),
            _event(
                "anchor",
                calendar,
                3,
                "TRAIN",
                code="000001",
                model_id=16,
            ),
        ]
    )
    factor_registry = {"fixture_factor": {"as_of": True, "lineage": "fixture-v1"}}
    index = EventIndex(
        events,
        calendar,
        factor_provider=lambda code, session, name: 10.0,
    )

    prior = {"op": "signal", "model": "S0008", "direction": 1}
    anchor = {"op": "signal", "model": "S0016", "direction": 1}
    missing = {"op": "signal", "model": "S0007", "direction": 1}

    def combo(where: dict[str, object]) -> ComboDefinition:
        return ComboDefinition.from_value(
            {"target_direction": 1, "where": where},
            factor_registry=factor_registry,
        )

    factor_node = {
        "op": "factor",
        "name": "fixture_factor",
        "comparison": "gte",
        "value": 10,
    }
    factor = combo(factor_node)
    pure_negative = combo({"op": "not", "expr": missing})
    not_exists = combo({"op": "not_exists", "expr": missing, "sessions": 3})
    count = {
        "op": "count",
        "expr": {"op": "or", "args": [prior, anchor]},
        "min": 2,
        "max": 2,
        "distinct": "independence_root",
        "sessions": 3,
    }
    sequence = {
        "op": "sequence",
        "args": [prior, anchor],
        "max_gap_sessions": 3,
        "anchor_last": True,
    }
    definitions = [
        combo(anchor),
        combo(
            {
                "op": "trigger_mask",
                "source": "direction_base",
                "mode": "all",
                "ids": [6],
                "model": "S0016",
                "direction": 1,
            }
        ),
        factor,
        combo({"op": "and", "args": [anchor, factor_node]}),
        combo({"op": "or", "args": [missing, anchor]}),
        pure_negative,
        combo({"op": "same_day", "expr": anchor}),
        combo({"op": "within", "expr": prior, "sessions": 3}),
        not_exists,
        combo(count),
        combo(sequence),
        combo(
            {
                "op": "and",
                "args": [
                    anchor,
                    {"op": "within", "expr": prior, "sessions": 3},
                    count,
                ],
            }
        ),
        combo({"op": "and", "args": [sequence, count]}),
        combo(
            {
                "op": "factor",
                "name": "fixture_factor",
                "comparison": "lt",
                "value": 10,
            }
        ),
    ]

    for definition in definitions:
        for day in days[:7]:
            assert index.matches(definition, "000001", day) is (
                index.match_trace(definition, "000001", day) is not None
            )

    decision_day = days[3]
    assert index.match_trace(factor, "000001", decision_day) == ()
    assert index.match_trace(pure_negative, "000001", decision_day) == ()
    assert index.match_trace(not_exists, "000001", decision_day) == ()
    assert {
        row["signal_fact_id"]
        for row in index.match_trace(combo(sequence), "000001", decision_day) or ()
    } == {"prior", "anchor"}


def test_independence_root_count_and_multi_model_generator_do_not_double_vote() -> None:
    calendar = _calendar()
    outcomes = _outcomes(calendar)
    index = EventIndex(outcomes.filter(pl.col("split_id") == "TRAIN"), calendar)
    day = calendar["trade_date"][2]
    code = "000001"

    def two_vote(left: str, right: str) -> ComboDefinition:
        left_signal = {"op": "signal", "model": left, "direction": 1}
        right_signal = {"op": "signal", "model": right, "direction": 1}
        return make_combo(
            {
                "op": "and",
                "args": [
                    left_signal,
                    right_signal,
                    {
                        "op": "count",
                        "expr": {"op": "or", "args": [left_signal, right_signal]},
                        "min": 2,
                        "max": 2,
                        "distinct": "independence_root",
                        "sessions": 0,
                    },
                ],
            },
            target_direction=1,
        )

    assert not index.matches(two_vote("S0008", "S0013"), code, day)
    assert index.matches(two_vote("S0008", "S0016"), code, day)

    config = _config()
    relations = ModelRelations()
    single = generate_single_model_candidates(
        outcomes.filter(pl.col("split_id") == "TRAIN"), config, relations
    )
    # The generator contract is exercised through the pipeline-selected seeds
    # below; every emitted multi definition must contain distinct roots only.
    store = SplitOutcomeStore(outcomes)
    result = discover_and_freeze(
        store, calendar, _plan(calendar), config, source_identity=_source()
    )
    assert single
    assert any(
        candidate.discovery_stage in {"C1", "C2"} for candidate in result.candidates
    )
    assert all(
        len(candidate.definition.model_roots)
        == len(set(candidate.definition.model_roots))
        for candidate in result.candidates
    )
    assert not any(
        set(candidate.definition.model_roots) == {"S0008"}
        and candidate.discovery_stage in {"C1", "C2"}
        for candidate in result.candidates
    )


def test_train_validation_only_ranking_freezes_then_reveals_once() -> None:
    calendar = _calendar()
    config = _config()
    store = SplitOutcomeStore(_outcomes(calendar, holdout_scale=-50.0))
    with pytest.raises(HoldoutLockedError, match="HOLDOUT_LOCKED"):
        store.reveal_holdout(None, purpose="PRE_FREEZE_PROBE")
    assert store.successful_holdout_reads == 0

    result = discover_and_freeze(
        store, calendar, _plan(calendar), config, source_identity=_source()
    )
    assert result.rankings
    assert result.search_audit["holdout_rows_read"] == 0
    assert all(row["holdout_state"] == HOLDOUT_LOCKED for row in result.rankings)
    assert all(row["holdout_sample"] is None for row in result.rankings)
    assert "S0007" not in "\n".join(row["canonical_dsl"] for row in result.rankings)

    # Mutating only HOLDOUT outcomes cannot affect candidate discovery, scores,
    # or the frozen order because that split has not been queried.
    other_store = SplitOutcomeStore(_outcomes(calendar, holdout_scale=100.0))
    other = discover_and_freeze(
        other_store, calendar, _plan(calendar), config, source_identity=_source()
    )
    frozen_projection = [
        (row["combo_id"], row["frozen_rank"], row["validation_score"])
        for row in result.rankings
    ]
    assert frozen_projection == [
        (row["combo_id"], row["frozen_rank"], row["validation_score"])
        for row in other.rankings
    ]

    revealed = reveal_holdout(result, store, calendar)
    assert store.successful_holdout_reads == 1
    assert [row["combo_id"] for row in revealed.rankings] == [
        row["combo_id"] for row in result.rankings
    ]
    assert [row["frozen_rank"] for row in revealed.rankings] == [
        row["frozen_rank"] for row in result.rankings
    ]
    assert all(row["holdout_state"] == HOLDOUT_REVEALED for row in revealed.rankings)
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_REVEALED"):
        reveal_holdout(result, store, calendar)
    assert store.successful_holdout_reads == 1


def test_bh_fdr_and_train_sample_density_gates_are_deterministic() -> None:
    adjusted = benjamini_hochberg([("d", 0.5), ("b", 0.02), ("c", 0.2), ("a", 0.01)])
    assert adjusted == pytest.approx({"a": 0.04, "b": 0.04, "c": 0.2 * 4 / 3, "d": 0.5})
    with pytest.raises(ValueError, match="unique"):
        benjamini_hochberg([("same", 0.1), ("same", 0.2)])

    calendar = _calendar()
    sparse = replace(_config(), min_train_density=0.9)
    density_result = discover_and_freeze(
        SplitOutcomeStore(_outcomes(calendar)),
        calendar,
        _plan(calendar),
        sparse,
        source_identity=_source(),
    )
    assert not density_result.rankings
    assert density_result.search_audit["single_rejections"]["MIN_DENSITY"] > 0

    undersampled = replace(_config(), min_train_sample=10_000)
    sample_result = discover_and_freeze(
        SplitOutcomeStore(_outcomes(calendar)),
        calendar,
        _plan(calendar),
        undersampled,
        source_identity=_source(),
    )
    assert not sample_result.rankings
    assert sample_result.search_audit["single_rejections"]["MIN_SAMPLE"] > 0


def test_persistent_holdout_ledger_serializes_independent_worker_stores(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    first_store = SplitOutcomeStore(_outcomes(calendar))
    result = discover_and_freeze(
        first_store,
        calendar,
        _plan(calendar),
        _config(),
        source_identity=_source(),
    )
    second_store = SplitOutcomeStore(_outcomes(calendar))
    second_store.install_freeze(result.freeze_record)
    first_ledger = PersistentHoldoutLedger(tmp_path / "holdout-control")
    second_ledger = PersistentHoldoutLedger(tmp_path / "holdout-control")

    claim = first_ledger.claim(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )
    state = first_ledger.state(result.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "CLAIMED"
    assert state["claim_id"] == claim.claim_id
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_CLAIMED"):
        second_ledger.claim(
            result.freeze_record,
            ranking_set_id=result.ranking_set_id,
            output_dir=tmp_path / "holdout",
        )
    assert first_store.successful_holdout_reads == 0
    assert second_store.successful_holdout_reads == 0


def test_content_addressed_artifact_is_byte_identical_across_two_runs(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    store = SplitOutcomeStore(_outcomes(calendar))
    result = discover_and_freeze(
        store, calendar, _plan(calendar), _config(), source_identity=_source()
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    stale = first.parent / f".{first.name}.staging-{os.getpid()}"
    stale.mkdir()
    (stale / "partial").write_text("interrupted", encoding="utf-8")
    seal_tree_durable(stale)
    one = publish_ranking_artifact(result, first)
    two = publish_ranking_artifact(result, second)
    assert one == two
    assert verify_ranking_artifact(first) == one

    first_files = sorted(
        path.relative_to(first) for path in first.rglob("*") if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second) for path in second.rglob("*") if path.is_file()
    )
    assert first_files == second_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (
            second / relative
        ).read_bytes(), relative
