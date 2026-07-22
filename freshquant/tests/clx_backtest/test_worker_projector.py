from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from flask import Flask
from pymongo import MongoClient

from freshquant.rear.clx_backtest.projector import (
    ClxArtifactProjector,
    ProjectionError,
)
from freshquant.rear.clx_backtest.routes import create_clx_backtest_blueprint
from freshquant.rear.clx_backtest.runner import ExportRunner
from freshquant.rear.clx_backtest.runner import (
    BacktestPipelineRunner,
    JobCancelled,
    SubprocessStageExecutor,
    resolve_pipeline_layout,
)
from freshquant.rear.clx_backtest.store import (
    DERIVED_DATABASE_NAME,
    INDEX_DEFINITIONS,
    MemoryClxBacktestStore,
    MongoClxBacktestStore,
)
from freshquant.rear.clx_backtest.utils import content_hash
from freshquant.rear.clx_backtest.worker_store import MongoWorkerStore


def _file_meta(root: Path, relative: str, dataset: str, frame: pl.DataFrame):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return {
        "dataset": dataset,
        "path": relative,
        "rows": frame.height,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _json_meta(root: Path, relative: str, dataset: str, rows: list[dict]):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
    return {
        "dataset": dataset,
        "path": relative,
        "rows": len(rows),
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _manifest(root: Path, document: dict) -> str:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "manifest.json"
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.sha256").write_text(
        digest + "  manifest.json\n",
        encoding="ascii",
    )
    return "sha256:" + digest


def _signal_fixture(root: Path, artifact_run_id: str) -> tuple[str, str]:
    signal_set_id = "signal-fixture"
    revisions = pl.DataFrame(
        [
            {
                "signal_fact_id": "SF1",
                "code": "000001",
                "expected_model_id": 2,
                "signal_date": "2023-01-01",
                "reveal_date": "2023-01-02",
                "current_raw_signal": 21312,
            }
        ]
    )
    meta = _file_meta(
        root,
        "code_buckets/code_bucket=001/signal_revisions/reveal_year=2023/part-00000.parquet",
        "signal_revisions",
        revisions,
    )
    digest = _manifest(
        root,
        {
            "state": "COMPLETE",
            "run_id": artifact_run_id,
            "signal_set_id": signal_set_id,
            "artifacts": [meta],
        },
    )
    return signal_set_id, digest


def _event_fixture(
    root: Path,
    artifact_run_id: str,
    *,
    signal_set_id: str,
    signal_manifest_sha256: str,
) -> None:
    outcomes = pl.DataFrame(
        [
            {
                "signal_fact_id": "SF1",
                "signal_date": "2023-01-01",
                "code": "000001",
                "expected_model_id": 2,
                "reveal_date": "2023-01-02",
                "direction": 1,
                "occurrence": 1,
                "primary_entrypoint": 3,
                "primary_trigger_semantic": "ENGULFING",
                "direction_base_trigger_mask": 4,
                "synthetic_primary_mask": 0,
                "concurrent_trigger_mask": 70,
            }
        ]
    )
    meta = _file_meta(
        root,
        "code_buckets/code_bucket=001/event_outcomes/reveal_year=2023/part-00000.parquet",
        "event_outcomes",
        outcomes,
    )
    _manifest(
        root,
        {
            "state": "COMPLETE",
            "run_id": artifact_run_id,
            "event_set_id": "event-fixture",
            "signals": {
                "signal_set_id": signal_set_id,
                "manifest_sha256": signal_manifest_sha256,
            },
            "summary": {"total_events": 123, "fixture": True},
            "artifacts": [meta],
        },
    )


def _ranking_fixture(root: Path, artifact_run_id: str, combo_id: str) -> None:
    canonical = json.dumps(
        {
            "dsl_version": "1",
            "action": "BUY_CANDIDATE",
            "anchor": "REVEAL_DATE",
            "target_direction": 1,
            "where": {
                "op": "and",
                "args": [
                    {
                        "op": "signal",
                        "model": {"in": [2, 7]},
                        "occurrence": {"in": [1, 2]},
                        "primary_trigger_semantic": {"in": ["ENGULFING"]},
                    },
                    {
                        "op": "trigger_mask",
                        "source": "concurrent",
                        "mode": "any",
                        "ids": [2, 7],
                        "event_filter": {
                            "model": {"in": [2, 7]},
                            "occurrence": {"in": [1, 2]},
                            "primary_trigger_semantic": {"in": ["ENGULFING"]},
                        },
                    },
                ],
            },
        },
        sort_keys=True,
    )
    definitions = pl.DataFrame(
        [
            {
                "run_id": artifact_run_id,
                "ranking_set_id": "ranking-fixture",
                "combo_id": combo_id,
                "discovery_stage": "SINGLE",
                "candidate_family": "fixture",
                "complexity": 1,
                "model_roots_json": '["S0002", "S0007"]',
                "canonical_dsl": canonical,
                "freeze_id": "ranking-freeze",
            }
        ]
    )
    metrics = pl.DataFrame(
        [
            {
                "combo_id": combo_id,
                "split_id": split,
                "horizon": 5,
                "n_executable": 10,
                "mean_return": 0.02,
                "win_rate": 0.6,
                "discovery_score": 0.3 if split == "TRAIN" else 0.4,
            }
            for split in ("TRAIN", "VALIDATION")
        ]
    )
    rankings = pl.DataFrame(
        [
            {
                "run_id": artifact_run_id,
                "ranking_set_id": "ranking-fixture",
                "combo_id": combo_id,
                "frozen_rank": 1,
                "horizon": 5,
                "validation_score": 0.4,
            }
        ]
    )
    artifacts = [
        _file_meta(
            root, "combinations/definitions.parquet", "combo_definitions", definitions
        ),
        _file_meta(root, "rankings/combo_metrics.parquet", "combo_metrics", metrics),
        _file_meta(root, "rankings/combo_rankings.parquet", "combo_rankings", rankings),
    ]
    config = {"horizon": 5, "fixture": True}
    split_plan = {
        "windows": [
            {
                "split_id": "TRAIN",
                "start_date": "2020-01-01",
                "end_date": "2021-01-01",
            },
            {
                "split_id": "VALIDATION",
                "start_date": "2021-01-02",
                "end_date": "2022-01-01",
            },
            {
                "split_id": "HOLDOUT",
                "start_date": "2022-01-02",
                "end_date": "2023-01-01",
            },
        ],
        "purge_sessions": 20,
        "embargo_sessions": 20,
    }
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config/ranking_config.json").write_text(
        json.dumps({"config": config, "split_plan": split_plan}, sort_keys=True),
        encoding="utf-8",
    )
    (root / "config/freeze_record.json").write_text(
        json.dumps({"frozen_order": [combo_id]}, sort_keys=True),
        encoding="utf-8",
    )
    _manifest(
        root,
        {
            "state": "COMPLETE",
            "run_id": artifact_run_id,
            "ranking_set_id": "ranking-fixture",
            "freeze_id": "ranking-freeze",
            "search_audit": {"holdout_rows_read": 0, "fixture": True},
            "artifacts": artifacts,
        },
    )


def _portfolio_fixture(
    root: Path,
    artifact_run_id: str,
    combo_id: str,
    split: str,
    *,
    signal_fact_ids: list[str] | None = None,
) -> None:
    relative = f"splits/split_id={split}/combo=fixture"
    checkpoint = {
        "combo_id": combo_id,
        "source_frozen_rank": 1,
        "portfolio_id": f"portfolio-{split.lower()}",
    }
    checkpoint_root = root / relative
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    (checkpoint_root / "checkpoint.json").write_text(
        json.dumps(checkpoint, sort_keys=True), encoding="utf-8"
    )
    (checkpoint_root / "summary.json").write_text(
        json.dumps(
            {
                "portfolio_id": checkpoint["portfolio_id"],
                "total_return": 0.12,
                "sharpe": 1.1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (checkpoint_root / "quality.json").write_text(
        json.dumps({"quality_mask_counts": {}, "institutional_approximations": []}),
        encoding="utf-8",
    )
    equity = pl.DataFrame(
        [
            {
                "portfolio_id": checkpoint["portfolio_id"],
                "trade_date": "2023-01-03",
                "equity": "10000000",
                "drawdown": "0",
            }
        ]
    )
    trades = pl.DataFrame(
        [
            {
                "portfolio_id": checkpoint["portfolio_id"],
                "fill_id": "fill-1",
                "trade_date": "2023-01-03",
                "code": "000001",
                "side": "BUY",
            }
        ]
    )
    decisions = pl.DataFrame(
        [
            {
                "portfolio_id": checkpoint["portfolio_id"],
                "decision_id": "decision-1",
                "reveal_date": "2023-01-02",
                "code": "000001",
                "direction": 1,
                "source_signal_fact_ids": json.dumps(signal_fact_ids or ["SF1"]),
            }
        ]
    )
    artifacts = [
        _file_meta(root, f"{relative}/equity.parquet", "equity", equity),
        _file_meta(root, f"{relative}/trades.parquet", "trades", trades),
        _file_meta(root, f"{relative}/decisions.parquet", "decisions", decisions),
    ]
    _manifest(
        root,
        {
            "state": "COMPLETE",
            "run_id": artifact_run_id,
            "portfolio_set_id": f"portfolio-set-{split.lower()}",
            "split_id": split,
            "frozen_order": [combo_id],
            "checkpoint_paths": [relative],
            "artifacts": artifacts,
        },
    )


def _holdout_fixture(root: Path, combo_id: str) -> None:
    metrics = pl.DataFrame(
        [
            {
                "combo_id": combo_id,
                "split_id": "HOLDOUT",
                "horizon": 5,
                "n_executable": 8,
                "mean_return": 0.01,
                "win_rate": 0.55,
                "discovery_score": 0.2,
            }
        ]
    )
    metric_meta = _file_meta(
        root, "holdout/metrics.parquet", "holdout_metrics", metrics
    )
    audit_meta = _json_meta(
        root,
        "audit/event_access.json",
        "event_access_audit",
        [
            {
                "sequence": 1,
                "split_id": "HOLDOUT",
                "purpose": "FIXTURE_REVEAL",
                "decision": "ALLOW",
                "reason": "FROZEN_RULES_ONE_TIME_REVEAL",
            }
        ],
    )
    _manifest(
        root,
        {
            "state": "COMPLETE",
            "freeze_id": "ranking-freeze",
            "reveal_id": "reveal-fixture",
            "frozen_order": [combo_id],
            "frozen_ranks": [1],
            "artifacts": [metric_meta, audit_meta],
        },
    )


@pytest.fixture(scope="module")
def mongo_database():
    uri = os.getenv("CLX_INTEGRATION_MONGO_URI")
    if not uri:
        pytest.skip("CLX_INTEGRATION_MONGO_URI is not configured")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    assert client.admin.command("ping")["ok"] == 1
    database = client[DERIVED_DATABASE_NAME]
    MongoClxBacktestStore(database)
    prefix = "IT" + uuid.uuid4().hex
    yield database, prefix
    for collection in INDEX_DEFINITIONS:
        database[collection].delete_many(
            {
                "$or": [
                    {"_id": {"$regex": prefix}},
                    {"run_id": {"$regex": f"^{prefix}"}},
                    {"job_id": {"$regex": f"^{prefix}"}},
                ]
            }
        )
    client.close()


def test_mongo_claim_lease_progress_cancel_and_resume(mongo_database):
    database, prefix = mongo_database
    run_id = prefix + "-RUN-CLAIM"
    job_id = prefix + "-JOB-CLAIM"
    job = {
        "_id": job_id,
        "job_id": job_id,
        "run_id": run_id,
        "kind": "BACKTEST",
        "status": "QUEUED",
        "progress": 0.0,
        "created_at": "2026-07-22T01:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    database.runs.insert_one(
        {
            "_id": run_id,
            "run_id": run_id,
            "status": "QUEUED",
            "active_job_id": job_id,
            "active_job": job,
        }
    )
    database.jobs.insert_one(job)
    store = MongoWorkerStore(database, lease_seconds=10)
    with ThreadPoolExecutor(max_workers=6) as executor:
        claimed = list(executor.map(lambda i: store.claim(f"worker-{i}"), range(6)))
    winners = [item for item in claimed if item is not None]
    assert len(winners) == 1
    winner = winners[0]
    assert database.runs.find_one({"_id": run_id})["status"] == "RUNNING"
    store.update_progress(
        winner,
        "fixture-stage",
        event_type="STAGE_COMPLETE",
        progress=0.5,
        stage="fixture",
    )
    store.update_progress(
        winner,
        "fixture-stage",
        event_type="STAGE_COMPLETE",
        progress=0.5,
        stage="fixture",
    )
    assert (
        database.progress_events.count_documents(
            {"job_id": job_id, "event_key": "fixture-stage"}
        )
        == 1
    )
    store.checkpoint(winner, "fixture", {"artifact": "fresh"})
    store.persist_resolved_lineage(winner, {"root": "fixture-root"})
    store.complete(winner, result={"fixture": True})
    completed_run = database.runs.find_one({"_id": run_id})
    assert completed_run["status"] == "COMPLETE"
    assert completed_run["active_job"]["stage"] == "fixture"
    assert completed_run["active_job"]["checkpoints"]["fixture"]["artifact"] == "fresh"
    assert completed_run["active_job"]["resolved_lineage"] == {"root": "fixture-root"}

    resume_run = prefix + "-RUN-RESUME"
    resume_job = prefix + "-JOB-RESUME"
    stale = {
        "_id": resume_job,
        "job_id": resume_job,
        "run_id": resume_run,
        "kind": "BACKTEST",
        "status": "RUNNING",
        "progress": 0.25,
        "worker_id": "dead-worker",
        "lease_token": "dead-token",
        "lease_expires_at": "2020-01-01T00:00:00.000Z",
        "attempt_count": 1,
        "created_at": "2026-07-22T01:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    database.jobs.insert_one(stale)
    database.runs.insert_one(
        {
            "_id": resume_run,
            "run_id": resume_run,
            "status": "RUNNING",
            "active_job_id": resume_job,
            "active_job": stale,
        }
    )
    resumed = store.claim("recovery-worker")
    assert resumed["_id"] == resume_job
    assert resumed["attempt_count"] == 2
    assert resumed["lease_token"] != "dead-token"
    store.update_progress(
        resumed,
        "resume-stage",
        event_type="STAGE_COMPLETE",
        progress=0.75,
        stage="resume",
    )
    store.checkpoint(resumed, "resume", {"artifact": "latest"})
    store.fail(resumed, {"code": "FIXTURE", "message": "cleanup"})
    failed_run = database.runs.find_one({"_id": resume_run})
    assert failed_run["active_job"]["progress"] == 0.75
    assert failed_run["active_job"]["stage"] == "resume"
    assert failed_run["active_job"]["checkpoints"]["resume"]["artifact"] == "latest"
    assert (
        database.progress_events.find_one(
            {"job_id": resume_job, "event_key": "JOB_FAILED"}
        )["progress"]
        == 0.75
    )


def test_claim_cancellation_race_finishes_cancelled(mongo_database, monkeypatch):
    database, prefix = mongo_database
    run_id = prefix + "-RUN-CLAIM-CANCEL"
    job_id = prefix + "-JOB-CLAIM-CANCEL"
    job = {
        "_id": job_id,
        "job_id": job_id,
        "run_id": run_id,
        "kind": "BACKTEST",
        "status": "QUEUED",
        "progress": 0.0,
        "created_at": "2026-07-22T01:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    database.runs.insert_one(
        {
            "_id": run_id,
            "run_id": run_id,
            "status": "QUEUED",
            "active_job_id": job_id,
            "active_job": job,
        }
    )
    database.jobs.insert_one(job)
    store = MongoWorkerStore(database, lease_seconds=10)
    original_bind = store._bind_control_plane

    def cancel_before_bind(claimed, now):
        database.runs.update_one(
            {"_id": run_id}, {"$set": {"status": "CANCEL_REQUESTED"}}
        )
        database.jobs.update_one(
            {"_id": job_id}, {"$set": {"status": "CANCEL_REQUESTED"}}
        )
        return original_bind(claimed, now)

    monkeypatch.setattr(store, "_bind_control_plane", cancel_before_bind)
    assert store.claim("cancellation-race-worker", kinds=("BACKTEST",)) is None
    assert database.jobs.find_one({"_id": job_id})["status"] == "CANCELLED"
    assert database.runs.find_one({"_id": run_id})["status"] == "CANCELLED"
    assert (
        database.progress_events.count_documents(
            {"job_id": job_id, "event_key": "JOB_FAILED"}
        )
        == 0
    )
    assert (
        database.progress_events.count_documents(
            {"job_id": job_id, "event_key": "JOB_CANCELLED"}
        )
        == 1
    )


def test_mongo_projection_holdout_export_and_download(mongo_database, tmp_path):
    database, prefix = mongo_database
    run_id = prefix + "-RUN-PROJECT"
    artifact_run_id = prefix + "-SOURCE"
    combo_id = "sha256:" + "c" * 64
    signal_dir = tmp_path / "signal"
    event_dir = tmp_path / "event"
    ranking_dir = tmp_path / "ranking"
    validation_portfolio = tmp_path / "portfolio-validation"
    holdout_dir = tmp_path / "holdout-ranking"
    holdout_portfolio = tmp_path / "portfolio-holdout"
    signal_set_id, signal_manifest_sha256 = _signal_fixture(signal_dir, artifact_run_id)
    _event_fixture(
        event_dir,
        artifact_run_id,
        signal_set_id=signal_set_id,
        signal_manifest_sha256=signal_manifest_sha256,
    )
    _ranking_fixture(ranking_dir, artifact_run_id, combo_id)
    _portfolio_fixture(validation_portfolio, artifact_run_id, combo_id, "VALIDATION")
    database.runs.insert_one(
        {
            "_id": run_id,
            "run_id": run_id,
            "status": "RUNNING",
            "config_sha256": content_hash({"fixture": True}),
            "config": {
                "train": {"start": "2020-01-01", "end": "2021-01-01"},
                "validation": {"start": "2021-01-02", "end": "2022-01-01"},
                "holdout": {"start": "2022-01-02", "end": "2023-01-01"},
            },
        }
    )
    run = database.runs.find_one({"_id": run_id})
    accept = lambda _: {"status": "verified"}
    projector = ClxArtifactProjector(
        database,
        verify_event=accept,
        verify_ranking=accept,
        verify_holdout=accept,
        verify_portfolio=accept,
    )
    first = projector.project_backtest(
        run,
        signal_dir=signal_dir,
        event_dir=event_dir,
        ranking_dir=ranking_dir,
        portfolio_dirs={"VALIDATION": validation_portfolio},
    )
    second = projector.project_backtest(
        run,
        signal_dir=signal_dir,
        event_dir=event_dir,
        ranking_dir=ranking_dir,
        portfolio_dirs={"VALIDATION": validation_portfolio},
    )
    assert first["manifest_sha256"] == second["manifest_sha256"]
    projected_manifest = database.manifests.find_one({"run_id": run_id})
    expected_split_plan = json.loads(
        (ranking_dir / "config/ranking_config.json").read_text(encoding="utf-8")
    )["split_plan"]
    assert projected_manifest["config"]["split_config_sha256"] == content_hash(
        expected_split_plan
    )
    assert projected_manifest["config"]["ranking_config"] == {
        "horizon": 5,
        "fixture": True,
    }
    assert projected_manifest["config"]["ranking_config_sha256"] == content_hash(
        {"horizon": 5, "fixture": True}
    )
    assert projected_manifest["freeze_input"] == {
        "validation": {
            "selected_combo_ids": [combo_id],
            "rank_order": [combo_id],
        },
        "ranking_config": {"horizon": 5, "fixture": True},
        "split_config_sha256": content_hash(expected_split_plan),
        "frozen_rank_digest": content_hash(
            {
                "run_id": run_id,
                "split_id": "VALIDATION",
                "rank_order": [combo_id],
                "ranking_config_sha256": content_hash({"horizon": 5, "fixture": True}),
            }
        ),
    }
    assert projected_manifest["quality"]["event_summary"]["total_events"] == 123
    assert (
        projected_manifest["quality"]["ranking_search_audit"]["holdout_rows_read"] == 0
    )
    definition = database.combo_definitions.find_one(
        {"run_id": run_id, "combo_id": combo_id}
    )
    assert definition["model_ids"] == [2, 7]
    assert definition["occurrences"] == [1, 2]
    assert definition["primary_triggers"] == [
        "ENGULFING",
        "MACD_CROSS",
        "PIN_BAR",
    ]
    assert (
        database.combo_metrics.find_one({"run_id": run_id, "split_id": "VALIDATION"})[
            "frozen_rank"
        ]
        == 1
    )
    assert database.portfolio_equity.count_documents({"run_id": run_id}) == 1
    assert database.portfolio_trades.count_documents({"run_id": run_id}) == 1
    signal = database.combo_signals.find_one({"run_id": run_id})
    assert signal["signal_fact_id"] == "SF1"
    assert signal["signal_date"] == "2023-01-01"
    assert signal["model_id"] == 2
    assert signal["occurrence"] == 1
    assert signal["primary_trigger"] == "ENGULFING"
    assert signal["concurrent_triggers"] == ["PIN_BAR", "ENGULFING", "MACD_CROSS"]
    assert signal["raw_signal"] == 21312
    assert signal["decision_id"] == "decision-1"
    assert signal["code"] == "000001"
    assert signal["reveal_date"] == "2023-01-02"
    assert signal["direction"] == 1

    missing_portfolio = tmp_path / "portfolio-missing-source"
    _portfolio_fixture(
        missing_portfolio,
        artifact_run_id,
        combo_id,
        "VALIDATION",
        signal_fact_ids=["MISSING"],
    )
    with pytest.raises(ProjectionError, match="source signal facts are missing"):
        projector.project_backtest(
            {
                "_id": prefix + "-RUN-MISSING-SOURCE",
                "config_sha256": content_hash({"fixture": "missing"}),
            },
            signal_dir=signal_dir,
            event_dir=event_dir,
            ranking_dir=ranking_dir,
            portfolio_dirs={"VALIDATION": missing_portfolio},
        )

    database.runs.update_one({"_id": run_id}, {"$set": {"status": "COMPLETE"}})
    api = Flask(__name__)
    api.register_blueprint(
        create_clx_backtest_blueprint(
            MongoClxBacktestStore(database, create_indexes=False)
        )
    )
    api_client = api.test_client()
    filtered = api_client.get(
        f"/api/clx-backtest/runs/{run_id}/rankings"
        "?model_id=7&primary_trigger=MACD_CROSS&occurrence=2"
    )
    assert filtered.status_code == 200
    assert [item["combo_id"] for item in filtered.get_json()["data"]["items"]] == [
        combo_id
    ]
    published_freeze_input = api_client.get(
        f"/api/clx-backtest/runs/{run_id}/manifest"
    ).get_json()["data"]["freeze_input"]
    frozen = api_client.post(
        f"/api/clx-backtest/runs/{run_id}/freeze", json=published_freeze_input
    )
    assert frozen.status_code == 201
    api_freeze_id = frozen.get_json()["data"]["freeze_id"]

    _holdout_fixture(holdout_dir, combo_id)
    _portfolio_fixture(holdout_portfolio, artifact_run_id, combo_id, "HOLDOUT")
    first_holdout = projector.project_holdout(
        run,
        signal_dir=signal_dir,
        event_dir=event_dir,
        ranking_dir=ranking_dir,
        holdout_dir=holdout_dir,
        portfolio_dir=holdout_portfolio,
        api_freeze_id=api_freeze_id,
    )
    second_holdout = projector.project_holdout(
        run,
        signal_dir=signal_dir,
        event_dir=event_dir,
        ranking_dir=ranking_dir,
        holdout_dir=holdout_dir,
        portfolio_dir=holdout_portfolio,
        api_freeze_id=api_freeze_id,
    )
    assert (
        first_holdout["holdout"]["projected_at"]
        == second_holdout["holdout"]["projected_at"]
    )
    validation = database.combo_metrics.find_one(
        {"run_id": run_id, "split_id": "VALIDATION"}
    )
    holdout = database.combo_metrics.find_one({"run_id": run_id, "split_id": "HOLDOUT"})
    assert validation["frozen_rank"] == holdout["frozen_rank"] == 1
    assert (
        database.manifests.find_one({"run_id": run_id})["quality"][
            "holdout_materialized"
        ]
        is True
    )
    access_finding = database.audit_findings.find_one(
        {"run_id": run_id, "kind": "EVENT_ACCESS_AUDIT"}
    )
    assert access_finding["details"]["decision"] == "ALLOW"

    export_root = tmp_path / "exports-root"
    for file_format in ("csv", "json", "parquet"):
        job_id = f"{prefix}-EXPORT-{file_format}"
        job = {
            "_id": job_id,
            "job_id": job_id,
            "run_id": run_id,
            "kind": "EXPORT",
            "status": "QUEUED",
            "resource": "metrics",
            "format": file_format,
            "combo_ids": [combo_id],
            "split_id": "VALIDATION",
            "artifact_key": f"exports/{run_id}/{job_id}.{file_format}",
            "created_at": "2026-07-22T01:00:00.000Z",
            "updated_at": "2026-07-22T01:00:00.000Z",
        }
        database.jobs.insert_one(job)
        worker_store = MongoWorkerStore(database, lease_seconds=10)
        claimed = worker_store.claim("export-worker", kinds=("EXPORT",))
        result = ExportRunner(database, root=export_root).run(claimed)
        worker_store.complete(claimed, result=result)
        completed = database.jobs.find_one({"_id": job_id})
        assert completed["status"] == "COMPLETE"
        assert completed["artifact_sha256"].startswith("sha256:")
        assert completed["artifact_size_bytes"] > 0
        assert (export_root / completed["artifact_key"]).is_file()

    completed = database.jobs.find_one({"_id": f"{prefix}-EXPORT-json"})
    store = MemoryClxBacktestStore()
    store.seed("jobs", [completed])
    app = Flask(__name__)
    app.register_blueprint(
        create_clx_backtest_blueprint(store, export_artifact_root=export_root)
    )
    response = app.test_client().get(
        f"/api/clx-backtest/exports/{completed['_id']}/download"
    )
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert combo_id.encode() in response.data


def test_mongo_reveal_projects_exactly_one_holdout_job(mongo_database):
    database, prefix = mongo_database
    run_id = prefix + "-RUN-REVEAL"
    freeze_id = prefix + "-FREEZE"
    database.runs.insert_one({"_id": run_id, "run_id": run_id, "status": "COMPLETE"})
    database.freeze_records.insert_one(
        {
            "_id": prefix + "-FREEZE-DOC",
            "run_id": run_id,
            "freeze_id": freeze_id,
            "state": "FROZEN",
            "reveal_count": 0,
            "holdout_revealed_at": None,
        }
    )
    store = MongoClxBacktestStore(database, create_indexes=False)

    def reveal(index: int):
        return store.reveal_holdout(
            run_id,
            freeze_id,
            now="2026-07-22T05:00:00.000Z",
            job_id=f"{prefix}-HOLDOUT-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reveal, range(8)))
    assert [item["reason"] for item in results].count("OK") == 1
    assert database.jobs.count_documents({"run_id": run_id, "kind": "HOLDOUT"}) == 1
    record = database.freeze_records.find_one({"run_id": run_id})
    assert record["reveal_count"] == 1
    assert record["projection_pending"] is False


def test_real_fixture_backtest_cli_resume_and_subprocess_cancel(
    mongo_database, tmp_path, monkeypatch
):
    from freshquant.backtest.clx.event_study import (
        build_event_study,
        verify_event_study,
    )
    from freshquant.backtest.clx.ranking import verify_ranking_artifact
    from freshquant.tests.clx_backtest import test_event_study as event_fixture

    database, prefix = mongo_database
    days = [
        date(year, 1, 1) + timedelta(days=index)
        for year in (2022, 2023, 2024)
        for index in range(50)
    ]
    separated_calendar = pl.DataFrame(
        {"trade_date": days, "session_no": list(range(1, 151))},
        schema={"trade_date": pl.Date, "session_no": pl.UInt32},
    )
    monkeypatch.setattr(
        event_fixture, "_calendar", lambda count=150: separated_calendar
    )
    snapshot, signals, plan = event_fixture._write_inputs(tmp_path)
    event_dir = tmp_path / "events"
    build_event_study(
        snapshot,
        signals,
        event_dir,
        plan,
        bootstrap_replicates=20,
    )
    verify_event_study(event_dir)
    split_plan = tmp_path / "split-plan.json"
    split_plan.write_text(json.dumps(plan.to_dict(), sort_keys=True), encoding="utf-8")
    ranking_config = tmp_path / "ranking-config.json"
    ranking_config.write_text(
        json.dumps(
            {
                "min_train_sample": 1,
                "min_validation_sample": 1,
                "min_train_density": 0.0,
                "min_validation_density": 0.0,
                "min_train_years": 1,
                "min_validation_years": 1,
                "min_events_per_year": 1,
                "max_train_fdr": 1.0,
                "max_validation_fdr": 1.0,
                "beam_width_per_stage": 8,
                "max_candidates_per_stage": 32,
                "max_total_candidates": 64,
                "max_seed_per_root": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    run_id = prefix + "-RUN-PIPELINE"
    job_id = prefix + "-JOB-PIPELINE"
    config = {
        "snapshot_id": "sha256:fixture-snapshot",
        "snapshot_dir": str(snapshot),
        "signal_dir": str(signals),
        "event_dir": str(event_dir),
        "calendar_path": str(snapshot / "calendar/part-00000.parquet"),
        "split_plan_path": str(split_plan),
        "ranking_config_path": str(ranking_config),
        "portfolio_splits": [],
        "train": {
            "start": plan.windows[0].start_date.isoformat(),
            "end": plan.windows[0].end_date.isoformat(),
        },
        "validation": {
            "start": plan.windows[1].start_date.isoformat(),
            "end": plan.windows[1].end_date.isoformat(),
        },
        "holdout": {
            "start": plan.windows[2].start_date.isoformat(),
            "end": plan.windows[2].end_date.isoformat(),
        },
    }
    job = {
        "_id": job_id,
        "job_id": job_id,
        "run_id": run_id,
        "kind": "BACKTEST",
        "status": "QUEUED",
        "progress": 0.0,
        "created_at": "2026-07-22T01:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    database.jobs.insert_one(job)
    database.runs.insert_one(
        {
            "_id": run_id,
            "run_id": run_id,
            "status": "QUEUED",
            "active_job_id": job_id,
            "active_job": job,
            "config": config,
            "config_sha256": content_hash(config),
            "lineage": {},
        }
    )
    store = MongoWorkerStore(database, lease_seconds=10)
    claimed = store.claim("pipeline-worker-1", kinds=("BACKTEST",))
    run = database.runs.find_one({"_id": run_id})
    layout = resolve_pipeline_layout(run, tmp_path)
    lineage = {
        "root": layout.root,
        "run_root": layout.run_root,
        "snapshot_dir": layout.snapshot_dir,
        "signal_dir": layout.signal_dir,
        "event_dir": layout.event_dir,
        "ranking_dir": layout.ranking_dir,
        "calendar_path": layout.calendar_path,
        "split_plan_path": layout.split_plan_path,
        "ranking_config_path": layout.ranking_config_path,
        "portfolio_config_path": layout.portfolio_config_path,
        "portfolio_dirs": layout.portfolio_dirs,
    }
    store.persist_resolved_lineage(claimed, lineage)
    claimed = {**claimed, "resolved_lineage": lineage}
    executor = SubprocessStageExecutor(
        store, claimed, "pipeline-worker-1", root=tmp_path, poll_seconds=0.05
    )
    first_lineage = BacktestPipelineRunner(executor, root=tmp_path).run(run, claimed)
    first = verify_ranking_artifact(first_lineage["ranking_dir"])
    first_sha = first["manifest_sha256"]

    # Simulate a hard worker loss after immutable publication and before Mongo
    # completion.  The expired job is reclaimed and every stage verifies/resumes.
    database.jobs.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": "RUNNING",
                "lease_expires_at": "2020-01-01T00:00:00.000Z",
                "worker_id": "dead-worker",
                "lease_token": "dead-token",
            }
        },
    )
    resumed = store.claim("pipeline-worker-2", kinds=("BACKTEST",))
    assert resumed["attempt_count"] == 2
    second_executor = SubprocessStageExecutor(
        store, resumed, "pipeline-worker-2", root=tmp_path, poll_seconds=0.05
    )
    second_lineage = BacktestPipelineRunner(second_executor, root=tmp_path).run(
        database.runs.find_one({"_id": run_id}), resumed
    )
    assert (
        verify_ranking_artifact(second_lineage["ranking_dir"])["manifest_sha256"]
        == first_sha
    )
    projection = ClxArtifactProjector(database).project_backtest(
        database.runs.find_one({"_id": run_id}),
        signal_dir=second_lineage["signal_dir"],
        event_dir=second_lineage["event_dir"],
        ranking_dir=second_lineage["ranking_dir"],
        portfolio_dirs={},
    )
    store.complete(resumed, result={"projection": projection})
    assert database.runs.find_one({"_id": run_id})["status"] == "COMPLETE"

    cancel_run_id = prefix + "-RUN-CANCEL"
    cancel_job_id = prefix + "-JOB-CANCEL"
    cancel_job = {
        "_id": cancel_job_id,
        "job_id": cancel_job_id,
        "run_id": cancel_run_id,
        "kind": "BACKTEST",
        "status": "QUEUED",
        "progress": 0.0,
        "created_at": "2026-07-22T01:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    database.jobs.insert_one(cancel_job)
    database.runs.insert_one(
        {
            "_id": cancel_run_id,
            "run_id": cancel_run_id,
            "status": "QUEUED",
            "active_job_id": cancel_job_id,
            "active_job": cancel_job,
        }
    )
    active = store.claim("cancel-worker", kinds=("BACKTEST",))
    executor = SubprocessStageExecutor(
        store, active, "cancel-worker", root=tmp_path, poll_seconds=0.05
    )
    outcome: list[BaseException] = []

    def execute_sleep():
        try:
            executor(
                "cancel_fixture",
                [os.sys.executable, "-c", "import time; time.sleep(30)"],
                0.5,
            )
        except BaseException as exc:
            outcome.append(exc)

    thread = threading.Thread(target=execute_sleep)
    thread.start()
    deadline = time.monotonic() + 5
    while (
        database.progress_events.find_one(
            {"job_id": cancel_job_id, "event_key": "cancel_fixture:START"}
        )
        is None
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    MongoClxBacktestStore(database, create_indexes=False).cancel_run(
        cancel_run_id,
        now="2026-07-22T06:00:00.000Z",
        reason="fixture cancellation",
    )
    thread.join(timeout=8)
    assert not thread.is_alive()
    assert len(outcome) == 1 and isinstance(outcome[0], JobCancelled)
    store.cancel(active)
    assert database.runs.find_one({"_id": cancel_run_id})["status"] == "CANCELLED"
