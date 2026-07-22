from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifacts import artifact_root
from .projector import ClxArtifactProjector
from .runner import (
    BacktestPipelineRunner,
    ExportRunner,
    HoldoutPipelineRunner,
    JobCancelled,
    SubprocessStageExecutor,
    resolve_pipeline_layout,
)
from .utils import utc_now
from .worker_store import JobLeaseLost, MongoWorkerStore

LOGGER = logging.getLogger(__name__)


def configured_worker_id() -> str:
    return os.getenv("CLX_WORKER_ID") or socket.gethostname()


class _Heartbeat:
    def __init__(
        self, store: MongoWorkerStore, job: Mapping[str, object], worker_id: str
    ) -> None:
        self.store = store
        self.job = job
        self.worker_id = worker_id
        self.stop = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "_Heartbeat":
        self.store.heartbeat(self.job, worker_id=self.worker_id)
        self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop.wait(max(3.0, self.store.lease_seconds / 3)):
            try:
                self.store.heartbeat(self.job, worker_id=self.worker_id)
            except BaseException as exc:
                self.error = exc
                return

    def check(self) -> None:
        if self.error is not None:
            raise self.error

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        if exc_type is not JobCancelled:
            self.check()


class ClxBacktestWorker:
    def __init__(
        self,
        store: MongoWorkerStore | None = None,
        *,
        worker_id: str | None = None,
        root: str | Path | None = None,
    ) -> None:
        self.store = store or MongoWorkerStore()
        self.worker_id = worker_id or configured_worker_id()
        self.root = artifact_root(root)
        self.projector = ClxArtifactProjector(self.store.db)

    def run_once(self) -> bool:
        self.store.reconcile_pending()
        self.store.acknowledge_queued_cancellations()
        self.store.heartbeat_worker(self.worker_id, current_job_id=None)
        job = self.store.claim(self.worker_id)
        if job is None:
            return False
        LOGGER.info("claimed CLX job %s (%s)", job["_id"], job.get("kind"))
        try:
            with _Heartbeat(self.store, job, self.worker_id) as heartbeat:
                result = self._dispatch(job)
                heartbeat.check()
            if self.store.cancel_requested(job) and job.get("kind") == "BACKTEST":
                self.store.cancel(job)
            else:
                self.store.complete(job, result=result)
        except JobCancelled:
            self.store.cancel(job)
        except JobLeaseLost:
            LOGGER.warning("lost CLX job lease %s", job["_id"])
        except BaseException as exc:
            LOGGER.exception("CLX job failed: %s", job["_id"])
            try:
                self.store.fail(
                    job,
                    {
                        "code": type(exc).__name__,
                        "message": str(exc)[-2000:],
                    },
                )
            except JobLeaseLost:
                LOGGER.warning("failure result lost lease for %s", job["_id"])
        finally:
            self.store.heartbeat_worker(self.worker_id, current_job_id=None)
        return True

    def _dispatch(self, job: Mapping[str, object]) -> dict[str, object]:
        run = self.store.db.runs.find_one({"_id": job["run_id"]})
        if run is None:
            raise RuntimeError(f"job run is missing: {job['run_id']}")
        kind = job.get("kind")
        if kind == "EXPORT":
            self.store.update_progress(
                job,
                "export:START",
                event_type="STAGE_STARTED",
                progress=0.1,
                stage="export",
            )
            result = ExportRunner(self.store.db, root=self.root).run(job)
            self.store.checkpoint(job, "export", result)
            self.store.update_progress(
                job,
                "export:COMPLETE",
                event_type="STAGE_COMPLETE",
                progress=0.95,
                stage="export",
                details=result,
            )
            return result
        execute = SubprocessStageExecutor(
            self.store, job, self.worker_id, root=self.root
        )
        if kind == "BACKTEST":
            existing = job.get("resolved_lineage")
            if not isinstance(existing, Mapping):
                layout = resolve_pipeline_layout(run, self.root)
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
                self.store.persist_resolved_lineage(job, lineage)
                job = {**dict(job), "resolved_lineage": lineage}
            lineage = BacktestPipelineRunner(execute, root=self.root).run(run, job)
            projection = self.projector.project_backtest(
                run,
                signal_dir=str(lineage["signal_dir"]),
                event_dir=str(lineage["event_dir"]),
                ranking_dir=str(lineage["ranking_dir"]),
                portfolio_dirs=dict(lineage["portfolio_dirs"]),
            )
            return {"resolved_lineage": lineage, "projection": projection}
        if kind == "HOLDOUT":
            freeze = self.store.db.freeze_records.find_one(
                {
                    "run_id": job["run_id"],
                    "freeze_id": job["freeze_id"],
                    "state": "REVEALING",
                    "reveal_count": 0,
                    "holdout_job_id": job["_id"],
                }
            )
            if freeze is None:
                raise RuntimeError("HOLDOUT job has no reserved reveal proof")
            lineage = HoldoutPipelineRunner(execute, root=self.root).run(
                run, job, freeze
            )
            projection = self.projector.project_holdout(
                run,
                signal_dir=str(lineage["signal_dir"]),
                event_dir=str(lineage["event_dir"]),
                ranking_dir=str(lineage["ranking_dir"]),
                holdout_dir=str(lineage["holdout_ranking_dir"]),
                portfolio_dir=str(lineage["holdout_portfolio_dir"]),
                api_freeze_id=str(freeze["freeze_id"]),
            )
            return {"resolved_lineage": lineage, "projection": projection}
        raise RuntimeError(f"unsupported job kind: {kind}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLX external backtest worker")
    parser.add_argument(
        "command", nargs="?", choices=("run", "once", "health"), default="run"
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-heartbeat-age", type=int, default=90)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=os.getenv("CLX_WORKER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    store = MongoWorkerStore()
    worker_id = configured_worker_id()
    if args.command == "health":
        return (
            0
            if store.ping()
            and store.worker_healthy(worker_id, max_age_seconds=args.max_heartbeat_age)
            else 1
        )
    worker = ClxBacktestWorker(store, worker_id=worker_id)
    if args.command == "once":
        worker.run_once()
        return 0
    stopping = threading.Event()

    def stop(*_: Any) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping.is_set():
        worked = worker.run_once()
        if not worked:
            stopping.wait(max(0.1, args.poll_seconds))
    store.db.workers.update_one(
        {"_id": worker_id},
        {"$set": {"status": "STOPPED", "updated_at": utc_now()}},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ClxBacktestWorker", "configured_worker_id", "main"]
