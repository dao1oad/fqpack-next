from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Mapping, Sequence

from .errors import ApiError, conflict, not_found
from .store import ClxBacktestStore
from .utils import (
    canonical_json,
    content_hash,
    decode_cursor,
    encode_cursor,
    new_ulid,
    utc_now,
)

RUN_STATUSES = frozenset(
    {
        "DRAFT",
        "QUEUED",
        "RUNNING",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "FAILED",
        "COMPLETE",
    }
)


@dataclass(slots=True)
class Page:
    items: list[dict[str, object]]
    next_cursor: str | None


def frozen_rank_digest(
    run_id: str, rank_order: Sequence[str], ranking_config_sha256: str
) -> str:
    return content_hash(
        {
            "run_id": run_id,
            "split_id": "VALIDATION",
            "rank_order": list(rank_order),
            "ranking_config_sha256": ranking_config_sha256,
        }
    )


class ClxBacktestService:
    def __init__(self, store: ClxBacktestStore) -> None:
        self.store = store

    def create_run(
        self,
        *,
        name: str,
        config: Mapping[str, object],
        lineage: Mapping[str, object],
        cloned_from: str | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        run_id = new_ulid()
        immutable_config = copy.deepcopy(dict(config))
        document: dict[str, object] = {
            "_id": run_id,
            "run_id": run_id,
            "name": name,
            "status": "DRAFT",
            "config": immutable_config,
            "config_sha256": content_hash(immutable_config),
            "lineage": copy.deepcopy(dict(lineage)),
            "created_at": now,
            "updated_at": now,
        }
        if cloned_from is not None:
            document["cloned_from"] = cloned_from
        return self.store.create_run(document)

    def clone_run(
        self,
        source_run_id: str,
        *,
        name: str | None,
        config: Mapping[str, object] | None,
    ) -> dict[str, object]:
        source = self.require_run(source_run_id)
        source_config = source.get("config", {})
        source_lineage = source.get("lineage", {})
        if not isinstance(source_config, Mapping):
            source_config = {}
        if not isinstance(source_lineage, Mapping):
            source_lineage = {}
        return self.create_run(
            name=name or f"{source.get('name', source_run_id)} (clone)",
            config=config if config is not None else source_config,
            lineage=source_lineage,
            cloned_from=source_run_id,
        )

    def require_run(self, run_id: str) -> dict[str, object]:
        run = self.store.get_one("runs", {"_id": run_id})
        if run is None:
            raise not_found("run", run_id)
        return run

    def list_runs(
        self, *, status: str | None, page_size: int, cursor: str | None
    ) -> Page:
        equals: dict[str, object] = {}
        if status is not None:
            if status not in RUN_STATUSES:
                raise ApiError(
                    "INVALID_FILTER", "status is invalid", 400, {"field": "status"}
                )
            equals["status"] = status
        return self.page_collection(
            "runs",
            kind="runs",
            equals=equals,
            sort=(("created_at", -1), ("_id", 1)),
            page_size=page_size,
            cursor=cursor,
        )

    def start_run(self, run_id: str, expected_hash: str | None) -> dict[str, object]:
        run = self.require_run(run_id)
        current_hash = str(run["config_sha256"])
        if expected_hash is not None and expected_hash != current_hash:
            raise conflict(
                "CONFIG_HASH_MISMATCH",
                "The supplied config hash does not match the immutable run config",
                expected=current_hash,
                supplied=expected_hash,
            )
        result = self.store.start_run(
            run_id,
            current_hash,
            now=utc_now(),
            job_id=new_ulid(),
        )
        reason = result["reason"]
        if reason == "NOT_FOUND":
            raise not_found("run", run_id)
        if reason == "CONFIG_HASH_MISMATCH":
            raise conflict(
                "CONFIG_HASH_MISMATCH",
                "Run config changed while start was attempted",
                run_id=run_id,
            )
        if reason != "OK":
            current = result.get("run", {})
            status = current.get("status") if isinstance(current, Mapping) else None
            raise conflict(
                "INVALID_RUN_STATE",
                "Run can only be started from DRAFT",
                run_id=run_id,
                status=status,
            )
        return {"run": result["run"], "job": result["job"]}

    def cancel_run(self, run_id: str, reason: str | None) -> dict[str, object]:
        result = self.store.cancel_run(run_id, now=utc_now(), reason=reason)
        if result["reason"] == "NOT_FOUND":
            raise not_found("run", run_id)
        if result["reason"] != "OK":
            current = result.get("run", {})
            status = current.get("status") if isinstance(current, Mapping) else None
            raise conflict(
                "INVALID_RUN_STATE",
                "Run can only be cancelled from QUEUED or RUNNING",
                run_id=run_id,
                status=status,
            )
        return {"run": result["run"], "job": result.get("job")}

    def freeze(
        self, run_id: str, specification: Mapping[str, object]
    ) -> tuple[dict[str, object], bool]:
        run = self.require_run(run_id)
        if run.get("status") != "COMPLETE":
            raise conflict(
                "INVALID_RUN_STATE",
                "Only a COMPLETE run can be frozen",
                run_id=run_id,
                status=run.get("status"),
            )
        manifest = self.store.get_one("manifests", {"run_id": run_id})
        if manifest is None or manifest.get("state") != "COMPLETE":
            raise conflict(
                "MANIFEST_NOT_READY",
                "A COMPLETE derived manifest is required before freezing",
                run_id=run_id,
            )
        freeze_input = manifest.get("freeze_input")
        if not isinstance(freeze_input, Mapping):
            raise conflict(
                "MANIFEST_NOT_READY",
                "The derived manifest has no server-published freeze input",
                run_id=run_id,
            )
        server_specification = copy.deepcopy(dict(freeze_input))
        if canonical_json(specification) != canonical_json(server_specification):
            raise conflict(
                "FREEZE_SOURCE_MISMATCH",
                "Freeze input does not match the server-published manifest",
                run_id=run_id,
            )
        manifest_config = manifest.get("config")
        expected_split_hash = (
            manifest_config.get("split_config_sha256")
            if isinstance(manifest_config, Mapping)
            else None
        )
        supplied_split_hash = server_specification["split_config_sha256"]
        if expected_split_hash != supplied_split_hash:
            raise conflict(
                "FREEZE_SOURCE_MISMATCH",
                "split_config_sha256 does not match the derived manifest",
                run_id=run_id,
            )

        validation = server_specification["validation"]
        ranking_config = server_specification["ranking_config"]
        if not isinstance(validation, Mapping) or not isinstance(
            ranking_config, Mapping
        ):
            raise conflict(
                "FREEZE_SOURCE_MISMATCH",
                "Freeze validation material is invalid",
                run_id=run_id,
            )
        rank_order = list(validation["rank_order"])
        ranking_config_sha256 = content_hash(ranking_config)
        for frozen_rank, combo_id in enumerate(rank_order, start=1):
            definition = self.store.get_one(
                "combo_definitions", {"run_id": run_id, "combo_id": combo_id}
            )
            metric = self.store.get_one(
                "combo_metrics",
                {
                    "run_id": run_id,
                    "combo_id": combo_id,
                    "split_id": "VALIDATION",
                    "frozen_rank": frozen_rank,
                    "ranking_config_sha256": ranking_config_sha256,
                },
            )
            if definition is None or metric is None:
                raise conflict(
                    "FREEZE_SOURCE_MISMATCH",
                    "rank_order contains a combo without VALIDATION facts",
                    run_id=run_id,
                    combo_id=combo_id,
                )
        expected_rank_digest = frozen_rank_digest(
            run_id, rank_order, ranking_config_sha256
        )
        if server_specification["frozen_rank_digest"] != expected_rank_digest:
            raise conflict(
                "FREEZE_SOURCE_MISMATCH",
                "frozen_rank_digest does not match VALIDATION facts",
                run_id=run_id,
            )
        freeze_material = {
            "run_id": run_id,
            "run_config_sha256": run["config_sha256"],
            "specification": server_specification,
        }
        freeze_id = content_hash(freeze_material)
        document = {
            "_id": f"{run_id}:{freeze_id.removeprefix('sha256:')}",
            "run_id": run_id,
            "freeze_id": freeze_id,
            **freeze_material,
            "created_at": utc_now(),
            "state": "FROZEN",
            "holdout_revealed_at": None,
            "reveal_count": 0,
        }
        record, created = self.store.create_freeze(document)
        if record.get("freeze_id") != freeze_id:
            raise conflict(
                "RUN_ALREADY_FROZEN",
                "Run already has a different immutable freeze",
                run_id=run_id,
                freeze_id=record.get("freeze_id"),
            )
        return record, created

    def reveal_holdout(self, run_id: str, freeze_id: str) -> dict[str, object]:
        self.require_run(run_id)
        now = utc_now()
        result = self.store.reveal_holdout(
            run_id, freeze_id, now=now, job_id=new_ulid()
        )
        if result["reason"] == "NOT_FOUND":
            raise not_found("freeze", freeze_id)
        if result["reason"] == "ALREADY_REVEALED":
            raise conflict(
                "HOLDOUT_ALREADY_REVEALED",
                "HOLDOUT has already been revealed for this freeze",
                run_id=run_id,
                freeze_id=freeze_id,
            )
        if result["reason"] == "REVEAL_FAILED":
            raise conflict(
                "HOLDOUT_REVEAL_FAILED",
                "The reserved HOLDOUT reveal failed and requires operator inspection",
                run_id=run_id,
                freeze_id=freeze_id,
            )
        if result["reason"] != "OK":
            raise conflict(
                "HOLDOUT_REVEAL_IN_PROGRESS",
                "A HOLDOUT reveal job has already been reserved for this freeze",
                run_id=run_id,
                freeze_id=freeze_id,
            )
        freeze = result["freeze"]
        assert isinstance(freeze, Mapping)
        return copy.deepcopy(dict(freeze))

    def require_holdout_access(self, run_id: str) -> dict[str, object]:
        record = self.store.get_one(
            "freeze_records",
            {"run_id": run_id, "state": "REVEALED", "reveal_count": 1},
        )
        if record is not None:
            return record
        self.audit(
            run_id,
            kind="HOLDOUT_ACCESS_DENIED",
            severity="WARNING",
            status="OPEN",
            details={},
        )
        raise ApiError(
            "HOLDOUT_LOCKED",
            "HOLDOUT data is locked until a frozen rule is revealed",
            423,
            {"run_id": run_id},
        )

    def audit(
        self,
        run_id: str,
        *,
        kind: str,
        severity: str,
        status: str,
        details: Mapping[str, object],
    ) -> dict[str, object]:
        audit_id = new_ulid()
        return self.store.insert_document(
            "audit_findings",
            {
                "_id": audit_id,
                "finding_id": audit_id,
                "run_id": run_id,
                "kind": kind,
                "severity": severity,
                "status": status,
                "details": copy.deepcopy(dict(details)),
                "created_at": utc_now(),
            },
        )

    def create_export(
        self,
        run_id: str,
        *,
        resource: str,
        file_format: str,
        combo_ids: Sequence[str],
        split_id: str,
    ) -> dict[str, object]:
        self.require_run(run_id)
        holdout_access: dict[str, object] | None = None
        if split_id == "HOLDOUT":
            freeze = self.require_holdout_access(run_id)
            holdout_access = {
                "freeze_id": freeze["freeze_id"],
                "holdout_revealed_at": freeze["holdout_revealed_at"],
                "reveal_count": freeze["reveal_count"],
            }
        now = utc_now()
        job_id = new_ulid()
        document: dict[str, object] = {
            "_id": job_id,
            "job_id": job_id,
            "run_id": run_id,
            "kind": "EXPORT",
            "status": "QUEUED",
            "execution_mode": "EXTERNAL_WORKER",
            "resource": resource,
            "format": file_format,
            "combo_ids": list(combo_ids),
            "split_id": split_id,
            "artifact_key": f"exports/{run_id}/{job_id}.{file_format}",
            "created_at": now,
            "updated_at": now,
        }
        if holdout_access is not None:
            document["holdout_access"] = holdout_access
        return self.store.insert_document("jobs", document)

    def page_collection(
        self,
        collection: str,
        *,
        kind: str,
        equals: Mapping[str, object],
        sort: Sequence[tuple[str, int]],
        page_size: int,
        cursor: str | None,
        ranges: Mapping[str, tuple[str, object]] | None = None,
    ) -> Page:
        filter_kind = (
            f"{kind}:{content_hash({'equals': equals, 'ranges': ranges or {}})}"
        )
        after = decode_cursor(cursor, kind=filter_kind, length=len(sort))
        documents = self.store.find_many(
            collection,
            equals=equals,
            ranges=ranges,
            sort=sort,
            limit=page_size + 1,
            after=after,
        )
        has_more = len(documents) > page_size
        items = documents[:page_size]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = encode_cursor(
                filter_kind, [last.get(field) for field, _ in sort]
            )
        return Page(items, next_cursor)
