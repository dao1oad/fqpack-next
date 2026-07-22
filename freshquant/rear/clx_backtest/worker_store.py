from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ReturnDocument

from .artifacts import canonical_json_bytes
from .store import DERIVED_DATABASE_NAME, _holdout_queued_audit
from .utils import new_ulid, utc_now

ACTIVE_JOB_KINDS = ("BACKTEST", "EXPORT", "HOLDOUT")
TERMINAL_JOB_STATUSES = frozenset({"CANCELLED", "FAILED", "COMPLETE"})


class JobLeaseLost(RuntimeError):
    """Raised when a worker no longer owns the claimed job lease."""


def _parse_now(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _event_id(job_id: str, event_key: str) -> str:
    digest = hashlib.sha256(f"{job_id}\0{event_key}".encode()).hexdigest()
    return f"PE{digest}"


def _without_id(document: Mapping[str, object]) -> dict[str, object]:
    copied = copy.deepcopy(dict(document))
    copied.pop("_id", None)
    return copied


class MongoWorkerStore:
    """Atomic Mongo lease and control-plane transitions for CLX workers."""

    def __init__(self, database: Any | None = None, *, lease_seconds: int = 45) -> None:
        if database is None:
            from freshquant.db import get_db

            database = get_db(DERIVED_DATABASE_NAME)
        if getattr(database, "name", DERIVED_DATABASE_NAME) != DERIVED_DATABASE_NAME:
            raise ValueError(f"CLX worker requires database {DERIVED_DATABASE_NAME}")
        if lease_seconds < 10:
            raise ValueError("lease_seconds must be at least 10")
        self.db = database
        self.lease_seconds = lease_seconds

    def ping(self) -> bool:
        return bool(self.db.client.admin.command("ping").get("ok"))

    def reconcile_pending(self, *, limit: int = 100) -> int:
        reconciled = 0
        for run in self.db.runs.find({"projection_pending": True}).limit(limit):
            self._reconcile_run(run)
            reconciled += 1
        remaining = max(0, limit - reconciled)
        for record in self.db.freeze_records.find({"projection_pending": True}).limit(
            remaining
        ):
            self._reconcile_freeze(record)
            reconciled += 1
        # A worker may stop after committing the terminal job document but
        # before publishing the corresponding freeze state.  Reconcile that
        # narrow cross-document window fail-closed: readers remain locked while
        # REVEALING and become visible only from an authoritative COMPLETE job
        # carrying the projector attachment proof.
        remaining = max(0, limit - reconciled)
        for record in self.db.freeze_records.find(
            {"state": "REVEALING", "reveal_count": 0}
        ).limit(remaining):
            if self._reconcile_holdout_terminal(record):
                reconciled += 1
        return reconciled

    def _reconcile_run(self, run: Mapping[str, object]) -> None:
        active = run.get("active_job")
        if isinstance(active, Mapping) and active.get("_id"):
            job = copy.deepcopy(dict(active))
            job_id = job.pop("_id")
            if job.get("status") == "CANCEL_REQUESTED":
                self.db.jobs.update_one(
                    {
                        "_id": job_id,
                        "status": {"$in": ["QUEUED", "RUNNING", "CANCEL_REQUESTED"]},
                    },
                    {"$set": job},
                    upsert=False,
                )
                if self.db.jobs.find_one({"_id": job_id}) is None:
                    self.db.jobs.update_one(
                        {"_id": job_id}, {"$setOnInsert": job}, upsert=True
                    )
            else:
                self.db.jobs.update_one(
                    {"_id": job_id}, {"$setOnInsert": job}, upsert=True
                )
        control_events = run.get("control_events")
        if isinstance(control_events, Sequence) and not isinstance(
            control_events, (str, bytes)
        ):
            for event in control_events:
                if isinstance(event, Mapping) and event.get("_id"):
                    self.db.progress_events.update_one(
                        {"_id": event["_id"]},
                        {"$setOnInsert": copy.deepcopy(dict(event))},
                        upsert=True,
                    )
        last = run.get("last_control_event")
        last_id = last.get("_id") if isinstance(last, Mapping) else None
        query: dict[str, object] = {"_id": run["_id"], "projection_pending": True}
        if last_id is not None:
            query["last_control_event._id"] = last_id
        self.db.runs.update_one(query, {"$set": {"projection_pending": False}})

    def _reconcile_freeze(self, record: Mapping[str, object]) -> None:
        job = record.get("holdout_job")
        projected_job: Mapping[str, object] | None = None
        if isinstance(job, Mapping) and job.get("_id"):
            copied = copy.deepcopy(dict(job))
            job_id = copied.pop("_id")
            self.db.jobs.update_one(
                {"_id": job_id}, {"$setOnInsert": copied}, upsert=True
            )
            projected_job = job
        event = record.get("last_control_event")
        if isinstance(event, Mapping) and event.get("_id"):
            self.db.progress_events.update_one(
                {"_id": event["_id"]},
                {"$setOnInsert": copy.deepcopy(dict(event))},
                upsert=True,
            )
            if projected_job is not None and projected_job.get("kind") == "HOLDOUT":
                audit = _holdout_queued_audit(projected_job, event)
                self.db.audit_findings.update_one(
                    {"_id": audit["_id"]},
                    {"$setOnInsert": audit},
                    upsert=True,
                )
        query: dict[str, object] = {
            "_id": record["_id"],
            "projection_pending": True,
        }
        if isinstance(event, Mapping):
            query["last_control_event._id"] = event.get("_id")
        self.db.freeze_records.update_one(
            query, {"$set": {"projection_pending": False}}
        )

    @staticmethod
    def _holdout_projection_proof(
        job: Mapping[str, object], freeze_id: object
    ) -> Mapping[str, object] | None:
        result = job.get("result")
        projection = result.get("projection") if isinstance(result, Mapping) else None
        attachment = (
            projection.get("holdout") if isinstance(projection, Mapping) else None
        )
        if (
            not isinstance(attachment, Mapping)
            or attachment.get("api_freeze_id") != freeze_id
            or not isinstance(attachment.get("projection_sha256"), str)
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", str(attachment["projection_sha256"])
            )
            is None
        ):
            return None
        return attachment

    def _reconcile_holdout_terminal(
        self,
        record: Mapping[str, object],
        *,
        terminal_job: Mapping[str, object] | None = None,
    ) -> bool:
        job_id = record.get("holdout_job_id")
        if not job_id:
            return False
        authoritative = terminal_job or self.db.jobs.find_one({"_id": job_id})
        if not isinstance(authoritative, Mapping):
            return False
        if (
            authoritative.get("_id") != job_id
            or authoritative.get("job_id") != job_id
            or authoritative.get("kind") != "HOLDOUT"
            or authoritative.get("run_id") != record.get("run_id")
            or authoritative.get("freeze_id") != record.get("freeze_id")
        ):
            return False
        status = authoritative.get("status")
        if status not in TERMINAL_JOB_STATUSES:
            return False

        now = str(authoritative.get("finished_at") or utc_now())
        freeze_id = record.get("freeze_id")
        proof = (
            self._holdout_projection_proof(authoritative, freeze_id)
            if status == "COMPLETE"
            else None
        )
        revealed = status == "COMPLETE" and proof is not None
        fields: dict[str, object] = {
            "state": "REVEALED" if revealed else "REVEAL_FAILED",
            "holdout_job": copy.deepcopy(dict(authoritative)),
            "updated_at": now,
            "projection_pending": False,
        }
        unset: dict[str, str] = {}
        update: dict[str, object] = {"$set": fields}
        if revealed:
            assert proof is not None
            fields["holdout_revealed_at"] = now
            fields["holdout_projection_sha256"] = proof["projection_sha256"]
            update["$inc"] = {"reveal_count": 1}
            unset = {
                "holdout_reveal_failed_at": "",
                "holdout_reveal_error": "",
            }
        else:
            fields["holdout_reveal_failed_at"] = now
            error = authoritative.get("error")
            if status == "COMPLETE":
                error = {
                    "code": "HOLDOUT_PROJECTION_PROOF_MISSING",
                    "message": (
                        "HOLDOUT job completed without a verified Mongo "
                        "projection attachment"
                    ),
                }
            fields["holdout_reveal_error"] = copy.deepcopy(error or {"status": status})
        if unset:
            update["$unset"] = unset
        kind = "HOLDOUT_REVEALED" if revealed else "HOLDOUT_REVEAL_FAILED"
        audit_id = _event_id(str(job_id), kind)
        self.db.audit_findings.update_one(
            {"_id": audit_id},
            {
                "$setOnInsert": {
                    "finding_id": audit_id,
                    "run_id": record["run_id"],
                    "kind": kind,
                    "severity": "INFO" if revealed else "ERROR",
                    "status": "RECORDED" if revealed else "OPEN",
                    "details": {
                        "freeze_id": freeze_id,
                        "job_id": job_id,
                        "projection_sha256": (
                            proof.get("projection_sha256")
                            if proof is not None
                            else None
                        ),
                    },
                    "created_at": now,
                }
            },
            upsert=True,
        )
        changed = self.db.freeze_records.update_one(
            {
                "_id": record["_id"],
                "state": "REVEALING",
                "reveal_count": 0,
                "holdout_job_id": job_id,
            },
            update,
        )
        if changed.matched_count != 1:
            return False
        return True

    def claim(
        self,
        worker_id: str,
        *,
        kinds: Sequence[str] = ACTIVE_JOB_KINDS,
        now: str | None = None,
    ) -> dict[str, object] | None:
        current = now or utc_now()
        lease_expires = _iso(
            _parse_now(current) + timedelta(seconds=self.lease_seconds)
        )
        token = new_ulid()
        query = {
            "kind": {"$in": list(kinds)},
            "$or": [
                {"status": "QUEUED"},
                {
                    "status": "RUNNING",
                    "lease_expires_at": {"$lte": current},
                },
            ],
        }
        job = self.db.jobs.find_one_and_update(
            query,
            {
                "$set": {
                    "status": "RUNNING",
                    "worker_id": worker_id,
                    "lease_token": token,
                    "lease_expires_at": lease_expires,
                    "heartbeat_at": current,
                    "updated_at": current,
                    "started_at": current,
                },
                "$inc": {"attempt_count": 1},
            },
            sort=[("created_at", 1), ("_id", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if job is None:
            return None
        if self._bind_control_plane(job, current):
            self.emit_progress(
                job,
                "JOB_RUNNING",
                event_type="JOB_RUNNING",
                progress=float(job.get("progress", 0.0)),
                details={"worker_id": worker_id, "attempt": job.get("attempt_count")},
                now=current,
            )
            return copy.deepcopy(job)
        current_job = self.db.jobs.find_one({"_id": job["_id"]}) or job
        cancelled = current_job.get("status") == "CANCEL_REQUESTED"
        if job.get("kind") == "BACKTEST":
            run = self.db.runs.find_one({"_id": job["run_id"]}, {"status": 1})
            cancelled = cancelled or (
                run is not None and run.get("status") == "CANCEL_REQUESTED"
            )
        self._terminal_update(
            current_job,
            token,
            "CANCELLED" if cancelled else "FAILED",
            current,
            error=(
                None
                if cancelled
                else {
                    "code": "CONTROL_PLANE_MISMATCH",
                    "message": (
                        "claimed job does not match its authoritative run/freeze"
                    ),
                }
            ),
        )
        return None

    def _bind_control_plane(self, job: Mapping[str, object], now: str) -> bool:
        kind = job.get("kind")
        if kind == "BACKTEST":
            result = self.db.runs.update_one(
                {
                    "_id": job["run_id"],
                    "active_job_id": job["_id"],
                    "status": {"$in": ["QUEUED", "RUNNING"]},
                },
                {
                    "$set": {
                        "status": "RUNNING",
                        "active_job": copy.deepcopy(dict(job)),
                        "updated_at": now,
                        "projection_pending": False,
                    }
                },
            )
            return result.matched_count == 1
        if kind == "HOLDOUT":
            result = self.db.freeze_records.update_one(
                {
                    "run_id": job["run_id"],
                    "freeze_id": job["freeze_id"],
                    "state": "REVEALING",
                    "reveal_count": 0,
                    "holdout_job_id": job["_id"],
                },
                {"$set": {"holdout_job": copy.deepcopy(dict(job)), "updated_at": now}},
            )
            return result.matched_count == 1
        if kind == "EXPORT":
            run = self.db.runs.find_one({"_id": job["run_id"]}, {"_id": 1})
            if run is None:
                return False
            if job.get("split_id") == "HOLDOUT":
                access = job.get("holdout_access")
                freeze_id = (
                    access.get("freeze_id") if isinstance(access, Mapping) else None
                )
                return (
                    self.db.freeze_records.find_one(
                        {
                            "run_id": job["run_id"],
                            "freeze_id": freeze_id,
                            "state": "REVEALED",
                            "reveal_count": 1,
                        },
                        {"_id": 1},
                    )
                    is not None
                )
            return True
        return False

    def heartbeat(
        self, job: Mapping[str, object], *, worker_id: str, now: str | None = None
    ) -> None:
        current = now or utc_now()
        expires = _iso(_parse_now(current) + timedelta(seconds=self.lease_seconds))
        result = self.db.jobs.update_one(
            {
                "_id": job["_id"],
                "status": "RUNNING",
                "worker_id": worker_id,
                "lease_token": job["lease_token"],
            },
            {
                "$set": {
                    "heartbeat_at": current,
                    "lease_expires_at": expires,
                    "updated_at": current,
                }
            },
        )
        if result.matched_count != 1:
            raise JobLeaseLost(str(job["_id"]))
        self.heartbeat_worker(worker_id, current_job_id=str(job["_id"]), now=current)

    def heartbeat_worker(
        self, worker_id: str, *, current_job_id: str | None, now: str | None = None
    ) -> None:
        current = now or utc_now()
        self.db.workers.update_one(
            {"_id": worker_id},
            {
                "$set": {
                    "worker_id": worker_id,
                    "status": "ALIVE",
                    "heartbeat_at": current,
                    "current_job_id": current_job_id,
                    "updated_at": current,
                },
                "$setOnInsert": {"created_at": current},
            },
            upsert=True,
        )

    def worker_healthy(self, worker_id: str, *, max_age_seconds: int = 90) -> bool:
        worker = self.db.workers.find_one({"_id": worker_id, "status": "ALIVE"})
        if worker is None or not isinstance(worker.get("heartbeat_at"), str):
            return False
        return _parse_now(worker["heartbeat_at"]) >= datetime.now(
            timezone.utc
        ) - timedelta(seconds=max_age_seconds)

    def update_progress(
        self,
        job: Mapping[str, object],
        event_key: str,
        *,
        event_type: str,
        progress: float,
        stage: str,
        details: Mapping[str, object] | None = None,
        now: str | None = None,
    ) -> None:
        current = now or utc_now()
        result = self.db.jobs.update_one(
            {
                "_id": job["_id"],
                "status": "RUNNING",
                "lease_token": job["lease_token"],
            },
            {
                "$set": {
                    "progress": progress,
                    "stage": stage,
                    "updated_at": current,
                }
            },
        )
        if result.matched_count != 1:
            raise JobLeaseLost(str(job["_id"]))
        self.emit_progress(
            job,
            event_key,
            event_type=event_type,
            progress=progress,
            stage=stage,
            details=details,
            now=current,
        )
        if job.get("kind") == "BACKTEST":
            self.db.runs.update_one(
                {"_id": job["run_id"], "active_job_id": job["_id"]},
                {
                    "$set": {
                        "active_job.progress": progress,
                        "active_job.stage": stage,
                        "active_job.updated_at": current,
                        "updated_at": current,
                    }
                },
            )

    def emit_progress(
        self,
        job: Mapping[str, object],
        event_key: str,
        *,
        event_type: str,
        progress: float | None,
        stage: str | None = None,
        details: Mapping[str, object] | None = None,
        now: str | None = None,
    ) -> dict[str, object]:
        current = now or utc_now()
        event_id = _event_id(str(job["_id"]), event_key)
        event: dict[str, object] = {
            "_id": event_id,
            "event_id": event_id,
            "event_key": event_key,
            "run_id": job["run_id"],
            "job_id": job["_id"],
            "event_type": event_type,
            "progress": progress,
            "created_at": current,
        }
        if stage is not None:
            event["stage"] = stage
        if details:
            event["details"] = copy.deepcopy(dict(details))
        self.db.progress_events.update_one(
            {"_id": event_id}, {"$setOnInsert": event}, upsert=True
        )
        return event

    def checkpoint(
        self,
        job: Mapping[str, object],
        stage: str,
        result: Mapping[str, object],
        *,
        now: str | None = None,
    ) -> None:
        current = now or utc_now()
        payload = copy.deepcopy(dict(result))
        payload["completed_at"] = current
        update = self.db.jobs.update_one(
            {
                "_id": job["_id"],
                "status": "RUNNING",
                "lease_token": job["lease_token"],
            },
            {"$set": {f"checkpoints.{stage}": payload, "updated_at": current}},
        )
        if update.matched_count != 1:
            raise JobLeaseLost(str(job["_id"]))

    def persist_resolved_lineage(
        self, job: Mapping[str, object], lineage: Mapping[str, object]
    ) -> None:
        digest = "sha256:" + hashlib.sha256(canonical_json_bytes(lineage)).hexdigest()
        result = self.db.jobs.update_one(
            {
                "_id": job["_id"],
                "lease_token": job["lease_token"],
                "$or": [
                    {"resolved_lineage_sha256": {"$exists": False}},
                    {"resolved_lineage_sha256": digest},
                ],
            },
            {
                "$set": {
                    "resolved_lineage": copy.deepcopy(dict(lineage)),
                    "resolved_lineage_sha256": digest,
                }
            },
        )
        if result.matched_count != 1:
            raise JobLeaseLost("resolved lineage differs from prior attempt")
        if job.get("kind") == "BACKTEST":
            run_result = self.db.runs.update_one(
                {
                    "_id": job["run_id"],
                    "active_job_id": job["_id"],
                    "$or": [
                        {"resolved_lineage_sha256": {"$exists": False}},
                        {"resolved_lineage_sha256": digest},
                    ],
                },
                {
                    "$set": {
                        "resolved_lineage": copy.deepcopy(dict(lineage)),
                        "resolved_lineage_sha256": digest,
                    }
                },
            )
            if run_result.matched_count != 1:
                raise JobLeaseLost("run lineage differs from prior attempt")

    def cancel_requested(self, job: Mapping[str, object]) -> bool:
        current = self.db.jobs.find_one({"_id": job["_id"]}, {"status": 1})
        if current is None or current.get("status") == "CANCEL_REQUESTED":
            return True
        if job.get("kind") == "BACKTEST":
            run = self.db.runs.find_one({"_id": job["run_id"]}, {"status": 1})
            return run is None or run.get("status") == "CANCEL_REQUESTED"
        return False

    def complete(
        self,
        job: Mapping[str, object],
        *,
        result: Mapping[str, object] | None = None,
        now: str | None = None,
    ) -> None:
        self._terminal_update(
            job,
            str(job["lease_token"]),
            "COMPLETE",
            now or utc_now(),
            result=result,
        )

    def fail(
        self,
        job: Mapping[str, object],
        error: Mapping[str, object],
        *,
        now: str | None = None,
    ) -> None:
        self._terminal_update(
            job,
            str(job["lease_token"]),
            "FAILED",
            now or utc_now(),
            error=error,
        )

    def cancel(self, job: Mapping[str, object], *, now: str | None = None) -> None:
        self._terminal_update(
            job, str(job["lease_token"]), "CANCELLED", now or utc_now()
        )

    def _terminal_update(
        self,
        job: Mapping[str, object],
        token: str,
        status: str,
        now: str,
        *,
        result: Mapping[str, object] | None = None,
        error: Mapping[str, object] | None = None,
    ) -> None:
        if status != "CANCELLED":
            current_job = self.db.jobs.find_one(
                {"_id": job["_id"]}, {"status": 1, "lease_token": 1}
            )
            run_cancelled = False
            if job.get("kind") == "BACKTEST":
                run = self.db.runs.find_one({"_id": job["run_id"]}, {"status": 1})
                run_cancelled = (
                    run is not None and run.get("status") == "CANCEL_REQUESTED"
                )
            if (
                current_job is not None
                and current_job.get("lease_token") == token
                and (current_job.get("status") == "CANCEL_REQUESTED" or run_cancelled)
            ):
                status = "CANCELLED"
                result = None
                error = None
        fields: dict[str, object] = {
            "status": status,
            "finished_at": now,
            "updated_at": now,
        }
        if status == "COMPLETE":
            fields["progress"] = 1.0
        if result is not None:
            fields["result"] = copy.deepcopy(dict(result))
            if job.get("kind") == "EXPORT":
                for key in (
                    "artifact_key",
                    "artifact_sha256",
                    "artifact_size_bytes",
                    "row_count",
                    "content_type",
                    "download_url",
                ):
                    if key in result:
                        fields[key] = copy.deepcopy(result[key])
        if error is not None:
            fields["error"] = copy.deepcopy(dict(error))
        update = self.db.jobs.update_one(
            {
                "_id": job["_id"],
                "lease_token": token,
                "status": (
                    {"$in": ["RUNNING", "CANCEL_REQUESTED"]}
                    if status == "CANCELLED"
                    else "RUNNING"
                ),
            },
            {"$set": fields, "$unset": {"lease_token": "", "lease_expires_at": ""}},
        )
        if update.matched_count != 1 and status != "CANCELLED":
            current_job = self.db.jobs.find_one(
                {"_id": job["_id"]}, {"status": 1, "lease_token": 1}
            )
            if (
                current_job is not None
                and current_job.get("status") == "CANCEL_REQUESTED"
                and current_job.get("lease_token") == token
            ):
                status = "CANCELLED"
                fields = {
                    "status": status,
                    "finished_at": now,
                    "updated_at": now,
                }
                result = None
                error = None
                update = self.db.jobs.update_one(
                    {
                        "_id": job["_id"],
                        "lease_token": token,
                        "status": "CANCEL_REQUESTED",
                    },
                    {
                        "$set": fields,
                        "$unset": {"lease_token": "", "lease_expires_at": ""},
                    },
                )
        if update.matched_count != 1:
            raise JobLeaseLost(str(job["_id"]))
        terminal_job = self.db.jobs.find_one({"_id": job["_id"]})
        if terminal_job is None:
            raise JobLeaseLost(str(job["_id"]))
        if job.get("kind") == "BACKTEST":
            run_status = status
            self.db.runs.update_one(
                {"_id": job["run_id"], "active_job_id": job["_id"]},
                {
                    "$set": {
                        "status": run_status,
                        "active_job": terminal_job,
                        "updated_at": now,
                        "finished_at": now,
                        "projection_pending": False,
                    }
                },
            )
        elif job.get("kind") == "HOLDOUT":
            record = self.db.freeze_records.find_one(
                {
                    "run_id": job["run_id"],
                    "freeze_id": job["freeze_id"],
                    "holdout_job_id": job["_id"],
                }
            )
            if isinstance(record, Mapping):
                self._reconcile_holdout_terminal(record, terminal_job=terminal_job)
        self.emit_progress(
            terminal_job,
            f"JOB_{status}",
            event_type=f"JOB_{status}",
            progress=(
                float(terminal_job["progress"])
                if isinstance(terminal_job.get("progress"), (int, float))
                else None
            ),
            details=error or result,
            now=now,
        )

    def acknowledge_queued_cancellations(self, *, limit: int = 100) -> int:
        count = 0
        for run in self.db.runs.find({"status": "CANCEL_REQUESTED"}).limit(limit):
            job_id = run.get("active_job_id")
            job = self.db.jobs.find_one({"_id": job_id, "status": "CANCEL_REQUESTED"})
            if job is None:
                continue
            now = utc_now()
            self.db.jobs.update_one(
                {"_id": job_id, "status": "CANCEL_REQUESTED"},
                {
                    "$set": {
                        "status": "CANCELLED",
                        "finished_at": now,
                        "updated_at": now,
                    }
                },
            )
            job["status"] = "CANCELLED"
            job["finished_at"] = now
            job["updated_at"] = now
            self.db.runs.update_one(
                {"_id": run["_id"], "status": "CANCEL_REQUESTED"},
                {
                    "$set": {
                        "status": "CANCELLED",
                        "active_job": job,
                        "finished_at": now,
                        "updated_at": now,
                        "projection_pending": False,
                    }
                },
            )
            self.emit_progress(
                job,
                "JOB_CANCELLED",
                event_type="JOB_CANCELLED",
                progress=None,
                now=now,
            )
            count += 1
        return count


__all__ = [
    "ACTIVE_JOB_KINDS",
    "JobLeaseLost",
    "MongoWorkerStore",
    "TERMINAL_JOB_STATUSES",
]
