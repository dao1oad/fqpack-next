from __future__ import annotations

import csv
import itertools
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .artifacts import (
    ArtifactContractError,
    artifact_root,
    atomic_write_json,
    content_hash,
    discover_signal_artifact,
    read_hashed_manifest,
    resolve_run_reference,
    run_value,
    safe_artifact_path,
    sha256_file,
)
from .utils import utc_now
from .worker_store import MongoWorkerStore


class JobCancelled(RuntimeError):
    """Raised after a cancellation request has stopped the active subprocess."""


class StageExecutionError(RuntimeError):
    """Raised when an immutable pipeline command exits unsuccessfully."""


@dataclass(frozen=True, slots=True)
class PipelineLayout:
    root: str
    run_root: str
    snapshot_dir: str
    signal_dir: str
    event_dir: str
    ranking_dir: str
    calendar_path: str
    split_plan_path: str
    ranking_config_path: str
    portfolio_config_path: str
    portfolio_dirs: dict[str, str]


def _config(run: Mapping[str, object]) -> Mapping[str, object]:
    value = run.get("config")
    return value if isinstance(value, Mapping) else {}


def _control_document(path: Path, value: object) -> None:
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if content_hash(current) != content_hash(value):
            raise ArtifactContractError(f"immutable generated config differs: {path}")
        return
    atomic_write_json(path, value)


def _split_plan(config: Mapping[str, object]) -> dict[str, object]:
    windows: list[dict[str, object]] = []
    for name in ("train", "validation", "holdout"):
        window = config.get(name)
        if not isinstance(window, Mapping):
            raise ArtifactContractError(f"run config has no {name} split window")
        start = window.get("start") or window.get("start_date")
        end = window.get("end") or window.get("end_date")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ArtifactContractError(f"run config {name} split is incomplete")
        windows.append({"split_id": name.upper(), "start_date": start, "end_date": end})
    return {
        "windows": windows,
        "purge_sessions": int(config.get("purge_sessions", 20)),
        "embargo_sessions": int(config.get("embargo_sessions", 20)),
    }


def _portfolio_config(config: Mapping[str, object]) -> dict[str, object]:
    supplied = config.get("portfolio_config")
    if isinstance(supplied, Mapping):
        return dict(supplied)
    max_holdings = int(config.get("max_positions", config.get("max_holdings", 10)))
    return {
        "initial_cash_cny": str(config.get("initial_cash", 10_000_000)),
        "target_weight": str(config.get("target_weight", "0.10")),
        "max_holdings": max_holdings,
        "lot_size_default": 100,
        "decision_clock": "T_CLOSE",
        "first_attempt": "NEXT_MARKET_SESSION_RAW_OPEN",
        "buy_rule": "FROZEN_POSITIVE_DIRECTION_COMBO",
        "exit_rule": "DIRECTION_INVERTED_SAME_CANONICAL_DSL",
        "negative_signal_priority": "EXIT_AND_SAME_DAY_BUY_VETO",
        "selection": {
            "split": "VALIDATION",
            "direction": 1,
            "frozen_rank_top_n": int(config.get("frozen_rank_top_n", 20)),
        },
        "price_domain": "RAW",
        "fee_schedule": "DEFAULT_FEE_SCHEDULE",
        "limit_schedule": "DEFAULT_LIMIT_SCHEDULE",
        "slippage_model": "DEFAULT_SLIPPAGE_MODEL",
    }


def _calendar_from_snapshot(snapshot_dir: Path) -> Path:
    manifest, _ = read_hashed_manifest(snapshot_dir)
    dataset = manifest.get("dataset")
    calendar_file = (
        dataset.get("calendar_file") if isinstance(dataset, Mapping) else None
    )
    relative = calendar_file.get("path") if isinstance(calendar_file, Mapping) else None
    if not isinstance(relative, str):
        raise ArtifactContractError("snapshot manifest has no calendar path")
    candidate = (snapshot_dir / relative).resolve()
    if candidate != snapshot_dir and snapshot_dir not in candidate.parents:
        raise ArtifactContractError("snapshot calendar leaves snapshot artifact")
    if not candidate.is_file():
        raise ArtifactContractError(f"snapshot calendar does not exist: {candidate}")
    return candidate


def resolve_pipeline_layout(
    run: Mapping[str, object], root: str | Path | None = None
) -> PipelineLayout:
    frozen = run.get("resolved_lineage")
    if isinstance(frozen, Mapping):
        return PipelineLayout(**dict(frozen))
    base = artifact_root(root)
    run_id = str(run["_id"])
    config = _config(run)
    snapshot_id = run_value(run, "snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ArtifactContractError("run config has no snapshot_id")
    snapshot_dir = resolve_run_reference(
        base,
        run,
        "snapshot_dir",
        "snapshot_path",
        default=f"snapshots/{snapshot_id}",
    )
    explicit_signal = run_value(run, "signal_dir", "signal_path")
    if explicit_signal is None:
        signal_id = run_value(run, "signal_set_id")
        signal_dir = discover_signal_artifact(
            base, snapshot_id, str(signal_id) if signal_id else None
        )
    else:
        signal_dir = safe_artifact_path(base, str(explicit_signal))
        if not signal_dir.exists():
            raise ArtifactContractError(f"signal artifact does not exist: {signal_dir}")
    run_root = safe_artifact_path(base, f"runs/{run_id}")
    explicit_event = run_value(run, "event_dir", "event_path")
    event_dir = (
        safe_artifact_path(base, str(explicit_event))
        if explicit_event
        else run_root / "event"
    )
    explicit_ranking = run_value(run, "ranking_dir", "ranking_path")
    ranking_dir = (
        safe_artifact_path(base, str(explicit_ranking))
        if explicit_ranking
        else run_root / "ranking"
    )
    calendar_value = run_value(run, "calendar_path", "calendar_file")
    calendar_path = (
        safe_artifact_path(base, str(calendar_value))
        if calendar_value
        else _calendar_from_snapshot(snapshot_dir)
    )
    control = run_root / "control" / "config"
    split_value = run_value(run, "split_plan_path")
    if split_value:
        split_path = safe_artifact_path(base, str(split_value))
    else:
        split_path = control / "split-plan.json"
        _control_document(split_path, _split_plan(config))
    ranking_value = run_value(run, "ranking_config_path")
    if ranking_value:
        ranking_path = safe_artifact_path(base, str(ranking_value))
    else:
        supplied = config.get("ranking_config")
        if isinstance(supplied, Mapping):
            ranking_document = dict(supplied)
        else:
            shared = base / "config" / "ranking-config-v1.json"
            if not shared.is_file():
                raise ArtifactContractError(
                    "run needs ranking_config or ranking_config_path"
                )
            ranking_document = json.loads(shared.read_text(encoding="utf-8"))
        ranking_path = control / "ranking-config.json"
        _control_document(ranking_path, ranking_document)
    portfolio_value = run_value(run, "portfolio_config_path")
    if portfolio_value:
        portfolio_path = safe_artifact_path(base, str(portfolio_value))
    else:
        portfolio_path = control / "portfolio-config.json"
        _control_document(portfolio_path, _portfolio_config(config))
    requested_splits = config.get("portfolio_splits", ["TRAIN", "VALIDATION"])
    if not isinstance(requested_splits, Sequence) or isinstance(
        requested_splits, (str, bytes)
    ):
        raise ArtifactContractError("portfolio_splits must be a list")
    portfolio_dirs: dict[str, str] = {}
    supplied_dirs = run_value(run, "portfolio_dirs")
    supplied_mapping = supplied_dirs if isinstance(supplied_dirs, Mapping) else {}
    for raw_split in requested_splits:
        split_id = str(raw_split).upper()
        if split_id not in {"TRAIN", "VALIDATION"}:
            raise ArtifactContractError(
                "BACKTEST portfolio_splits only allow TRAIN/VALIDATION"
            )
        supplied = supplied_mapping.get(split_id) or supplied_mapping.get(
            split_id.lower()
        )
        path = (
            safe_artifact_path(base, str(supplied))
            if supplied
            else run_root / "portfolios" / split_id.lower()
        )
        portfolio_dirs[split_id] = str(path)
    for path in (calendar_path, split_path, ranking_path, portfolio_path):
        if not path.is_file():
            raise ArtifactContractError(f"pipeline config does not exist: {path}")
    return PipelineLayout(
        root=str(base),
        run_root=str(run_root),
        snapshot_dir=str(snapshot_dir),
        signal_dir=str(signal_dir),
        event_dir=str(event_dir),
        ranking_dir=str(ranking_dir),
        calendar_path=str(calendar_path),
        split_plan_path=str(split_path),
        ranking_config_path=str(ranking_path),
        portfolio_config_path=str(portfolio_path),
        portfolio_dirs=portfolio_dirs,
    )


StageExecutor = Callable[[str, Sequence[str], float], Mapping[str, object]]


class BacktestPipelineRunner:
    def __init__(
        self, execute: StageExecutor, *, root: str | Path | None = None
    ) -> None:
        self.execute = execute
        self.root = artifact_root(root)

    def run(
        self, run: Mapping[str, object], job: Mapping[str, object]
    ) -> dict[str, object]:
        existing = job.get("resolved_lineage")
        if isinstance(existing, Mapping):
            layout = PipelineLayout(**dict(existing))
        else:
            layout = resolve_pipeline_layout(run, self.root)
        lineage = asdict(layout)
        event_dir = Path(layout.event_dir)
        command = [
            sys.executable,
            "-m",
            "freshquant.backtest.clx.event_study",
            "build",
            "--snapshot-dir",
            layout.snapshot_dir,
            "--signal-dir",
            layout.signal_dir,
            "--output-dir",
            layout.event_dir,
            "--split-plan",
            layout.split_plan_path,
            "--bootstrap-replicates",
            str(int(_config(run).get("bootstrap_replicates", 1000))),
        ]
        if event_dir.exists():
            command.append("--resume")
        self.execute("event_build", command, 0.25)
        ranking_command = [
            sys.executable,
            "-m",
            "freshquant.backtest.clx.ranking",
            "build",
            "--event-dir",
            layout.event_dir,
            "--calendar",
            layout.calendar_path,
            "--split-plan",
            layout.split_plan_path,
            "--ranking-config",
            layout.ranking_config_path,
            "--output-dir",
            layout.ranking_dir,
            "--access-log",
            str(Path(layout.run_root) / "control" / "ranking-access.jsonl"),
        ]
        self.execute("ranking", ranking_command, 0.55)
        splits = sorted(layout.portfolio_dirs)
        for index, split_id in enumerate(splits):
            output = layout.portfolio_dirs[split_id]
            destination = Path(output)
            command = [
                sys.executable,
                "-m",
                "freshquant.backtest.clx.portfolio.pipeline",
                "build",
                "--snapshot-dir",
                layout.snapshot_dir,
                "--event-dir",
                layout.event_dir,
                "--ranking-dir",
                layout.ranking_dir,
                "--output-dir",
                output,
                "--portfolio-config",
                layout.portfolio_config_path,
                "--split-id",
                split_id,
                *(["--resume"] if destination.exists() else []),
            ]
            progress = 0.55 + (index + 1) * (0.35 / max(1, len(splits)))
            self.execute(f"portfolio_{split_id.lower()}", command, progress)
        return lineage


class HoldoutPipelineRunner:
    def __init__(
        self, execute: StageExecutor, *, root: str | Path | None = None
    ) -> None:
        self.execute = execute
        self.root = artifact_root(root)

    def run(
        self,
        run: Mapping[str, object],
        job: Mapping[str, object],
        freeze: Mapping[str, object],
    ) -> dict[str, object]:
        base = resolve_pipeline_layout(run, self.root)
        read_hashed_manifest(base.ranking_dir)
        freeze_path = Path(base.ranking_dir) / "config" / "freeze_record.json"
        if not freeze_path.is_file():
            raise ArtifactContractError(
                "ranking artifact has no immutable freeze record"
            )
        ranking_freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        specification = freeze.get("specification")
        validation = (
            specification.get("validation")
            if isinstance(specification, Mapping)
            else None
        )
        api_order = (
            validation.get("rank_order") if isinstance(validation, Mapping) else None
        )
        artifact_order = ranking_freeze.get("frozen_order")
        if list(api_order or []) != list(artifact_order or []):
            raise ArtifactContractError(
                "API freeze order differs from ranking artifact"
            )
        suffix = content_hash(
            {"run_id": run["_id"], "api_freeze_id": freeze["freeze_id"]}
        ).removeprefix("sha256:")
        holdout_root = Path(base.run_root) / "holdout" / suffix
        ranking_output = holdout_root / "ranking"
        ledger = self.root / "holdout-ledgers" / str(run["_id"])
        # `reveal` is idempotent after publication and also reconciles the
        # narrow crash window between atomic artifact rename and ledger
        # completion.  A plain artifact verify would leave that CLAIMED ledger
        # unresolved and could expose results without the one-read proof.
        ranking_command = [
            sys.executable,
            "-m",
            "freshquant.backtest.clx.ranking",
            "reveal",
            "--event-dir",
            base.event_dir,
            "--calendar",
            base.calendar_path,
            "--ranking-dir",
            base.ranking_dir,
            "--output-dir",
            str(ranking_output),
            "--ledger-dir",
            str(ledger),
            "--access-log",
            str(holdout_root / "access.jsonl"),
        ]
        self.execute("holdout_ranking", ranking_command, 0.45)
        portfolio_output = holdout_root / "portfolio"
        portfolio_command = [
            sys.executable,
            "-m",
            "freshquant.backtest.clx.portfolio.pipeline",
            "build",
            "--snapshot-dir",
            base.snapshot_dir,
            "--event-dir",
            base.event_dir,
            "--ranking-dir",
            base.ranking_dir,
            "--output-dir",
            str(portfolio_output),
            "--portfolio-config",
            base.portfolio_config_path,
            "--split-id",
            "HOLDOUT",
            "--reveal-dir",
            str(ranking_output),
            *(["--resume"] if portfolio_output.exists() else []),
        ]
        self.execute("holdout_portfolio", portfolio_command, 0.90)
        return {
            **asdict(base),
            "holdout_ranking_dir": str(ranking_output),
            "holdout_portfolio_dir": str(portfolio_output),
            "ledger_dir": str(ledger),
        }


_EXPORT_COLLECTIONS = {
    "rankings": "combo_metrics",
    "metrics": "combo_metrics",
    "equity": "portfolio_equity",
    "trades": "portfolio_trades",
    "signals": "combo_signals",
}


def _flat_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


class ExportRunner:
    def __init__(self, database: Any, *, root: str | Path | None = None) -> None:
        self.db = database
        self.root = artifact_root(root)

    def run(self, job: Mapping[str, object]) -> dict[str, object]:
        collection = _EXPORT_COLLECTIONS[str(job["resource"])]
        query: dict[str, object] = {
            "run_id": job["run_id"],
            "split_id": job["split_id"],
        }
        combo_ids = job.get("combo_ids")
        if (
            isinstance(combo_ids, Sequence)
            and not isinstance(combo_ids, (str, bytes))
            and combo_ids
        ):
            query["combo_id"] = {"$in": list(combo_ids)}
        cursor = self.db[collection].find(query).sort("_id", 1).batch_size(1000)

        def normalized():
            for document in cursor:
                yield {str(key): _flat_value(value) for key, value in document.items()}

        iterator = iter(normalized())
        first = next(iterator, None)
        rows = itertools.chain(() if first is None else (first,), iterator)
        destination = safe_artifact_path(self.root, str(job["artifact_key"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
        file_format = str(job["format"])
        row_count = 0
        if file_format == "json":
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write("[\n")
                for row in rows:
                    if row_count:
                        stream.write(",\n")
                    stream.write(
                        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                    )
                    row_count += 1
                stream.write("\n]\n")
            content_type = "application/json"
        elif file_format == "csv":
            fields = sorted(first) if first is not None else []
            with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(
                    stream, fieldnames=fields, extrasaction="ignore"
                )
                if fields:
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(row)
                        row_count += 1
            content_type = "text/csv"
        elif file_format == "parquet":
            if first is None:
                pq.write_table(pa.table({}), temporary, compression="zstd")
            else:
                batch: list[dict[str, object]] = []
                writer: pq.ParquetWriter | None = None
                try:
                    for row in rows:
                        batch.append(row)
                        row_count += 1
                        if len(batch) < 1000:
                            continue
                        table = pa.Table.from_pylist(
                            batch, schema=writer.schema if writer else None
                        )
                        if writer is None:
                            writer = pq.ParquetWriter(
                                temporary, table.schema, compression="zstd"
                            )
                        writer.write_table(table)
                        batch.clear()
                    if batch:
                        table = pa.Table.from_pylist(
                            batch, schema=writer.schema if writer else None
                        )
                        if writer is None:
                            writer = pq.ParquetWriter(
                                temporary, table.schema, compression="zstd"
                            )
                        writer.write_table(table)
                finally:
                    if writer is not None:
                        writer.close()
            content_type = "application/vnd.apache.parquet"
        else:
            raise ArtifactContractError(f"unsupported export format: {file_format}")
        with temporary.open("rb+") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o444)
        return {
            "artifact_key": str(job["artifact_key"]),
            "artifact_sha256": sha256_file(destination),
            "artifact_size_bytes": destination.stat().st_size,
            "row_count": row_count,
            "content_type": content_type,
            "download_url": f"/api/clx-backtest/exports/{job['_id']}/download",
        }


class SubprocessStageExecutor:
    def __init__(
        self,
        store: MongoWorkerStore,
        job: Mapping[str, object],
        worker_id: str,
        *,
        root: str | Path | None = None,
        poll_seconds: float = 0.5,
    ) -> None:
        self.store = store
        self.job = job
        self.worker_id = worker_id
        self.root = artifact_root(root)
        self.poll_seconds = poll_seconds

    def __call__(
        self, stage: str, command: Sequence[str], progress: float
    ) -> Mapping[str, object]:
        self.store.update_progress(
            self.job,
            f"{stage}:START",
            event_type="STAGE_STARTED",
            progress=max(0.0, progress - 0.1),
            stage=stage,
            details={"command": list(command)},
        )
        log_path = safe_artifact_path(
            self.root,
            f"runs/{self.job['run_id']}/control/logs/{self.job['_id']}-{stage}.log",
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log:
            log.write(
                (
                    f"\n[{utc_now()}] {json.dumps(list(command), ensure_ascii=False)}\n"
                ).encode("utf-8")
            )
            log.flush()
            process = subprocess.Popen(
                list(command),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            next_heartbeat = 0.0
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        if self.store.cancel_requested(self.job):
                            raise JobCancelled(str(self.job["_id"]))
                        self.store.heartbeat(self.job, worker_id=self.worker_id)
                        next_heartbeat = now + max(3.0, self.store.lease_seconds / 3)
                    time.sleep(self.poll_seconds)
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                raise
        if process.returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            raise StageExecutionError(
                f"stage {stage} exited {process.returncode}: {tail}"
            )
        result: dict[str, object] = {"status": "complete", "log_path": str(log_path)}
        for line in reversed(
            log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                result["command_result"] = dict(value)
                break
        self.store.checkpoint(self.job, stage, result)
        self.store.update_progress(
            self.job,
            f"{stage}:COMPLETE",
            event_type="STAGE_COMPLETE",
            progress=progress,
            stage=stage,
            details=result,
        )
        return result


__all__ = [
    "BacktestPipelineRunner",
    "ExportRunner",
    "HoldoutPipelineRunner",
    "JobCancelled",
    "PipelineLayout",
    "StageExecutionError",
    "SubprocessStageExecutor",
    "resolve_pipeline_layout",
]
