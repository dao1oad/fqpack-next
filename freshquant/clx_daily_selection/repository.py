from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable

from pymongo.errors import DuplicateKeyError

from freshquant.db import MongoClient

from .contracts import canonical_hash

DATABASE_NAME = "freshquant_clx_daily_selection"
LINE_FLAG_KEYS = frozenset(
    {"above_ma250", "above_chanlun_line", "above_reference_line"}
)
LINE_FLAG_VALUES = frozenset({"yes", "no", "unknown"})
DIRECTION_MODES = ("pure_buy", "pure_sell", "mixed", "no_signal", "all")
PUBLISHED_FINAL_QUERY = {
    "is_final": True,
    "publication.status": {"$in": ["published", "not_required"]},
}
COMPLETED_PARTITION_QUERY = {
    "status": "completed",
    "commit_result.status": "completed",
}


def classify_direction_mode(directions) -> str:
    """把快照 directions 归一到业务方向口径。

    - pure_buy: 规范化去重后恰好只有 buy（不含 sell）
    - pure_sell: 恰好只有 sell
    - mixed: 同时包含 buy 与 sell
    - no_signal: 无 buy/sell；未知方向值（如 hold/空白）不参与判定，
      只保留 buy/sell 后再分类，未知值本身不会造成 mixed 误判。
    """
    normalized = sorted(
        {
            str(item or "").strip()
            for item in (directions or [])
            if str(item or "").strip() in {"buy", "sell"}
        }
    )
    if not normalized:
        return "no_signal"
    if normalized == ["buy"]:
        return "pure_buy"
    if normalized == ["sell"]:
        return "pure_sell"
    return "mixed"


class ClxDailySelectionRepository:
    def __init__(self, database=None) -> None:
        self.database = database if database is not None else MongoClient[DATABASE_NAME]
        self.attempts = self.database["partition_attempts"]
        self.partitions = self.database["partitions"]
        self.memberships = self.database["memberships"]
        self.snapshots = self.database["snapshots"]
        self.model_stats = self.database["model_stats"]
        self.batch_statuses = self.database["batch_statuses"]
        self.finalization_attempts = self.database["finalization_attempts"]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.attempts.create_index(
            [("selection_key", 1), ("attempt_no", 1)],
            unique=True,
            name="uniq_selection_attempt",
        )
        self.attempts.create_index(
            [("trade_date", -1), ("asset_type", 1), ("attempt_no", -1)],
            name="attempt_status_lookup",
        )
        self.partitions.create_index(
            [("selection_key", 1)], unique=True, name="uniq_completed_selection"
        )
        self.partitions.create_index(
            [("trade_date", -1), ("asset_type", 1), ("completed_at", -1)],
            name="latest_partition",
        )
        self.memberships.create_index(
            [
                ("partition_id", 1),
                ("asset_type", 1),
                ("symbol", 1),
                ("model_key", 1),
                ("trigger_date", 1),
            ],
            name="partition_membership_lookup",
        )
        self.snapshots.create_index(
            [("partition_id", 1), ("asset_type", 1), ("symbol", 1)],
            unique=True,
            name="uniq_partition_symbol",
        )
        self.model_stats.create_index(
            [("partition_id", 1), ("model_key", 1)],
            unique=True,
            name="uniq_partition_model_stats",
        )
        self.batch_statuses.create_index(
            [("trade_date", -1), ("is_final", -1)], name="batch_latest"
        )
        self.finalization_attempts.create_index(
            [("batch_id", 1), ("attempt_no", 1)],
            unique=True,
            name="uniq_batch_finalization_attempt",
        )
        self.finalization_attempts.create_index(
            [("batch_id", 1), ("status", 1), ("attempt_no", -1)],
            name="active_batch_finalization_attempt",
        )

    def find_completed_partition(self, selection_key: str):
        existing = self._plain(
            self.partitions.find_one(
                {"selection_key": selection_key, **deepcopy(COMPLETED_PARTITION_QUERY)}
            )
        )
        if existing:
            return existing
        authorized_attempt = self.attempts.find_one(
            {
                "selection_key": selection_key,
                "status": "completed",
                "commit_result.status": "completed",
                "commit_result.authoritative_partition": {"$exists": True},
            },
            sort=[("attempt_no", 1)],
        )
        if not authorized_attempt:
            return None
        return self._persist_authoritative_partition(
            authorized_attempt["commit_result"]["authoritative_partition"]
        )

    def find_active_attempt(self, selection_key: str):
        return self._plain(
            self.attempts.find_one(
                {
                    "selection_key": selection_key,
                    "status": {"$in": ["scheduled", "running", "committing"]},
                },
                sort=[("attempt_no", -1)],
            )
        )

    def next_attempt_no(self, selection_key: str) -> int:
        latest = self.attempts.find_one(
            {"selection_key": selection_key}, sort=[("attempt_no", -1)]
        )
        return int((latest or {}).get("attempt_no") or 0) + 1

    def create_attempt(self, document: dict[str, Any]):
        payload = deepcopy(document)
        payload["_id"] = payload["attempt_id"]
        try:
            self.attempts.insert_one(payload)
        except DuplicateKeyError:
            existing = self.attempts.find_one(
                {
                    "selection_key": payload["selection_key"],
                    "attempt_no": payload["attempt_no"],
                }
            )
            if not existing:
                raise
            return self._plain(existing)
        return self._plain(payload)

    def get_attempt(self, attempt_id: str):
        return self._plain(self.attempts.find_one({"_id": attempt_id}))

    def update_attempt(self, attempt_id: str, fields: dict[str, Any]):
        self.attempts.update_one({"_id": attempt_id}, {"$set": deepcopy(fields)})
        return self.get_attempt(attempt_id)

    def update_attempt_if(
        self,
        attempt_id: str,
        *,
        expected: dict[str, Any],
        fields: dict[str, Any],
    ):
        query = {"_id": attempt_id, **deepcopy(expected)}
        result = self.attempts.update_one(query, {"$set": deepcopy(fields)})
        return bool(result.matched_count), self.get_attempt(attempt_id)

    def commit_partition(
        self,
        *,
        attempt_id: str,
        claim_owner: str,
        claim_token: str,
        now: str,
        commit_lease_expires_at: str,
        now_provider: Callable[[], str],
        partition: dict[str, Any],
        memberships: list[dict[str, Any]],
        snapshots: list[dict[str, Any]],
        stats: list[dict[str, Any]],
    ):
        claim = self.attempts.update_one(
            {
                "_id": attempt_id,
                "status": "running",
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "lease_expires_at": {"$gt": now},
            },
            {
                "$set": {
                    "status": "committing",
                    "commit_started_at": now,
                    "lease_expires_at": commit_lease_expires_at,
                }
            },
        )
        if not claim.matched_count:
            recovered = self._recover_authorized_partition(
                attempt_id=attempt_id,
                claim_token=claim_token,
                partition=partition,
            )
            if recovered:
                return recovered
            resumed = self.attempts.update_one(
                {
                    "_id": attempt_id,
                    "status": "committing",
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                    "lease_expires_at": {"$gt": now},
                },
                {"$set": {"commit_resumed_at": now}},
            )
            if not resumed.matched_count:
                raise RuntimeError(f"CLX partition attempt claim lost: {attempt_id}")
        existing = self.find_completed_partition(partition["selection_key"])
        if existing:
            if existing.get("content_hash") != partition.get("content_hash"):
                raise RuntimeError("immutable partition conflict")
            commit_completed_at = str(now_provider())
            completed, _attempt = self.update_attempt_if(
                attempt_id,
                expected={
                    "status": "committing",
                    "claim_owner": claim_owner,
                    "claim_token": claim_token,
                    "lease_expires_at": {"$gt": commit_completed_at},
                },
                fields={
                    "status": "completed",
                    "partition_id": existing["partition_id"],
                    "finished_at": commit_completed_at,
                    "lease_expires_at": None,
                    "commit_result": self._attempt_commit_result(
                        existing,
                        claim_token=claim_token,
                        completed_at=commit_completed_at,
                    ),
                },
            )
            if not completed:
                raise RuntimeError(f"CLX partition completion claim lost: {attempt_id}")
            return existing
        self._insert_immutable_rows(
            self.memberships, partition["partition_id"], memberships
        )
        self._insert_immutable_rows(
            self.snapshots, partition["partition_id"], snapshots
        )
        self._insert_immutable_rows(self.model_stats, partition["partition_id"], stats)
        commit_completed_at = str(now_provider())
        payload = self._authoritative_partition_payload(
            partition,
            attempt_id=attempt_id,
            claim_token=claim_token,
            completed_at=commit_completed_at,
        )
        completed = self.attempts.update_one(
            {
                "_id": attempt_id,
                "status": "committing",
                "claim_owner": claim_owner,
                "claim_token": claim_token,
                "lease_expires_at": {"$gt": commit_completed_at},
            },
            {
                "$set": {
                    "status": "completed",
                    "partition_id": partition["partition_id"],
                    "finished_at": commit_completed_at,
                    "lease_expires_at": None,
                    "commit_result": self._attempt_commit_result(
                        payload,
                        claim_token=claim_token,
                        completed_at=commit_completed_at,
                    ),
                }
            },
        )
        if not completed.matched_count:
            raise RuntimeError(f"CLX partition completion claim lost: {attempt_id}")
        return self._persist_authoritative_partition(payload)

    def _recover_authorized_partition(
        self,
        *,
        attempt_id: str,
        claim_token: str,
        partition: dict[str, Any],
    ):
        attempt = self.attempts.find_one(
            {
                "_id": attempt_id,
                "status": "completed",
                "commit_result.status": "completed",
                "commit_result.authoritative_partition": {"$exists": True},
            }
        )
        if not attempt:
            return None
        commit_result = dict(attempt.get("commit_result") or {})
        if commit_result.get("claim_token") != claim_token:
            raise RuntimeError(f"CLX partition attempt claim lost: {attempt_id}")
        authorized = dict(commit_result.get("authoritative_partition") or {})
        if any(
            authorized.get(field) != partition.get(field)
            for field in ("selection_key", "partition_id", "content_hash")
        ):
            raise RuntimeError("immutable partition conflict")
        return self._persist_authoritative_partition(authorized)

    def _authoritative_partition_payload(
        self,
        partition: dict[str, Any],
        *,
        attempt_id: str,
        claim_token: str,
        completed_at: str,
    ) -> dict[str, Any]:
        payload = deepcopy(partition)
        payload["commit_result"] = {
            "status": "completed",
            "attempt_id": attempt_id,
            "claim_token": claim_token,
            "completed_at": completed_at,
        }
        return payload

    def _attempt_commit_result(
        self,
        authoritative_partition: dict[str, Any],
        *,
        claim_token: str,
        completed_at: str,
    ) -> dict[str, Any]:
        payload = self._plain(authoritative_partition)
        return {
            "status": "completed",
            "partition_id": payload["partition_id"],
            "selection_key": payload["selection_key"],
            "content_hash": payload["content_hash"],
            "claim_token": claim_token,
            "completed_at": completed_at,
            "authoritative_partition": payload,
        }

    def _persist_authoritative_partition(self, partition: dict[str, Any]):
        payload = deepcopy(partition)
        payload["_id"] = payload["partition_id"]
        try:
            self.partitions.insert_one(payload)
        except DuplicateKeyError:
            existing_document = self.partitions.find_one(
                {"selection_key": payload["selection_key"]}
            )
            if not existing_document:
                raise RuntimeError("immutable partition conflict")
            existing = self._plain(existing_document)
            if all(
                existing.get(field) == payload.get(field)
                for field in ("selection_key", "partition_id", "content_hash")
            ) and self._partition_is_completed(existing):
                return existing
            if self._partition_is_completed(existing):
                raise RuntimeError("immutable partition conflict")
            replacement = deepcopy(payload)
            replacement["_id"] = existing_document["_id"]
            replaced = self.partitions.replace_one(
                {
                    "selection_key": partition["selection_key"],
                    "commit_result.status": {"$ne": "completed"},
                },
                replacement,
            )
            if not replaced.matched_count:
                raise RuntimeError("immutable partition conflict")
        return self._plain(payload)

    @staticmethod
    def _partition_is_completed(partition: dict[str, Any]) -> bool:
        return (
            partition.get("status") == "completed"
            and (partition.get("commit_result") or {}).get("status") == "completed"
        )

    def find_active_finalization_attempt(self, batch_id: str):
        return self._plain(
            self.finalization_attempts.find_one(
                {
                    "batch_id": batch_id,
                    "status": {"$in": ["scheduled", "running"]},
                },
                sort=[("attempt_no", -1)],
            )
        )

    def next_finalization_attempt_no(self, batch_id: str) -> int:
        latest = self.finalization_attempts.find_one(
            {"batch_id": batch_id}, sort=[("attempt_no", -1)]
        )
        return int((latest or {}).get("attempt_no") or 0) + 1

    def create_finalization_attempt(self, document: dict[str, Any]):
        payload = deepcopy(document)
        payload["_id"] = payload["finalization_attempt_id"]
        try:
            self.finalization_attempts.insert_one(payload)
        except DuplicateKeyError:
            existing = self.finalization_attempts.find_one(
                {
                    "batch_id": payload["batch_id"],
                    "attempt_no": payload["attempt_no"],
                }
            )
            if not existing:
                raise
            return self._plain(existing)
        return self._plain(payload)

    def get_finalization_attempt(self, finalization_attempt_id: str):
        return self._plain(
            self.finalization_attempts.find_one({"_id": finalization_attempt_id})
        )

    def update_finalization_attempt_if(
        self,
        finalization_attempt_id: str,
        *,
        expected: dict[str, Any],
        fields: dict[str, Any],
    ):
        query = {"_id": finalization_attempt_id, **deepcopy(expected)}
        result = self.finalization_attempts.update_one(
            query, {"$set": deepcopy(fields)}
        )
        return bool(result.matched_count), self.get_finalization_attempt(
            finalization_attempt_id
        )

    def latest_partition(self, trade_date: str, asset_type: str, profile_id: str):
        return self._plain(
            self.partitions.find_one(
                {
                    "trade_date": trade_date,
                    "asset_type": asset_type,
                    "evaluation_profile_id": profile_id,
                    **deepcopy(COMPLETED_PARTITION_QUERY),
                },
                sort=[
                    ("marker_snapshot.document_updated_at", -1),
                    ("completed_at", -1),
                ],
            )
        )

    def latest_attempt(self, trade_date: str, asset_type: str, profile_id: str):
        return self._plain(
            self.attempts.find_one(
                {
                    "trade_date": trade_date,
                    "asset_type": asset_type,
                    "evaluation_profile_id": profile_id,
                },
                sort=[
                    ("marker_snapshot.document_updated_at", -1),
                    ("scheduled_at", -1),
                    ("started_at", -1),
                    ("attempt_no", -1),
                ],
            )
        )

    def upsert_batch_status(self, document: dict[str, Any]):
        batch_id = document["batch_id"]
        payload = deepcopy(document)
        payload["_id"] = batch_id
        try:
            self.batch_statuses.replace_one(
                {"_id": batch_id, "is_final": {"$ne": True}},
                payload,
                upsert=True,
            )
        except DuplicateKeyError:
            existing = self.get_batch(batch_id)
            if not existing:
                raise
            if document.get("is_final") and existing.get(
                "content_hash"
            ) != document.get("content_hash"):
                raise RuntimeError("immutable final batch conflict")
            if existing.get("is_final"):
                return existing
            raise
        stored = self.get_batch(batch_id)
        return stored or self._plain(payload)

    def update_batch_publication(
        self, batch_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        updates = {
            f"publication.{key}": deepcopy(value) for key, value in fields.items()
        }
        result = self.batch_statuses.update_one(
            {"_id": batch_id, "is_final": True}, {"$set": updates}
        )
        if not result.matched_count:
            raise RuntimeError(f"final CLX batch not found: {batch_id}")
        return self.get_batch(batch_id)

    def update_batch_publication_if(
        self,
        batch_id: str,
        *,
        expected: dict[str, Any],
        fields: dict[str, Any],
    ):
        query = {"_id": batch_id, "is_final": True}
        query.update(
            {f"publication.{key}": deepcopy(value) for key, value in expected.items()}
        )
        updates = {
            f"publication.{key}": deepcopy(value) for key, value in fields.items()
        }
        result = self.batch_statuses.update_one(query, {"$set": updates})
        return bool(result.matched_count), self.get_batch(batch_id)

    def get_batch(self, batch_id: str):
        return self._plain(self.batch_statuses.find_one({"_id": batch_id}))

    def list_batches(
        self, *, limit: int, include_partial: bool
    ) -> list[dict[str, Any]]:
        query = {} if include_partial else deepcopy(PUBLISHED_FINAL_QUERY)
        return [
            self._plain(item)
            for item in self.batch_statuses.find(query)
            .sort([("trade_date", -1), ("updated_at", -1)])
            .limit(limit)
        ]

    def latest_batch(self, *, include_partial: bool):
        query = {} if include_partial else deepcopy(PUBLISHED_FINAL_QUERY)
        return self._plain(
            self.batch_statuses.find_one(
                query, sort=[("trade_date", -1), ("updated_at", -1)]
            )
        )

    def query_snapshots(
        self, partition_ids: list[str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        for field in ("min_model_count", "cursor", "limit"):
            if isinstance(payload.get(field), (dict, list)):
                raise ValueError(f"{field} must be an integer")
        query: dict[str, Any] = {
            "partition_id": {"$in": partition_ids},
            "distinct_model_count": {
                "$gte": int(payload.get("min_model_count", 1) or 0)
            },
        }
        if payload.get("asset_types"):
            query["asset_type"] = {"$in": list(payload["asset_types"])}
        if payload.get("model_keys"):
            query["model_keys"] = {"$in": list(payload["model_keys"])}
        if payload.get("condition_keys"):
            query["condition_keys"] = {"$in": list(payload["condition_keys"])}
        if payload.get("directions"):
            query["directions"] = {"$in": list(payload["directions"])}
        direction_mode = str(payload.get("direction_mode") or "").strip()
        if direction_mode and direction_mode not in DIRECTION_MODES:
            raise ValueError(
                f"unsupported direction_mode: {direction_mode}; "
                f"expected one of {','.join(DIRECTION_MODES)}"
            )
        line_flags = payload.get("line_flags")
        if line_flags is not None and not isinstance(line_flags, dict):
            raise ValueError("line_flags must be an object")
        for key, value in (line_flags or {}).items():
            if key not in LINE_FLAG_KEYS:
                raise ValueError(f"unsupported line_flags key: {key}")
            if value not in LINE_FLAG_VALUES:
                raise ValueError(f"unsupported line_flags value: {key}={value}")
            query[f"{key}.value"] = value
        q = str(payload.get("q") or "").strip()
        if q:
            pattern = re.escape(q)
            query["$or"] = [
                {"symbol": {"$regex": pattern, "$options": "i"}},
                {"name": {"$regex": pattern, "$options": "i"}},
            ]
        rows = [self._plain(item) for item in self.snapshots.find(query)]
        rows.sort(
            key=lambda item: (
                -int(item.get("distinct_model_count") or 0),
                -int(item.get("distinct_condition_count") or 0),
                str(item.get("symbol") or ""),
            )
        )
        if direction_mode and direction_mode != "all":
            rows = [
                item
                for item in rows
                if classify_direction_mode(item.get("directions")) == direction_mode
            ]
        try:
            offset = max(0, int(str(payload.get("cursor") or "0")))
        except ValueError:
            offset = 0
        limit = max(1, min(200, int(payload.get("limit", 50) or 50)))
        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "rows": page,
            "total": len(rows),
            "next_cursor": str(next_offset) if next_offset < len(rows) else None,
        }

    def get_snapshot(self, partition_ids, asset_type: str, symbol: str):
        return self._plain(
            self.snapshots.find_one(
                {
                    "partition_id": {"$in": partition_ids},
                    "asset_type": asset_type,
                    "symbol": symbol,
                }
            )
        )

    def get_memberships(self, partition_ids, asset_type: str, symbol: str):
        rows = [
            self._plain(item)
            for item in self.memberships.find(
                {
                    "partition_id": {"$in": partition_ids},
                    "asset_type": asset_type,
                    "symbol": symbol,
                }
            )
        ]
        rows.sort(
            key=lambda item: (item.get("model_key", ""), item.get("bar_index", 0))
        )
        return rows

    def get_snapshots(self, partition_ids):
        rows = [
            self._plain(item)
            for item in self.snapshots.find(
                {"partition_id": {"$in": list(partition_ids)}}
            )
        ]
        rows.sort(key=lambda item: (item.get("asset_type", ""), item.get("symbol", "")))
        return rows

    def get_partition_memberships(self, partition_ids):
        rows = [
            self._plain(item)
            for item in self.memberships.find(
                {"partition_id": {"$in": list(partition_ids)}}
            )
        ]
        rows.sort(
            key=lambda item: (
                item.get("asset_type", ""),
                item.get("symbol", ""),
                item.get("model_key", ""),
                item.get("trigger_date", ""),
                item.get("bar_index", 0),
            )
        )
        return rows

    def get_model_stats(self, partition_ids):
        rows = [
            self._plain(item)
            for item in self.model_stats.find({"partition_id": {"$in": partition_ids}})
        ]
        rows.sort(
            key=lambda item: (item.get("asset_type", ""), item.get("model_key", ""))
        )
        return rows

    def _insert_immutable_rows(self, collection, partition_id: str, rows) -> None:
        for row in rows:
            payload = deepcopy(row)
            row_id = canonical_hash([partition_id, payload])
            payload["_id"] = row_id
            collection.update_one(
                {"_id": row_id}, {"$setOnInsert": payload}, upsert=True
            )

    def _plain(self, document):
        if document is None:
            return None
        payload = deepcopy(dict(document))
        payload.pop("_id", None)
        return payload
