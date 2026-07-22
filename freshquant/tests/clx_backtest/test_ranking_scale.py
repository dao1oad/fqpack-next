from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from freshquant.backtest.clx.combo_dsl import ModelRelations, make_combo
from freshquant.backtest.clx.event_study import (
    SplitPlan,
    SplitWindow,
    _write_parquet_artifact,
)
from freshquant.backtest.clx.ranking import (
    Candidate,
    HoldoutAlreadyRevealedError,
    LegacyCandidateEvaluator,
    PersistentHoldoutLedger,
    SplitOutcomeStore,
    discover_and_freeze,
    publish_ranking_artifact,
    reveal_holdout,
)
from freshquant.backtest.clx.ranking_bitmap import BitmapCandidateEvaluator
from freshquant.backtest.clx.ranking_io import (
    EventArtifactOutcomeStore,
    build_ranking_artifact,
    load_ranking_result,
    publish_holdout_artifact,
    reveal_ranking_holdout,
    verify_holdout_artifact,
)
from freshquant.tests.clx_backtest.test_ranking import (
    _config,
    _event,
    _outcomes,
    _source,
)


def _calendar() -> pl.DataFrame:
    days: list[date] = []
    for year in (2022, 2023, 2024):
        start = date(year, 1, 1)
        days.extend(start + timedelta(days=index) for index in range(60))
    return pl.DataFrame(
        {"trade_date": days, "session_no": list(range(1, 181))},
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


def _event_artifact(
    root: Path, calendar: pl.DataFrame
) -> tuple[pl.DataFrame, SplitPlan]:
    outcomes = _outcomes(calendar).with_columns(
        (pl.col("code").cast(pl.Int64) % 8).cast(pl.UInt16).alias("code_bucket"),
        pl.col("reveal_date").dt.year().cast(pl.Int16).alias("reveal_year"),
    )
    plan = _plan(calendar)
    artifacts: list[dict[str, object]] = []
    for split_id in ("TRAIN", "VALIDATION", "HOLDOUT"):
        frame = outcomes.filter(pl.col("split_id") == split_id)
        year = int(frame["reveal_year"][0])
        relative = (
            f"code_buckets/code_bucket=000/event_outcomes/"
            f"reveal_year={year}/part-00000.parquet"
        )
        meta = _write_parquet_artifact(
            frame, root / relative, relative, "event_outcomes"
        )
        meta["partition"] = {"code_bucket": 0, "reveal_year": year}
        artifacts.append(meta)
    manifest = {
        "manifest_version": 1,
        "schema_version": "clx-event-study-v1",
        "state": "COMPLETE",
        "run_id": outcomes["run_id"][0],
        "event_set_id": "sha256:" + "a" * 64,
        "split_plan": plan.to_dict(),
        "artifacts": artifacts,
    }
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (root / "manifest.sha256").write_text(
        digest + "  manifest.json\n", encoding="ascii"
    )
    return outcomes, plan


def _metric_projection(result):
    return [metric.to_dict() for metric in result.metrics]


def _reveal_worker(
    label: str,
    event_dir: str,
    calendar_path: str,
    ranking_dir: str,
    output_dir: str,
    ledger_dir: str,
    access_log: str,
    queue,
) -> None:
    try:
        result = reveal_ranking_holdout(
            event_dir,
            pl.read_parquet(calendar_path),
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
        )
    except BaseException as exc:
        queue.put((label, "error", type(exc).__name__, str(exc)))
    else:
        queue.put((label, "ok", result["reveal_id"], ""))


def test_bitmap_pipeline_is_exactly_equivalent_to_legacy_fixture() -> None:
    calendar = _calendar()
    outcomes = _outcomes(calendar)
    plan = _plan(calendar)
    legacy = discover_and_freeze(
        SplitOutcomeStore(outcomes),
        calendar,
        plan,
        _config(),
        source_identity=_source(),
        evaluator_factory=LegacyCandidateEvaluator,
    )
    bitmap = discover_and_freeze(
        SplitOutcomeStore(outcomes),
        calendar,
        plan,
        _config(),
        source_identity=_source(),
    )
    assert bitmap.ranking_set_id == legacy.ranking_set_id
    assert bitmap.freeze_record == legacy.freeze_record
    assert bitmap.rankings == legacy.rankings
    assert [item.definition.combo_id for item in bitmap.candidates] == [
        item.definition.combo_id for item in legacy.candidates
    ]
    assert _metric_projection(bitmap) == _metric_projection(legacy)


def test_temporal_membership_stays_in_code_block_and_nests_on_one_session() -> None:
    calendar = _calendar()
    plan = _plan(calendar)
    rows = [
        # Shifting this final-session event by two used to alias code 000002's
        # first session because encoded code blocks had no temporal guard.
        _event(
            "cross-source",
            calendar,
            179,
            "HOLDOUT",
            code="000001",
            model_id=8,
        ),
        _event(
            "cross-anchor",
            calendar,
            1,
            "TRAIN",
            code="000002",
            model_id=16,
        ),
        # Different sessions must not jointly satisfy WITHIN(AND(A,B),3).
        _event(
            "nested-a-only",
            calendar,
            2,
            "TRAIN",
            code="000003",
            model_id=8,
        ),
        _event(
            "nested-b-only",
            calendar,
            3,
            "TRAIN",
            code="000003",
            model_id=16,
        ),
        _event(
            "nested-anchor-false",
            calendar,
            5,
            "TRAIN",
            code="000003",
            model_id=7,
        ),
        # A complete same-session child two lags back must survive nested
        # WITHIN(SAME_DAY(AND(...)),3).
        _event(
            "nested-a-same",
            calendar,
            3,
            "TRAIN",
            code="000004",
            model_id=8,
        ),
        _event(
            "nested-b-same",
            calendar,
            3,
            "TRAIN",
            code="000004",
            model_id=16,
        ),
        _event(
            "nested-anchor-true",
            calendar,
            5,
            "TRAIN",
            code="000004",
            model_id=7,
        ),
    ]
    context = pl.DataFrame(rows, infer_schema_length=None)
    relations = ModelRelations()
    legacy = LegacyCandidateEvaluator(context, calendar, plan, "TRAIN", relations, 5)
    bitmap = BitmapCandidateEvaluator(context, calendar, plan, "TRAIN", relations, 5)

    cross_code = make_combo(
        {
            "op": "and",
            "args": [
                {"op": "signal", "model": "S0016", "direction": 1},
                {
                    "op": "within",
                    "expr": {"op": "signal", "model": "S0008", "direction": 1},
                    "sessions": 3,
                },
            ],
        },
        target_direction=1,
    )
    cross_candidate = Candidate(cross_code, "REGRESSION", "CROSS_CODE")
    cross_legacy = legacy.evaluate(cross_candidate)
    assert "000002|2022-01-02" not in cross_legacy.membership
    assert bitmap.evaluate(cross_candidate).to_dict() == cross_legacy.to_dict()

    event_pair = {
        "op": "and",
        "args": [
            {"op": "signal", "model": "S0008", "direction": 1},
            {"op": "signal", "model": "S0016", "direction": 1},
        ],
    }
    nested = make_combo(
        {
            "op": "and",
            "args": [
                {"op": "signal", "model": "S0007", "direction": 1},
                {
                    "op": "within",
                    "expr": {"op": "same_day", "expr": event_pair},
                    "sessions": 3,
                },
            ],
        },
        target_direction=1,
    )
    nested_candidate = Candidate(nested, "REGRESSION", "NESTED_TEMPORAL")
    legacy_metric = legacy.evaluate(nested_candidate)
    bitmap_metric = bitmap.evaluate(nested_candidate)
    assert legacy_metric.n_total == 1
    assert legacy_metric.membership == frozenset({"000004|2022-01-06"})
    assert bitmap_metric.to_dict() == legacy_metric.to_dict()


def test_artifact_loader_roundtrip_and_holdout_physical_isolation(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    opens: list[dict[str, object]] = []
    store = EventArtifactOutcomeStore(
        event_dir, plan, access_probe=lambda item: opens.append(dict(item))
    )
    result = discover_and_freeze(
        store,
        calendar,
        plan,
        _config(),
        source_identity=store.source_identity,
    )
    assert store.holdout_file_reads == 0
    assert not [item for item in opens if item["holdout"]]

    ranking_dir = tmp_path / "ranking"
    published = publish_ranking_artifact(result, ranking_dir)
    frozen_bytes = {
        path.relative_to(ranking_dir): path.read_bytes()
        for path in ranking_dir.rglob("*")
        if path.is_file()
    }
    assert all(
        not (path.stat().st_mode & 0o222)
        for path in ranking_dir.rglob("*")
        if path.is_file()
    )
    loaded = load_ranking_result(ranking_dir)
    assert loaded.ranking_set_id == result.ranking_set_id
    assert loaded.freeze_record == result.freeze_record
    assert loaded.rankings == result.rankings
    assert _metric_projection(loaded) == _metric_projection(result)

    reveal_opens: list[dict[str, object]] = []
    reveal_store = EventArtifactOutcomeStore(
        event_dir,
        plan,
        access_probe=lambda item: reveal_opens.append(dict(item)),
    )
    reveal_store.install_freeze(loaded.freeze_record)
    ledger = PersistentHoldoutLedger(tmp_path / "ledger")
    revealed = reveal_holdout(
        loaded,
        reveal_store,
        calendar,
        persistent_ledger=ledger,
    )
    assert reveal_store.holdout_file_reads == 1
    assert [row["combo_id"] for row in revealed.rankings] == [
        row["combo_id"] for row in loaded.rankings
    ]
    assert [row["frozen_rank"] for row in revealed.rankings] == [
        row["frozen_rank"] for row in loaded.rankings
    ]
    holdout_dir = tmp_path / "holdout"
    holdout = publish_holdout_artifact(
        revealed,
        loaded,
        holdout_dir,
        ranking_manifest_sha256=published["manifest_sha256"],
    )
    assert verify_holdout_artifact(holdout_dir) == holdout
    holdout_manifest = json.loads(
        (holdout_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert holdout_manifest["successful_holdout_reads"] == 1
    assert holdout_manifest["holdout_state"] == "REVEALED"
    assert frozen_bytes == {
        path.relative_to(ranking_dir): path.read_bytes()
        for path in ranking_dir.rglob("*")
        if path.is_file()
    }

    second_opens: list[dict[str, object]] = []
    second_store = EventArtifactOutcomeStore(
        event_dir,
        plan,
        access_probe=lambda item: second_opens.append(dict(item)),
    )
    second_store.install_freeze(loaded.freeze_record)
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_COMPLETE"):
        reveal_holdout(
            loaded,
            second_store,
            calendar,
            persistent_ledger=PersistentHoldoutLedger(tmp_path / "ledger"),
        )
    assert second_store.holdout_file_reads == 0
    assert second_opens == []


def test_claimed_crash_fails_closed_before_any_holdout_open(tmp_path: Path) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    store = EventArtifactOutcomeStore(event_dir, plan)
    result = discover_and_freeze(
        store,
        calendar,
        plan,
        _config(),
        source_identity=store.source_identity,
    )
    ledger = PersistentHoldoutLedger(tmp_path / "crash-ledger")
    claim = ledger.claim(result.freeze_record, ranking_set_id=result.ranking_set_id)
    assert ledger.state(result.freeze_record["freeze_id"])["claim_id"] == claim.claim_id

    opens: list[dict[str, object]] = []
    restarted = EventArtifactOutcomeStore(
        event_dir, plan, access_probe=lambda item: opens.append(dict(item))
    )
    restarted.install_freeze(result.freeze_record)
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_CLAIMED"):
        reveal_holdout(
            result,
            restarted,
            calendar,
            persistent_ledger=PersistentHoldoutLedger(tmp_path / "crash-ledger"),
        )
    assert restarted.holdout_file_reads == 0
    assert opens == []


def test_build_is_resumable_and_two_fresh_runs_are_byte_identical(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    first = tmp_path / "ranking-one"
    second = tmp_path / "ranking-two"
    one = build_ranking_artifact(event_dir, calendar, plan, _config(), first)
    resumed = build_ranking_artifact(event_dir, calendar, plan, _config(), first)
    two = build_ranking_artifact(event_dir, calendar, plan, _config(), second)
    assert resumed["ranking_set_id"] == one["ranking_set_id"]
    assert two["ranking_set_id"] == one["ranking_set_id"]
    first_files = sorted(
        path.relative_to(first) for path in first.rglob("*") if path.is_file()
    )
    second_files = sorted(
        path.relative_to(second) for path in second.rglob("*") if path.is_file()
    )
    assert first_files == second_files
    for relative in first_files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_two_processes_share_one_claim_and_loser_opens_zero_event_files(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    calendar_path = tmp_path / "calendar.parquet"
    calendar.write_parquet(calendar_path)
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)

    context = mp.get_context("spawn")
    queue = context.Queue()
    processes = []
    labels = ("one", "two")
    for label in labels:
        process = context.Process(
            target=_reveal_worker,
            args=(
                label,
                str(event_dir),
                str(calendar_path),
                str(ranking_dir),
                str(tmp_path / f"holdout-{label}"),
                str(tmp_path / "shared-ledger"),
                str(tmp_path / f"access-{label}.jsonl"),
                queue,
            ),
        )
        process.start()
        processes.append(process)
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=2) for _ in processes]
    winners = [item for item in outcomes if item[1] == "ok"]
    losers = [item for item in outcomes if item[1] == "error"]
    assert len(winners) == len(losers) == 1
    assert losers[0][2] == "HoldoutAlreadyRevealedError"
    loser_log = tmp_path / f"access-{losers[0][0]}.jsonl"
    assert not loser_log.exists() or loser_log.read_text(encoding="utf-8") == ""
    winner_artifact = tmp_path / f"holdout-{winners[0][0]}"
    assert verify_holdout_artifact(winner_artifact)["reveal_id"] == winners[0][2]
