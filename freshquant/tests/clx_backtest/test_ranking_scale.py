from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import freshquant.backtest.clx.ranking as ranking_module
import freshquant.backtest.clx.ranking_io as ranking_io
from freshquant.backtest.clx._file_lock import seal_tree_durable
from freshquant.backtest.clx.combo_dsl import ModelRelations, make_combo
from freshquant.backtest.clx.event_study import (
    DIRECTION_ADJUSTED_EXCURSION_CONTRACT,
    DIRECTION_ADJUSTED_RETURN_CONTRACT,
    EVENT_STUDY_SCHEMA_VERSION,
    SplitPlan,
    SplitWindow,
    _write_parquet_artifact,
)
from freshquant.backtest.clx.ranking import (
    Candidate,
    HoldoutAlreadyRevealedError,
    LegacyCandidateEvaluator,
    PersistentHoldoutLedger,
    RankingError,
    SplitOutcomeStore,
    _content_id,
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
        "schema_version": EVENT_STUDY_SCHEMA_VERSION,
        "state": "COMPLETE",
        "run_id": outcomes["run_id"][0],
        "event_set_id": "sha256:" + "a" * 64,
        "split_plan": plan.to_dict(),
        "identity": {
            "direction_adjusted_return": DIRECTION_ADJUSTED_RETURN_CONTRACT,
            "direction_adjusted_excursions": DIRECTION_ADJUSTED_EXCURSION_CONTRACT,
        },
        "event_clock": {
            "direction_adjusted_return": DIRECTION_ADJUSTED_RETURN_CONTRACT,
            "direction_adjusted_excursions": DIRECTION_ADJUSTED_EXCURSION_CONTRACT,
        },
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


def _resume_reveal_worker(
    label: str,
    event_dir: str,
    calendar_path: str,
    ranking_dir: str,
    output_dir: str,
    ledger_dir: str,
    access_log: str,
    queue,
) -> None:
    """Run an authorized resume with a scheduling pause after its claim."""

    original_resume = PersistentHoldoutLedger.resume_claimed

    def delayed_resume(self, *args, **kwargs):
        claim = original_resume(self, *args, **kwargs)
        # This makes the pre-execution-lock implementation overlap both
        # physical reads; the fixed implementation holds the lock throughout.
        time.sleep(0.25)
        return claim

    setattr(PersistentHoldoutLedger, "resume_claimed", delayed_resume)
    try:
        result = reveal_ranking_holdout(
            event_dir,
            pl.read_parquet(calendar_path),
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
            resume_claimed=True,
        )
    except BaseException as exc:
        queue.put((label, "error", type(exc).__name__, str(exc)))
    else:
        queue.put((label, "ok", result["reveal_id"], ""))


def _published_holdout_artifact(root: Path) -> Path:
    calendar = _calendar()
    event_dir = root / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = root / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    holdout_dir = root / "holdout"
    reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        holdout_dir,
        root / "ledger",
    )
    return holdout_dir


def _external_open_event(
    store: EventArtifactOutcomeStore, *, sequence: int, path: str = "fixture.parquet"
) -> dict[str, object]:
    return {
        "schema_version": ranking_io.EVENT_ACCESS_SCHEMA_VERSION,
        **store._audit_identity(),
        "sequence": sequence,
        "operation": "OPEN_PARQUET",
        "purpose": "TEST_AUDIT",
        "dataset": "event_outcomes",
        "path": path,
        "holdout": False,
        "decision": "ALLOW",
    }


def _rewrite_holdout_manifest(root: Path, manifest: dict[str, Any]) -> None:
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    manifest_path.chmod(0o644)
    sidecar_path.chmod(0o644)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    sidecar_path.write_text(
        hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "  manifest.json\n",
        encoding="ascii",
    )
    manifest_path.chmod(0o444)
    sidecar_path.chmod(0o444)


def _rewrite_holdout_json_dataset(
    root: Path,
    manifest: dict[str, Any],
    dataset: str,
    document: list[dict[str, Any]],
) -> None:
    meta = next(
        item
        for item in manifest["artifacts"]
        if isinstance(item, dict) and item.get("dataset") == dataset
    )
    path = root / str(meta["path"])
    path.chmod(0o644)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    meta["rows"] = len(document)
    meta["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    meta["logical_sha256"] = _content_id(document)
    path.chmod(0o444)


def test_ranking_store_rejects_previous_event_outcome_semantics(tmp_path: Path) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    manifest_path = event_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "clx-event-study-v1"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (event_dir / "manifest.sha256").write_text(
        hashlib.sha256(manifest_path.read_bytes()).hexdigest() + "  manifest.json\n",
        encoding="ascii",
    )

    with pytest.raises(RankingError, match="schema/outcome contract"):
        EventArtifactOutcomeStore(event_dir, plan)


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
    claim = ledger.claim(
        loaded.freeze_record,
        ranking_set_id=loaded.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )
    revealed = reveal_holdout(loaded, reveal_store, calendar)
    assert reveal_store.holdout_file_reads == 1
    assert [row["combo_id"] for row in revealed.rankings] == [
        row["combo_id"] for row in loaded.rankings
    ]
    assert [row["frozen_rank"] for row in revealed.rankings] == [
        row["frozen_rank"] for row in loaded.rankings
    ]
    holdout_dir = tmp_path / "holdout"
    stale = holdout_dir.parent / f".{holdout_dir.name}.staging-{os.getpid()}"
    stale.mkdir()
    (stale / "partial").write_text("interrupted", encoding="utf-8")
    seal_tree_durable(stale)
    holdout = publish_holdout_artifact(
        revealed,
        loaded,
        holdout_dir,
        ranking_manifest_sha256=published["manifest_sha256"],
    )
    ledger.complete(
        claim, reveal_id=revealed.reveal_id, output_dir=tmp_path / "holdout"
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
        PersistentHoldoutLedger(tmp_path / "ledger").claim(
            loaded.freeze_record,
            ranking_set_id=loaded.ranking_set_id,
            output_dir=tmp_path / "holdout",
        )
    assert second_store.holdout_file_reads == 0
    assert second_opens == []


def test_holdout_verifier_recomputes_reveal_content_id(tmp_path: Path) -> None:
    holdout_dir = _published_holdout_artifact(tmp_path)
    manifest = json.loads((holdout_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["reveal_id"] = "sha256:" + "f" * 64
    _rewrite_holdout_manifest(holdout_dir, manifest)

    with pytest.raises(RankingError, match="reveal content id mismatch"):
        verify_holdout_artifact(holdout_dir)


def test_holdout_verifier_requires_unique_physical_read_proof(tmp_path: Path) -> None:
    holdout_dir = _published_holdout_artifact(tmp_path)
    manifest = json.loads((holdout_dir / "manifest.json").read_text(encoding="utf-8"))
    audit_meta = next(
        item
        for item in manifest["artifacts"]
        if item["dataset"] == "event_access_audit"
    )
    audit = json.loads((holdout_dir / audit_meta["path"]).read_text(encoding="utf-8"))
    allow = next(
        row
        for row in audit
        if row.get("purpose") == "FINAL_REVEAL" and row.get("decision") == "ALLOW"
    )
    allow["decision"] = "DENY"
    _rewrite_holdout_json_dataset(holdout_dir, manifest, "event_access_audit", audit)
    _rewrite_holdout_manifest(holdout_dir, manifest)

    with pytest.raises(RankingError, match="unique physical reveal proof"):
        verify_holdout_artifact(holdout_dir)


def test_holdout_verifier_cross_checks_ranking_and_parquet_metrics(
    tmp_path: Path,
) -> None:
    holdout_dir = _published_holdout_artifact(tmp_path)
    manifest = json.loads((holdout_dir / "manifest.json").read_text(encoding="utf-8"))
    ranking_meta = next(
        item for item in manifest["artifacts"] if item["dataset"] == "holdout_rankings"
    )
    rankings = json.loads(
        (holdout_dir / ranking_meta["path"]).read_text(encoding="utf-8")
    )
    metric = rankings[0]["holdout_metrics"]
    metric["mean_return"] = float(metric.get("mean_return") or 0.0) + 1.0
    _rewrite_holdout_json_dataset(holdout_dir, manifest, "holdout_rankings", rankings)
    manifest["reveal_id"] = _content_id(
        {
            "freeze_id": manifest["freeze_id"],
            "ranking_set_id": manifest["ranking_set_id"],
            "frozen_order": manifest["frozen_order"],
            "holdout_metric_digests": {
                row["combo_id"]: _content_id(row["holdout_metrics"]) for row in rankings
            },
            "successful_holdout_reads": 1,
        }
    )
    _rewrite_holdout_manifest(holdout_dir, manifest)

    with pytest.raises(RankingError, match="ranking/parquet metrics differ"):
        verify_holdout_artifact(holdout_dir)


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
    claim = ledger.claim(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )
    state = ledger.state(result.freeze_record["freeze_id"])
    assert state is not None
    assert state["claim_id"] == claim.claim_id
    assert state["resume_count"] == 0
    assert state["resume_audit"] == []

    opens: list[dict[str, object]] = []
    restarted = EventArtifactOutcomeStore(
        event_dir, plan, access_probe=lambda item: opens.append(dict(item))
    )
    restarted.install_freeze(result.freeze_record)
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_CLAIMED"):
        PersistentHoldoutLedger(tmp_path / "crash-ledger").claim(
            result.freeze_record,
            ranking_set_id=result.ranking_set_id,
            output_dir=tmp_path / "holdout",
        )
    assert restarted.holdout_file_reads == 0
    assert opens == []


def test_claimed_resume_requires_exact_identity_and_rejects_complete(
    tmp_path: Path,
) -> None:
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
    ledger = PersistentHoldoutLedger(tmp_path / "ledger")
    claim = ledger.claim(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )

    with pytest.raises(RankingError, match="output differs"):
        ledger.complete(
            claim,
            reveal_id="sha256:" + "a" * 64,
            output_dir=tmp_path / "other-holdout",
        )
    with pytest.raises(RankingError, match="output differs"):
        ledger.reconcile_complete(
            freeze_id=result.freeze_record["freeze_id"],
            ranking_set_id=result.ranking_set_id,
            reveal_id="sha256:" + "a" * 64,
            output_dir=tmp_path / "other-holdout",
        )
    state = ledger.state(result.freeze_record["freeze_id"])
    assert state is not None and state["resume_count"] == 0

    with pytest.raises(RankingError, match="ranking identity differs"):
        ledger.resume_claimed(
            result.freeze_record,
            ranking_set_id="sha256:" + "e" * 64,
            claim_id=claim.claim_id,
            output_dir=tmp_path / "holdout",
        )
    with pytest.raises(RankingError, match="claim identity differs"):
        ledger.resume_claimed(
            result.freeze_record,
            ranking_set_id=result.ranking_set_id,
            claim_id="sha256:" + "f" * 64,
            output_dir=tmp_path / "holdout",
        )

    changed_freeze = dict(result.freeze_record)
    changed_freeze["run_id"] = "different-run"
    changed_payload = dict(changed_freeze)
    changed_payload.pop("freeze_id")
    changed_freeze["freeze_id"] = _content_id(changed_payload)
    changed_claim_id = _content_id(
        {
            "ledger_schema_version": "clx-holdout-ledger-v1",
            "freeze_id": changed_freeze["freeze_id"],
            "ranking_set_id": result.ranking_set_id,
            "state": "CLAIMED",
        }
    )
    with pytest.raises(RankingError, match="existing CLAIMED claim"):
        ledger.resume_claimed(
            changed_freeze,
            ranking_set_id=result.ranking_set_id,
            claim_id=changed_claim_id,
            output_dir=tmp_path / "holdout",
        )

    ledger.complete(
        claim,
        reveal_id="sha256:" + "a" * 64,
        output_dir=tmp_path / "holdout",
    )
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_COMPLETE"):
        ledger.resume_claimed(
            result.freeze_record,
            ranking_set_id=result.ranking_set_id,
            claim_id=claim.claim_id,
            output_dir=tmp_path / "holdout",
        )


def test_persistent_ledger_flushes_claim_and_state_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    synced: list[Path] = []
    monkeypatch.setattr(
        ranking_module,
        "fsync_directory",
        lambda path: synced.append(Path(path).resolve()),
    )

    ledger = PersistentHoldoutLedger(tmp_path / "durable-ledger")
    claim = ledger.claim(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )
    claim_dir = claim.state_path.parent.resolve()
    assert claim.attempt_no == 0
    assert ledger.root in synced
    assert claim_dir in synced

    synced.clear()
    resumed = ledger.resume_claimed(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        claim_id=claim.claim_id,
        output_dir=tmp_path / "holdout",
    )
    assert resumed.attempt_no == 1
    assert synced == [claim_dir]

    synced.clear()
    with pytest.raises(RankingError, match="claim attempt is stale"):
        ledger.complete(
            claim,
            reveal_id="sha256:" + "a" * 64,
            output_dir=tmp_path / "holdout",
        )
    assert synced == []
    ledger.complete(
        resumed,
        reveal_id="sha256:" + "a" * 64,
        output_dir=tmp_path / "holdout",
    )
    assert synced == [claim_dir]


def test_persistent_ledger_recovers_only_the_empty_pre_state_claim_window(
    tmp_path: Path,
) -> None:
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
    ledger = PersistentHoldoutLedger(tmp_path / "empty-claim-ledger")
    claim_dir = ledger.root / result.freeze_record["freeze_id"].removeprefix("sha256:")
    claim_dir.mkdir()
    stale_temp = claim_dir / (".state.json.tmp-123-" + "a" * 32)
    stale_temp.write_text("partial", encoding="utf-8")

    claim = ledger.claim(
        result.freeze_record,
        ranking_set_id=result.ranking_set_id,
        output_dir=tmp_path / "holdout",
    )
    assert claim.attempt_no == 0
    state = ledger.state(result.freeze_record["freeze_id"])
    assert state is not None
    assert state["claim_id"] == claim.claim_id
    assert state["resume_count"] == 0
    assert not stale_temp.exists()

    changed = dict(result.freeze_record)
    changed["run_id"] = "different-run"
    changed_payload = dict(changed)
    changed_payload.pop("freeze_id")
    changed["freeze_id"] = _content_id(changed_payload)
    corrupt_dir = ledger.root / changed["freeze_id"].removeprefix("sha256:")
    corrupt_dir.mkdir()
    (corrupt_dir / "unexpected").write_text("conflict", encoding="utf-8")
    with pytest.raises(HoldoutAlreadyRevealedError, match="CLAIMED_CORRUPT_STATE"):
        ledger.claim(
            changed,
            ranking_set_id=result.ranking_set_id,
            output_dir=tmp_path / "holdout",
        )


def test_external_access_audit_writes_all_bytes_and_syncs_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    access_log = tmp_path / "audit/access.jsonl"
    store = EventArtifactOutcomeStore(event_dir, plan, access_log=access_log)
    real_write = ranking_io.os.write
    writes = 0

    def partial_write(descriptor: int, payload) -> int:
        nonlocal writes
        writes += 1
        chunk = max(1, len(payload) // 2)
        return real_write(descriptor, payload[:chunk])

    synced: list[Path] = []
    monkeypatch.setattr(ranking_io.os, "write", partial_write)
    monkeypatch.setattr(
        ranking_io,
        "fsync_directory",
        lambda path: synced.append(Path(path).resolve()),
    )
    event = _external_open_event(store, sequence=1, path="x" * 100)

    store._append_external_audit(event)

    assert writes > 1
    assert json.loads(access_log.read_text(encoding="utf-8")) == event
    assert synced == [access_log.parent.resolve()]


@pytest.mark.parametrize(
    "existing",
    [
        b'{"operation":\n',
        b'{"operation":"OPEN_PARQUET"}\n',
    ],
)
def test_external_access_audit_rejects_terminated_invalid_records(
    tmp_path: Path, existing: bytes
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    access_log = tmp_path / "audit/access.jsonl"
    access_log.parent.mkdir(parents=True)
    access_log.write_bytes(existing)
    store = EventArtifactOutcomeStore(event_dir, plan, access_log=access_log)

    with pytest.raises(RankingError, match="external event access audit"):
        store._append_external_audit(_external_open_event(store, sequence=1))

    assert access_log.read_bytes() == existing


def test_external_access_audit_rejects_invalid_complete_repair_history(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    access_log = tmp_path / "audit/access.jsonl"
    access_log.parent.mkdir(parents=True)
    store = EventArtifactOutcomeStore(event_dir, plan, access_log=access_log)
    recovered = _external_open_event(store, sequence=1)
    repair = {
        "schema_version": ranking_io.EVENT_ACCESS_SCHEMA_VERSION,
        **store._audit_identity(),
        "operation": ranking_io.EVENT_ACCESS_REPAIR_OPERATION,
        "purpose": "RECOVER_EXTERNAL_AUDIT",
        "decision": "ALLOW",
        "reason": "UNTERMINATED_JSONL_TAIL_TRUNCATED",
        "repair_sequence": 1,
        "truncate_offset": 1,
        "truncated_bytes": 10,
        "truncated_sha256": "a" * 64,
        "complete_records_before_repair": 0,
        "recovery_operation": "OPEN_PARQUET",
    }
    existing = b"".join(
        (json.dumps(row, sort_keys=True) + "\n").encode("utf-8")
        for row in (repair, recovered)
    )
    access_log.write_bytes(existing)

    with pytest.raises(RankingError, match="repair history is invalid"):
        store._append_external_audit(_external_open_event(store, sequence=2))

    assert access_log.read_bytes() == existing


def test_external_access_audit_serializes_concurrent_short_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    access_log = tmp_path / "audit/access.jsonl"
    store = EventArtifactOutcomeStore(event_dir, plan, access_log=access_log)
    real_write = ranking_io.os.write
    writes = 0

    def short_write(descriptor: int, payload) -> int:
        nonlocal writes
        writes += 1
        return real_write(descriptor, payload[: min(7, len(payload))])

    monkeypatch.setattr(ranking_io.os, "write", short_write)
    events = [
        _external_open_event(store, sequence=index, path=f"fixture-{index}.parquet")
        for index in range(1, 25)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(store._append_external_audit, events))

    rows = [
        json.loads(line) for line in access_log.read_text(encoding="utf-8").splitlines()
    ]
    assert writes > len(events)
    assert len(rows) == len(events)
    assert {row["sequence"] for row in rows} == set(range(1, len(events) + 1))


def test_partial_external_audit_write_is_repaired_by_authorized_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    loaded = load_ranking_result(ranking_dir)
    output_dir = tmp_path / "holdout"
    ledger_dir = tmp_path / "ledger"
    access_log = tmp_path / "access.jsonl"
    real_write = ranking_io.os.write
    writes = 0

    def fail_after_partial_write(descriptor: int, payload) -> int:
        nonlocal writes
        if writes == 0:
            writes += 1
            chunk = max(1, len(payload) // 2)
            return real_write(descriptor, payload[:chunk])
        raise OSError("fixture interrupted external audit write")

    monkeypatch.setattr(ranking_io.os, "write", fail_after_partial_write)
    with pytest.raises(OSError, match="interrupted external audit write"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
        )

    partial_tail = access_log.read_bytes()
    assert partial_tail and not partial_tail.endswith(b"\n")
    state = PersistentHoldoutLedger(ledger_dir).state(loaded.freeze_record["freeze_id"])
    assert state is not None and state["state"] == "CLAIMED"
    assert state["resume_count"] == 0

    monkeypatch.setattr(ranking_io.os, "write", real_write)
    resumed = reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        output_dir,
        ledger_dir,
        access_log=access_log,
        resume_claimed=True,
    )

    assert verify_holdout_artifact(output_dir) == resumed
    raw_lines = access_log.read_bytes().splitlines(keepends=True)
    assert raw_lines and all(line.endswith(b"\n") for line in raw_lines)
    rows = [json.loads(line) for line in raw_lines]
    repair = rows[0]
    assert repair["operation"] == ranking_io.EVENT_ACCESS_REPAIR_OPERATION
    assert repair["attempt_no"] == 1
    assert repair["repair_sequence"] == 1
    assert repair["truncate_offset"] == 0
    assert repair["complete_records_before_repair"] == 0
    assert repair["truncated_bytes"] == len(partial_tail)
    assert repair["truncated_sha256"] == hashlib.sha256(partial_tail).hexdigest()
    assert repair["recovery_operation"] == rows[1]["operation"] == "REVEAL_HOLDOUT"
    assert rows[1]["attempt_no"] == 1
    state = PersistentHoldoutLedger(ledger_dir).state(loaded.freeze_record["freeze_id"])
    assert state is not None and state["state"] == "COMPLETE"
    assert state["resume_count"] == 1


def test_publish_failure_defaults_fail_closed_then_explicit_same_claim_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    loaded = load_ranking_result(ranking_dir)
    output_dir = tmp_path / "holdout"
    ledger_dir = tmp_path / "ledger"
    access_log = tmp_path / "access.jsonl"
    original_publish = ranking_io.publish_holdout_artifact

    def fail_publish(*args, **kwargs):
        raise RuntimeError("fixture publish interruption")

    monkeypatch.setattr(ranking_io, "publish_holdout_artifact", fail_publish)
    with pytest.raises(RuntimeError, match="publish interruption"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
        )

    ledger = PersistentHoldoutLedger(ledger_dir)
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None and state["state"] == "CLAIMED"
    assert state["resume_count"] == 0
    assert state["resume_audit"] == []
    assert not output_dir.exists()
    before = access_log.read_text(encoding="utf-8")
    frozen_ranking = {
        path.relative_to(ranking_dir): path.read_bytes()
        for path in ranking_dir.rglob("*")
        if path.is_file()
    }

    monkeypatch.setattr(ranking_io, "publish_holdout_artifact", original_publish)
    with pytest.raises(HoldoutAlreadyRevealedError, match="ALREADY_CLAIMED"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
        )
    assert access_log.read_text(encoding="utf-8") == before

    resumed = reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        output_dir,
        ledger_dir,
        access_log=access_log,
        resume_claimed=True,
    )
    assert verify_holdout_artifact(output_dir) == resumed
    assert frozen_ranking == {
        path.relative_to(ranking_dir): path.read_bytes()
        for path in ranking_dir.rglob("*")
        if path.is_file()
    }
    access = [
        json.loads(line) for line in access_log.read_text(encoding="utf-8").splitlines()
    ]
    logical_reveals = [
        item
        for item in access
        if item.get("operation") == "REVEAL_HOLDOUT" and item.get("decision") == "ALLOW"
    ]
    holdout_opens = [
        item
        for item in access
        if item.get("operation") == "OPEN_PARQUET" and item.get("holdout") is True
    ]
    assert len(logical_reveals) == 2
    assert len(holdout_opens) == 2
    assert {item["attempt_no"] for item in logical_reveals} == {0, 1}
    assert {item["attempt_no"] for item in holdout_opens} == {0, 1}
    assert {item["run_id"] for item in access} == {loaded.run_id}
    assert {item["freeze_id"] for item in access} == {loaded.freeze_record["freeze_id"]}
    assert len({item["claim_id"] for item in access}) == 1
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "COMPLETE"
    assert state["resume_count"] == 1
    assert state["resume_audit"] == [
        {
            "action": "RESUME_CLAIMED",
            "claim_id": state["claim_id"],
            "freeze_id": loaded.freeze_record["freeze_id"],
            "ranking_set_id": loaded.ranking_set_id,
            "resume_count": 1,
        }
    ]


def test_resume_flag_keeps_clean_first_reveal_as_the_initial_claim(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    loaded = load_ranking_result(ranking_dir)
    ledger_dir = tmp_path / "ledger"

    published = reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        tmp_path / "holdout",
        ledger_dir,
        resume_claimed=True,
    )

    assert published["status"] == "verified"
    state = PersistentHoldoutLedger(ledger_dir).state(loaded.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "COMPLETE"
    assert state["resume_count"] == 0
    assert state["resume_audit"] == []


@pytest.mark.parametrize(
    ("extra_args", "expected_resume"),
    [([], False), (["--resume-claimed"], True)],
)
def test_reveal_cli_enables_claimed_resume_only_with_explicit_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    expected_resume: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    calendar = pl.DataFrame(
        {"trade_date": [date(2024, 1, 2)], "session_no": [1]},
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )

    monkeypatch.setattr(ranking_io, "_read_calendar", lambda _path: calendar)

    def fake_reveal(
        event_dir,
        received_calendar,
        ranking_dir,
        output_dir,
        ledger_dir,
        *,
        access_log=None,
        resume_claimed=False,
    ):
        observed.update(
            {
                "calendar": received_calendar,
                "resume_claimed": resume_claimed,
            }
        )
        return {"status": "verified"}

    monkeypatch.setattr(ranking_io, "reveal_ranking_holdout", fake_reveal)
    arguments = [
        "reveal",
        "--event-dir",
        str(tmp_path / "events"),
        "--calendar",
        str(tmp_path / "calendar.parquet"),
        "--ranking-dir",
        str(tmp_path / "ranking"),
        "--output-dir",
        str(tmp_path / "holdout"),
        "--ledger-dir",
        str(tmp_path / "ledger"),
        *extra_args,
    ]

    assert ranking_io.main(arguments) == 0
    assert observed["calendar"] is calendar
    assert observed["resume_claimed"] is expected_resume
    assert json.loads(capsys.readouterr().out) == {"status": "verified"}


def test_published_artifact_reconciles_claim_after_completion_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    loaded = load_ranking_result(ranking_dir)
    output_dir = tmp_path / "holdout"
    ledger_dir = tmp_path / "ledger"
    access_log = tmp_path / "access.jsonl"
    original_complete = PersistentHoldoutLedger.complete

    def fail_complete(self, claim, *, reveal_id, output_dir=None):
        raise RuntimeError("fixture ledger completion interruption")

    monkeypatch.setattr(PersistentHoldoutLedger, "complete", fail_complete)
    with pytest.raises(RuntimeError, match="completion interruption"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            output_dir,
            ledger_dir,
            access_log=access_log,
        )

    published = verify_holdout_artifact(output_dir)
    ledger = PersistentHoldoutLedger(ledger_dir)
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None and state["state"] == "CLAIMED"
    before = access_log.read_text(encoding="utf-8")

    monkeypatch.setattr(PersistentHoldoutLedger, "complete", original_complete)
    other_output = tmp_path / "holdout-other"
    other_access_log = tmp_path / "other-access.jsonl"
    with pytest.raises(RankingError, match="output differs"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            other_output,
            ledger_dir,
            access_log=other_access_log,
            resume_claimed=True,
        )
    assert not other_output.exists()
    assert not other_access_log.exists()
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "CLAIMED"
    assert state["resume_count"] == 0
    assert access_log.read_text(encoding="utf-8") == before

    resumed = reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        output_dir,
        ledger_dir,
        access_log=access_log,
    )
    assert resumed == published
    assert access_log.read_text(encoding="utf-8") == before
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "COMPLETE"
    assert state["reveal_id"] == published["reveal_id"]


def test_published_artifact_without_persistent_claim_fails_closed_without_reread(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    output_dir = tmp_path / "holdout"
    access_log = tmp_path / "access.jsonl"
    reveal_ranking_holdout(
        event_dir,
        calendar,
        ranking_dir,
        output_dir,
        tmp_path / "original-ledger",
        access_log=access_log,
    )
    before = access_log.read_text(encoding="utf-8")

    with pytest.raises(RankingError, match="persistent HOLDOUT claim is missing"):
        reveal_ranking_holdout(
            event_dir,
            calendar,
            ranking_dir,
            output_dir,
            tmp_path / "missing-ledger",
            access_log=access_log,
        )
    assert access_log.read_text(encoding="utf-8") == before


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


def test_build_resume_rejects_changed_calendar_session_identity(tmp_path: Path) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    changed_rows = list(calendar.iter_rows(named=True))
    changed_rows[0]["trade_date"], changed_rows[1]["trade_date"] = (
        changed_rows[1]["trade_date"],
        changed_rows[0]["trade_date"],
    )
    changed_calendar = pl.DataFrame(changed_rows, schema=calendar.schema)

    with pytest.raises(RankingError, match="another build"):
        build_ranking_artifact(
            event_dir,
            changed_calendar,
            plan,
            _config(),
            ranking_dir,
        )


def test_holdout_reveal_rejects_changed_calendar_before_claim_or_read(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    changed_rows = list(calendar.iter_rows(named=True))
    changed_rows[-2]["trade_date"], changed_rows[-1]["trade_date"] = (
        changed_rows[-1]["trade_date"],
        changed_rows[-2]["trade_date"],
    )
    changed_calendar = pl.DataFrame(changed_rows, schema=calendar.schema)
    access_log = tmp_path / "access.jsonl"
    ledger_dir = tmp_path / "ledger"

    with pytest.raises(RankingError, match="calendar differs"):
        reveal_ranking_holdout(
            event_dir,
            changed_calendar,
            ranking_dir,
            tmp_path / "holdout",
            ledger_dir,
            access_log=access_log,
        )

    assert not access_log.exists()
    assert list(ledger_dir.iterdir()) == []


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


def test_two_resume_processes_with_different_outputs_share_one_execution(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    calendar_path = tmp_path / "calendar.parquet"
    calendar.write_parquet(calendar_path)
    event_dir = tmp_path / "events"
    _, plan = _event_artifact(event_dir, calendar)
    ranking_dir = tmp_path / "ranking"
    build_ranking_artifact(event_dir, calendar, plan, _config(), ranking_dir)
    loaded = load_ranking_result(ranking_dir)
    ledger_dir = tmp_path / "shared-ledger"
    ledger = PersistentHoldoutLedger(ledger_dir)
    ledger.claim(
        loaded.freeze_record,
        ranking_set_id=loaded.ranking_set_id,
        output_dir=tmp_path / "resume-holdout-one",
    )

    context = mp.get_context("spawn")
    queue = context.Queue()
    processes = []
    labels = ("one", "two")
    for label in labels:
        process = context.Process(
            target=_resume_reveal_worker,
            args=(
                label,
                str(event_dir),
                str(calendar_path),
                str(ranking_dir),
                str(tmp_path / f"resume-holdout-{label}"),
                str(ledger_dir),
                str(tmp_path / f"resume-access-{label}.jsonl"),
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
    assert losers[0][2] == "RankingError"
    assert "output differs" in losers[0][3]

    holdout_opens = 0
    reveal_allows = 0
    for label in labels:
        access_log = tmp_path / f"resume-access-{label}.jsonl"
        if not access_log.exists():
            continue
        for raw_line in access_log.read_text(encoding="utf-8").splitlines():
            event = json.loads(raw_line)
            if (
                event.get("operation") == "OPEN_PARQUET"
                and event.get("holdout") is True
                and event.get("decision") == "ALLOW"
            ):
                holdout_opens += 1
            if (
                event.get("operation") == "REVEAL_HOLDOUT"
                and event.get("decision") == "ALLOW"
            ):
                reveal_allows += 1
    assert holdout_opens == 1
    assert reveal_allows == 1
    winner_artifact = tmp_path / f"resume-holdout-{winners[0][0]}"
    assert verify_holdout_artifact(winner_artifact)["reveal_id"] == winners[0][2]
    loser_artifact = tmp_path / f"resume-holdout-{losers[0][0]}"
    assert not loser_artifact.exists()
    state = ledger.state(loaded.freeze_record["freeze_id"])
    assert state is not None
    assert state["state"] == "COMPLETE"
    assert state["resume_count"] == 1
    assert len(state["resume_audit"]) == 1
