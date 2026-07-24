from __future__ import annotations

import copy
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol, Sequence, cast

from .utils import new_ulid

DERIVED_DATABASE_NAME = "freshquant_clx_backtest"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    keys: tuple[tuple[str, int], ...]
    name: str
    unique: bool = False


INDEX_DEFINITIONS: dict[str, tuple[IndexDefinition, ...]] = {
    "runs": (
        IndexDefinition(
            (("status", 1), ("created_at", -1), ("_id", 1)), "runs_status_created"
        ),
        IndexDefinition((("config_sha256", 1),), "runs_config_sha256"),
    ),
    "jobs": (
        IndexDefinition(
            (("run_id", 1), ("status", 1), ("updated_at", -1)), "jobs_run_status"
        ),
        IndexDefinition(
            (
                ("status", 1),
                ("kind", 1),
                ("lease_expires_at", 1),
                ("created_at", 1),
                ("_id", 1),
            ),
            "jobs_atomic_claim",
        ),
    ),
    "manifests": (
        IndexDefinition((("run_id", 1),), "manifests_run_unique", True),
        IndexDefinition((("manifest_sha256", 1),), "manifests_sha_unique", True),
    ),
    "model_registry": (
        IndexDefinition(
            (("registry_version", 1), ("model_id", 1)), "registry_model_unique", True
        ),
    ),
    "combo_definitions": (
        IndexDefinition(
            (("run_id", 1), ("combo_id", 1)), "combo_definition_unique", True
        ),
    ),
    "combo_metrics": (
        IndexDefinition(
            (
                ("run_id", 1),
                ("combo_id", 1),
                ("split_id", 1),
                ("segment_type", 1),
                ("segment_value", 1),
                ("horizon", 1),
            ),
            "combo_metric_unique",
            True,
        ),
        IndexDefinition(
            (("run_id", 1), ("split_id", 1), ("score", -1), ("combo_id", 1)),
            "combo_metric_rank",
        ),
        IndexDefinition(
            (
                ("run_id", 1),
                ("split_id", 1),
                ("horizon", 1),
                ("segment_type", 1),
                ("segment_value", 1),
                ("frozen_rank", 1),
                ("combo_id", 1),
                ("_id", 1),
            ),
            "combo_metric_frozen_rank",
        ),
    ),
    "portfolio_summaries": (
        IndexDefinition(
            (("run_id", 1), ("portfolio_id", 1), ("split_id", 1)),
            "portfolio_summary_unique",
            True,
        ),
        IndexDefinition(
            (("run_id", 1), ("combo_id", 1), ("split_id", 1)),
            "portfolio_summary_combo_split",
        ),
    ),
    "portfolio_equity": (
        IndexDefinition(
            (("run_id", 1), ("combo_id", 1), ("trade_date", 1)), "portfolio_equity_page"
        ),
    ),
    "portfolio_trades": (
        IndexDefinition(
            (("run_id", 1), ("combo_id", 1), ("sequence", 1)), "portfolio_trades_page"
        ),
    ),
    "combo_signals": (
        IndexDefinition(
            (("run_id", 1), ("combo_id", 1), ("reveal_date", 1), ("signal_fact_id", 1)),
            "combo_signals_page",
        ),
    ),
    "model_heatmap": (
        IndexDefinition(
            (("run_id", 1), ("split_id", 1), ("model_id", 1), ("trigger_key", 1)),
            "model_heatmap_unique",
            True,
        ),
    ),
    "audit_findings": (
        IndexDefinition(
            (("run_id", 1), ("severity", 1), ("kind", 1), ("status", 1)),
            "audit_run_kind",
        ),
    ),
    "freeze_records": (
        IndexDefinition((("run_id", 1),), "freeze_run_once", True),
        IndexDefinition((("run_id", 1), ("freeze_id", 1)), "freeze_run_unique", True),
    ),
    "progress_events": (
        IndexDefinition(
            (("run_id", 1), ("created_at", 1), ("_id", 1)), "progress_run_page"
        ),
    ),
    "workers": (IndexDefinition((("heartbeat_at", -1),), "workers_heartbeat"),),
}

QUERY_COLLECTIONS = frozenset(INDEX_DEFINITIONS)


class ClxBacktestStore(Protocol):
    index_definitions: Mapping[str, Sequence[IndexDefinition]]

    def ping(self) -> bool: ...

    def create_run(self, document: Mapping[str, object]) -> dict[str, object]: ...

    def get_one(
        self, collection: str, equals: Mapping[str, object]
    ) -> dict[str, object] | None: ...

    def find_many(
        self,
        collection: str,
        *,
        equals: Mapping[str, object],
        ranges: Mapping[str, tuple[str, object]] | None,
        sort: Sequence[tuple[str, int]],
        limit: int,
        after: Sequence[object] | None,
    ) -> list[dict[str, object]]: ...

    def start_run(
        self, run_id: str, expected_hash: str, *, now: str, job_id: str
    ) -> dict[str, object]: ...

    def cancel_run(
        self, run_id: str, *, now: str, reason: str | None
    ) -> dict[str, object]: ...

    def create_freeze(
        self, document: Mapping[str, object]
    ) -> tuple[dict[str, object], bool]: ...

    def reveal_holdout(
        self, run_id: str, freeze_id: str, *, now: str, job_id: str
    ) -> dict[str, object]: ...

    def holdout_revealed(self, run_id: str) -> bool: ...

    def insert_document(
        self, collection: str, document: Mapping[str, object]
    ) -> dict[str, object]: ...


def _copy(document: Mapping[str, object] | None) -> dict[str, object] | None:
    return copy.deepcopy(dict(document)) if document is not None else None


def _matches_equals(
    document: Mapping[str, object], equals: Mapping[str, object]
) -> bool:
    """Match Mongo scalar equality, including scalar membership in array fields."""

    for key, expected in equals.items():
        actual = document.get(key)
        if isinstance(actual, list) and not isinstance(expected, list):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    return True


def _control_event(
    run_id: str,
    job_id: str | None,
    event_type: str,
    now: str,
    progress: float | None,
) -> dict[str, object]:
    event_id = new_ulid()
    return {
        "_id": event_id,
        "event_id": event_id,
        "run_id": run_id,
        "job_id": job_id,
        "event_type": event_type,
        "progress": progress,
        "created_at": now,
    }


def _holdout_queued_audit(
    job: Mapping[str, object], event: Mapping[str, object]
) -> dict[str, object]:
    """Build the idempotent audit projection owned by a HOLDOUT reservation."""

    audit_id = f"{event['_id']}:HOLDOUT_REVEAL_QUEUED"
    return {
        "_id": audit_id,
        "finding_id": audit_id,
        "run_id": job["run_id"],
        "kind": "HOLDOUT_REVEAL_QUEUED",
        "severity": "INFO",
        "status": "RECORDED",
        "details": {
            "freeze_id": job["freeze_id"],
            "job_id": job["_id"],
        },
        "created_at": event["created_at"],
    }


def _value_after(
    document: Mapping[str, object],
    sort: Sequence[tuple[str, int]],
    after: Sequence[object],
) -> bool:
    for (field, direction), cursor_value in zip(sort, after, strict=True):
        value = cast(Any, document.get(field))
        comparable_cursor = cast(Any, cursor_value)
        if value == cursor_value:
            continue
        if value is None:
            return direction < 0
        if cursor_value is None:
            return direction > 0
        return value > comparable_cursor if direction > 0 else value < comparable_cursor
    return False


def _sort_key(value: object) -> tuple[bool, object]:
    return value is not None, value


class MemoryClxBacktestStore:
    """Thread-safe fixture store with the same state transitions as Mongo."""

    index_definitions: Mapping[str, Sequence[IndexDefinition]] = INDEX_DEFINITIONS

    def __init__(self) -> None:
        self._collections: dict[str, list[dict[str, object]]] = defaultdict(list)
        self._lock = threading.RLock()

    def ping(self) -> bool:
        return True

    def seed(self, collection: str, documents: Iterable[Mapping[str, object]]) -> None:
        self._require_collection(collection)
        with self._lock:
            for source in documents:
                document = copy.deepcopy(dict(source))
                document.setdefault("_id", new_ulid())
                self._assert_unique_id(collection, str(document["_id"]))
                self._collections[collection].append(document)

    def create_run(self, document: Mapping[str, object]) -> dict[str, object]:
        return self.insert_document("runs", document)

    def get_one(
        self, collection: str, equals: Mapping[str, object]
    ) -> dict[str, object] | None:
        self._require_collection(collection)
        with self._lock:
            for document in self._collections[collection]:
                if _matches_equals(document, equals):
                    return _copy(document)
        return None

    def find_many(
        self,
        collection: str,
        *,
        equals: Mapping[str, object],
        ranges: Mapping[str, tuple[str, object]] | None,
        sort: Sequence[tuple[str, int]],
        limit: int,
        after: Sequence[object] | None,
    ) -> list[dict[str, object]]:
        self._require_collection(collection)
        with self._lock:
            documents = [
                copy.deepcopy(document)
                for document in self._collections[collection]
                if _matches_equals(document, equals)
                and self._matches_ranges(document, ranges or {})
                and (after is None or _value_after(document, sort, after))
            ]
        for field, direction in reversed(sort):
            documents.sort(
                key=lambda item: _sort_key(item.get(field)), reverse=direction < 0
            )
        return documents[:limit]

    def start_run(
        self, run_id: str, expected_hash: str, *, now: str, job_id: str
    ) -> dict[str, object]:
        with self._lock:
            run = self._find_mutable("runs", {"_id": run_id})
            if run is None:
                return {"reason": "NOT_FOUND"}
            if run.get("config_sha256") != expected_hash:
                return {"reason": "CONFIG_HASH_MISMATCH", "run": _copy(run)}
            if run.get("status") != "DRAFT":
                return {"reason": "INVALID_STATE", "run": _copy(run)}
            prior_projection_pending = bool(run.get("projection_pending"))
            job = {
                "_id": job_id,
                "job_id": job_id,
                "run_id": run_id,
                "kind": "BACKTEST",
                "status": "QUEUED",
                "execution_mode": "EXTERNAL_WORKER",
                "progress": 0.0,
                "created_at": now,
                "updated_at": now,
            }
            event = _control_event(run_id, job_id, "RUN_QUEUED", now, 0.0)
            run.update(
                {
                    "status": "QUEUED",
                    "active_job_id": job_id,
                    "active_job": copy.deepcopy(job),
                    "started_at": now,
                    "updated_at": now,
                    "last_control_event": copy.deepcopy(event),
                    "control_events": [copy.deepcopy(event)],
                    "projection_pending": True,
                }
            )
            try:
                self._project_control_locked(job, event)
            except Exception:
                LOGGER.exception("CLX start projections require reconciliation")
            else:
                run["projection_pending"] = prior_projection_pending
            return {"reason": "OK", "run": _copy(run), "job": _copy(job)}

    def cancel_run(
        self, run_id: str, *, now: str, reason: str | None
    ) -> dict[str, object]:
        with self._lock:
            run = self._find_mutable("runs", {"_id": run_id})
            if run is None:
                return {"reason": "NOT_FOUND"}
            if run.get("status") not in {"QUEUED", "RUNNING"}:
                return {"reason": "INVALID_STATE", "run": _copy(run)}
            prior_projection_pending = bool(run.get("projection_pending"))
            run.update(
                {
                    "status": "CANCEL_REQUESTED",
                    "cancel_requested_at": now,
                    "updated_at": now,
                }
            )
            job_id = str(run.get("active_job_id", ""))
            embedded = run.get("active_job")
            job = (
                copy.deepcopy(dict(embedded))
                if isinstance(embedded, Mapping)
                else {
                    "_id": job_id,
                    "job_id": job_id,
                    "run_id": run_id,
                    "kind": "BACKTEST",
                    "execution_mode": "EXTERNAL_WORKER",
                }
            )
            job.update(
                {
                    "status": "CANCEL_REQUESTED",
                    "cancel_reason": reason,
                    "updated_at": now,
                }
            )
            event = _control_event(
                run_id, job_id or None, "CANCEL_REQUESTED", now, None
            )
            run["active_job"] = copy.deepcopy(job)
            run["last_control_event"] = copy.deepcopy(event)
            control_events = run.get("control_events")
            if not isinstance(control_events, list):
                control_events = []
                run["control_events"] = control_events
            control_events.append(copy.deepcopy(event))
            run["projection_pending"] = True
            try:
                self._project_control_locked(job, event)
            except Exception:
                LOGGER.exception("CLX cancel projections require reconciliation")
            else:
                run["projection_pending"] = prior_projection_pending
            return {"reason": "OK", "run": _copy(run), "job": _copy(job)}

    def create_freeze(
        self, document: Mapping[str, object]
    ) -> tuple[dict[str, object], bool]:
        run_id = str(document["run_id"])
        freeze_id = str(document["freeze_id"])
        with self._lock:
            existing = self._find_mutable("freeze_records", {"run_id": run_id})
            if existing is not None:
                return _copy(existing) or {}, False
            created = copy.deepcopy(dict(document))
            self._collections["freeze_records"].append(created)
            return _copy(created) or {}, True

    def reveal_holdout(
        self, run_id: str, freeze_id: str, *, now: str, job_id: str
    ) -> dict[str, object]:
        with self._lock:
            record = self._find_mutable(
                "freeze_records", {"run_id": run_id, "freeze_id": freeze_id}
            )
            if record is None:
                return {"reason": "NOT_FOUND"}
            if record.get("state") != "FROZEN" or record.get("reveal_count") != 0:
                reason = (
                    "ALREADY_REVEALED"
                    if record.get("state") == "REVEALED"
                    and record.get("reveal_count") == 1
                    else (
                        "REVEAL_FAILED"
                        if record.get("state") == "REVEAL_FAILED"
                        else "ALREADY_REQUESTED"
                    )
                )
                return {"reason": reason, "freeze": _copy(record)}
            # This transition only reserves the one reveal job.  HOLDOUT remains
            # query-locked until the worker has verified both artifacts,
            # projected them, and atomically publishes REVEALED on this record.
            record["state"] = "REVEALING"
            record["holdout_reveal_requested_at"] = now
            job = {
                "_id": job_id,
                "job_id": job_id,
                "run_id": run_id,
                "freeze_id": freeze_id,
                "kind": "HOLDOUT",
                "status": "QUEUED",
                "execution_mode": "EXTERNAL_WORKER",
                "progress": 0.0,
                "created_at": now,
                "updated_at": now,
            }
            event = _control_event(run_id, job_id, "HOLDOUT_QUEUED", now, 0.0)
            record["holdout_job_id"] = job_id
            record["holdout_job"] = copy.deepcopy(job)
            record["last_control_event"] = copy.deepcopy(event)
            record["projection_pending"] = True
            try:
                self._project_control_locked(job, event)
            except Exception:
                LOGGER.exception("CLX HOLDOUT projections require reconciliation")
            else:
                record["projection_pending"] = False
            return {"reason": "OK", "freeze": _copy(record)}

    def holdout_revealed(self, run_id: str) -> bool:
        with self._lock:
            return any(
                item.get("run_id") == run_id
                and item.get("state") == "REVEALED"
                and item.get("reveal_count") == 1
                for item in self._collections["freeze_records"]
            )

    def insert_document(
        self, collection: str, document: Mapping[str, object]
    ) -> dict[str, object]:
        self._require_collection(collection)
        created = copy.deepcopy(dict(document))
        created.setdefault("_id", new_ulid())
        with self._lock:
            self._assert_unique_id(collection, str(created["_id"]))
            self._collections[collection].append(created)
        return _copy(created) or {}

    def _project_control_locked(
        self, job: Mapping[str, object], event: Mapping[str, object]
    ) -> None:
        projected = self._find_mutable("jobs", {"_id": job["_id"]})
        if projected is None:
            self._collections["jobs"].append(copy.deepcopy(dict(job)))
        else:
            projected.update(copy.deepcopy(dict(job)))
        self._collections["progress_events"].append(copy.deepcopy(dict(event)))
        if job.get("kind") == "HOLDOUT":
            audit = _holdout_queued_audit(job, event)
            existing_audit = self._find_mutable("audit_findings", {"_id": audit["_id"]})
            if existing_audit is None:
                self._collections["audit_findings"].append(audit)

    def _find_mutable(
        self, collection: str, equals: Mapping[str, object]
    ) -> dict[str, object] | None:
        for document in self._collections[collection]:
            if _matches_equals(document, equals):
                return document
        return None

    def _assert_unique_id(self, collection: str, identifier: str) -> None:
        if self._find_mutable(collection, {"_id": identifier}) is not None:
            raise ValueError(f"duplicate _id in {collection}: {identifier}")

    @staticmethod
    def _matches_ranges(
        document: Mapping[str, object], ranges: Mapping[str, tuple[str, object]]
    ) -> bool:
        for field, (operator, expected) in ranges.items():
            value = cast(Any, document.get(field))
            comparable_expected = cast(Any, expected)
            if value is None:
                return False
            if operator == "gte" and not value >= comparable_expected:
                return False
            if operator == "lte" and not value <= comparable_expected:
                return False
            if operator == "gt" and not value > comparable_expected:
                return False
            if operator == "lt" and not value < comparable_expected:
                return False
        return True

    @staticmethod
    def _require_collection(collection: str) -> None:
        if collection not in QUERY_COLLECTIONS:
            raise ValueError(f"unsupported CLX collection: {collection}")


class MongoClxBacktestStore:
    """Mongo control-plane store; it is hard-bound to the derived database."""

    index_definitions: Mapping[str, Sequence[IndexDefinition]] = INDEX_DEFINITIONS

    def __init__(
        self, database: Any | None = None, *, create_indexes: bool = True
    ) -> None:
        if database is None:
            from freshquant.db import get_db

            database = get_db(DERIVED_DATABASE_NAME)
        database_name = getattr(database, "name", DERIVED_DATABASE_NAME)
        if database_name != DERIVED_DATABASE_NAME:
            raise ValueError(f"CLX API requires database {DERIVED_DATABASE_NAME}")
        self._db = database
        if create_indexes:
            self.ensure_indexes()

    def ensure_indexes(self) -> None:
        for collection, definitions in self.index_definitions.items():
            for definition in definitions:
                self._db[collection].create_index(
                    list(definition.keys),
                    name=definition.name,
                    unique=definition.unique,
                    background=True,
                )

    def ping(self) -> bool:
        return bool(self._db.client.admin.command("ping").get("ok"))

    def create_run(self, document: Mapping[str, object]) -> dict[str, object]:
        return self.insert_document("runs", document)

    def get_one(
        self, collection: str, equals: Mapping[str, object]
    ) -> dict[str, object] | None:
        self._require_collection(collection)
        return _copy(self._db[collection].find_one(dict(equals)))

    def find_many(
        self,
        collection: str,
        *,
        equals: Mapping[str, object],
        ranges: Mapping[str, tuple[str, object]] | None,
        sort: Sequence[tuple[str, int]],
        limit: int,
        after: Sequence[object] | None,
    ) -> list[dict[str, object]]:
        self._require_collection(collection)
        query: dict[str, object] = dict(equals)
        for field, (operator, value) in (ranges or {}).items():
            query[field] = {f"${operator}": value}
        if after is not None:
            clauses: list[dict[str, object]] = []
            for index, ((field, direction), cursor_value) in enumerate(
                zip(sort, after, strict=True)
            ):
                clause = {
                    prior_field: after[prior_index]
                    for prior_index, (prior_field, _) in enumerate(sort[:index])
                }
                clause[field] = {"$gt" if direction > 0 else "$lt": cursor_value}
                clauses.append(clause)
            query["$or"] = clauses
        cursor = self._db[collection].find(query).sort(list(sort)).limit(limit)
        return [copy.deepcopy(document) for document in cursor]

    def start_run(
        self, run_id: str, expected_hash: str, *, now: str, job_id: str
    ) -> dict[str, object]:
        from pymongo import ReturnDocument

        job = {
            "_id": job_id,
            "job_id": job_id,
            "run_id": run_id,
            "kind": "BACKTEST",
            "status": "QUEUED",
            "execution_mode": "EXTERNAL_WORKER",
            "progress": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        event = _control_event(run_id, job_id, "RUN_QUEUED", now, 0.0)
        run = self._db.runs.find_one_and_update(
            {"_id": run_id, "status": "DRAFT", "config_sha256": expected_hash},
            {
                "$set": {
                    "status": "QUEUED",
                    "active_job_id": job_id,
                    "active_job": copy.deepcopy(job),
                    "started_at": now,
                    "updated_at": now,
                    "last_control_event": copy.deepcopy(event),
                    "projection_pending": True,
                },
                "$push": {"control_events": copy.deepcopy(event)},
            },
            return_document=ReturnDocument.AFTER,
        )
        if run is None:
            current = self._db.runs.find_one({"_id": run_id})
            if current is None:
                return {"reason": "NOT_FOUND"}
            reason = (
                "CONFIG_HASH_MISMATCH"
                if current.get("config_sha256") != expected_hash
                else "INVALID_STATE"
            )
            return {"reason": reason, "run": _copy(current)}
        try:
            self._project_control(job, event)
        except Exception:
            LOGGER.exception("CLX start projections require reconciliation")
        else:
            try:
                cleared = self._clear_projection_pending(run_id, event["_id"])
            except Exception:
                LOGGER.exception("CLX start projection marker requires reconciliation")
            else:
                if cleared:
                    run["projection_pending"] = False
        return {"reason": "OK", "run": _copy(run), "job": _copy(job)}

    def cancel_run(
        self, run_id: str, *, now: str, reason: str | None
    ) -> dict[str, object]:
        from pymongo import ReturnDocument

        current = self._db.runs.find_one(
            {"_id": run_id}, {"active_job_id": 1, "projection_pending": 1}
        )
        current_job_id = str((current or {}).get("active_job_id", ""))
        prior_projection_pending = bool((current or {}).get("projection_pending"))
        event = _control_event(
            run_id, current_job_id or None, "CANCEL_REQUESTED", now, None
        )
        run = self._db.runs.find_one_and_update(
            {"_id": run_id, "status": {"$in": ["QUEUED", "RUNNING"]}},
            {
                "$set": {
                    "status": "CANCEL_REQUESTED",
                    "cancel_requested_at": now,
                    "updated_at": now,
                    "active_job._id": current_job_id,
                    "active_job.job_id": current_job_id,
                    "active_job.run_id": run_id,
                    "active_job.kind": "BACKTEST",
                    "active_job.execution_mode": "EXTERNAL_WORKER",
                    "active_job.status": "CANCEL_REQUESTED",
                    "active_job.cancel_reason": reason,
                    "active_job.updated_at": now,
                    "last_control_event": copy.deepcopy(event),
                    "projection_pending": True,
                },
                "$push": {"control_events": copy.deepcopy(event)},
            },
            return_document=ReturnDocument.AFTER,
        )
        if run is None:
            current = self._db.runs.find_one({"_id": run_id})
            return {
                "reason": "NOT_FOUND" if current is None else "INVALID_STATE",
                "run": _copy(current),
            }
        embedded = run.get("active_job")
        job = copy.deepcopy(dict(embedded)) if isinstance(embedded, Mapping) else None
        if job is not None:
            try:
                self._project_control(job, event)
            except Exception:
                LOGGER.exception("CLX cancel projections require reconciliation")
            else:
                if not prior_projection_pending:
                    try:
                        cleared = self._clear_projection_pending(run_id, event["_id"])
                    except Exception:
                        LOGGER.exception(
                            "CLX cancel projection marker requires reconciliation"
                        )
                    else:
                        if cleared:
                            run["projection_pending"] = False
        return {"reason": "OK", "run": _copy(run), "job": _copy(job)}

    def create_freeze(
        self, document: Mapping[str, object]
    ) -> tuple[dict[str, object], bool]:
        from pymongo.errors import DuplicateKeyError

        try:
            self._db.freeze_records.insert_one(copy.deepcopy(dict(document)))
            return _copy(document) or {}, True
        except DuplicateKeyError:
            current = self._db.freeze_records.find_one({"run_id": document["run_id"]})
            return _copy(current) or {}, False

    def reveal_holdout(
        self, run_id: str, freeze_id: str, *, now: str, job_id: str
    ) -> dict[str, object]:
        from pymongo import ReturnDocument

        job = {
            "_id": job_id,
            "job_id": job_id,
            "run_id": run_id,
            "freeze_id": freeze_id,
            "kind": "HOLDOUT",
            "status": "QUEUED",
            "execution_mode": "EXTERNAL_WORKER",
            "progress": 0.0,
            "created_at": now,
            "updated_at": now,
        }
        event = _control_event(run_id, job_id, "HOLDOUT_QUEUED", now, 0.0)
        record = self._db.freeze_records.find_one_and_update(
            {
                "run_id": run_id,
                "freeze_id": freeze_id,
                "state": "FROZEN",
                "reveal_count": 0,
                "holdout_revealed_at": None,
            },
            {
                "$set": {
                    "state": "REVEALING",
                    "holdout_reveal_requested_at": now,
                    "holdout_job_id": job_id,
                    "holdout_job": copy.deepcopy(job),
                    "last_control_event": copy.deepcopy(event),
                    "projection_pending": True,
                    "updated_at": now,
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if record is not None:
            try:
                self._project_control(job, event)
            except Exception:
                LOGGER.exception("CLX HOLDOUT projections require reconciliation")
            else:
                cleared = self._db.freeze_records.update_one(
                    {
                        "_id": record["_id"],
                        "last_control_event._id": event["_id"],
                    },
                    {"$set": {"projection_pending": False}},
                )
                if cleared.matched_count == 1:
                    record["projection_pending"] = False
            return {"reason": "OK", "freeze": _copy(record)}
        current = self._db.freeze_records.find_one(
            {"run_id": run_id, "freeze_id": freeze_id}
        )
        if current is None:
            reason = "NOT_FOUND"
        elif current.get("state") == "REVEALED" and current.get("reveal_count") == 1:
            reason = "ALREADY_REVEALED"
        elif current.get("state") == "REVEAL_FAILED":
            reason = "REVEAL_FAILED"
        else:
            reason = "ALREADY_REQUESTED"
        return {"reason": reason, "freeze": _copy(current)}

    def holdout_revealed(self, run_id: str) -> bool:
        return (
            self._db.freeze_records.find_one(
                {"run_id": run_id, "state": "REVEALED", "reveal_count": 1},
                {"_id": 1},
            )
            is not None
        )

    def insert_document(
        self, collection: str, document: Mapping[str, object]
    ) -> dict[str, object]:
        from pymongo.errors import DuplicateKeyError

        self._require_collection(collection)
        created = copy.deepcopy(dict(document))
        created.setdefault("_id", new_ulid())
        try:
            self._db[collection].insert_one(created)
        except DuplicateKeyError as exc:
            raise ValueError(f"duplicate document in {collection}") from exc
        return _copy(created) or {}

    def _project_control(
        self, job: Mapping[str, object], event: Mapping[str, object]
    ) -> None:
        job_document = copy.deepcopy(dict(job))
        job_id = job_document.pop("_id")
        self._db.jobs.update_one(
            {"_id": job_id},
            {"$set": job_document},
            upsert=True,
        )
        self._db.progress_events.update_one(
            {"_id": event["_id"]},
            {"$setOnInsert": copy.deepcopy(dict(event))},
            upsert=True,
        )
        if job.get("kind") == "HOLDOUT":
            audit = _holdout_queued_audit(job, event)
            self._db.audit_findings.update_one(
                {"_id": audit["_id"]},
                {"$setOnInsert": audit},
                upsert=True,
            )

    def _clear_projection_pending(self, run_id: str, event_id: object) -> bool:
        result = self._db.runs.update_one(
            {"_id": run_id, "last_control_event._id": event_id},
            {"$set": {"projection_pending": False}},
        )
        return bool(result.matched_count == 1)

    @staticmethod
    def _require_collection(collection: str) -> None:
        if collection not in QUERY_COLLECTIONS:
            raise ValueError(f"unsupported CLX collection: {collection}")
