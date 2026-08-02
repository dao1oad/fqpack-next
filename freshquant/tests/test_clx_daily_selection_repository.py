from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from freshquant.clx_daily_selection.repository import (
    COMPLETED_PARTITION_QUERY,
    PUBLISHED_FINAL_QUERY,
    ClxDailySelectionRepository,
)


class CapturingCollection:
    def __init__(self, rows=()):
        self.rows = [deepcopy(item) for item in rows]
        self.last_query = None

    def find(self, query):
        self.last_query = deepcopy(query)
        return [deepcopy(item) for item in self.rows]


class CapturingFindOneCollection:
    def __init__(self):
        self.last_query = None
        self.last_sort = None

    def find_one(self, query, sort=None):
        self.last_query = deepcopy(query)
        self.last_sort = deepcopy(sort)


class CapturingBatchCursor:
    def __init__(self):
        self.sort_spec = None
        self.limit_value = None

    def sort(self, spec):
        self.sort_spec = deepcopy(spec)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def __iter__(self):
        return iter(())


class CapturingBatchCollection(CapturingFindOneCollection):
    def __init__(self):
        super().__init__()
        self.cursor = CapturingBatchCursor()

    def find(self, query):
        self.last_query = deepcopy(query)
        return self.cursor


_MISSING = object()


def _get_path(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _set_path(document, path, value):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = deepcopy(value)


def _matches(document, query):
    for field, expected in query.items():
        actual = _get_path(document, field)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gt" in expected and (actual is _MISSING or actual <= expected["$gt"]):
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$exists" in expected and (actual is not _MISSING) is not bool(
                expected["$exists"]
            ):
                return False
            continue
        if actual is _MISSING or actual != expected:
            return False
    return True


class StatefulMongoCollection:
    def __init__(self, name):
        self.name = name
        self.rows = {}
        self.fail_next_insert = None

    def create_index(self, *_args, **_kwargs):
        return None

    def find_one(self, query, sort=None):
        rows = [row for row in self.rows.values() if _matches(row, query)]
        for field, direction in reversed(sort or []):
            rows.sort(
                key=lambda row: (
                    None if _get_path(row, field) is _MISSING else _get_path(row, field)
                ),
                reverse=direction < 0,
            )
        return deepcopy(rows[0]) if rows else None

    def update_one(self, query, update, upsert=False):
        current = self.find_one(query)
        if current is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, upserted_id=None)
            payload = {
                key: deepcopy(value)
                for key, value in query.items()
                if "." not in key and not isinstance(value, dict)
            }
            for field, value in (update.get("$setOnInsert") or {}).items():
                _set_path(payload, field, value)
            for field, value in (update.get("$set") or {}).items():
                _set_path(payload, field, value)
            self.insert_one(payload)
            return SimpleNamespace(matched_count=0, upserted_id=payload["_id"])
        row_id = current["_id"]
        for field, value in (update.get("$set") or {}).items():
            _set_path(current, field, value)
        self.rows[row_id] = current
        return SimpleNamespace(matched_count=1, upserted_id=None)

    def insert_one(self, payload):
        if self.fail_next_insert is not None:
            failure = self.fail_next_insert
            self.fail_next_insert = None
            raise failure
        payload = deepcopy(payload)
        row_id = payload["_id"]
        if row_id in self.rows:
            raise DuplicateKeyError(f"duplicate _id: {row_id}")
        if self.name == "partitions" and any(
            row.get("selection_key") == payload.get("selection_key")
            for row in self.rows.values()
        ):
            raise DuplicateKeyError("duplicate partition selection_key")
        if self.name == "partition_attempts" and any(
            row.get("selection_key") == payload.get("selection_key")
            and row.get("attempt_no") == payload.get("attempt_no")
            for row in self.rows.values()
        ):
            raise DuplicateKeyError("duplicate partition attempt")
        self.rows[row_id] = payload
        return SimpleNamespace(inserted_id=row_id)

    def replace_one(self, query, payload, upsert=False):
        current = self.find_one(query)
        if current is None:
            if not upsert:
                return SimpleNamespace(matched_count=0, upserted_id=None)
            self.insert_one(payload)
            return SimpleNamespace(matched_count=0, upserted_id=payload["_id"])
        self.rows.pop(current["_id"])
        self.rows[payload["_id"]] = deepcopy(payload)
        return SimpleNamespace(matched_count=1, upserted_id=None)


class StatefulMongoDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, StatefulMongoCollection(name))


def _commit_fixture(*, attempt_no=1, content_suffix="a"):
    attempt_id = f"attempt-{attempt_no}"
    claim_token = f"token-{attempt_no}"
    attempt = {
        "attempt_id": attempt_id,
        "attempt_no": attempt_no,
        "selection_key": "selection-stock",
        "status": "running",
        "claim_owner": f"owner-{attempt_no}",
        "claim_token": claim_token,
        "lease_expires_at": "2026-03-19T09:00:00+00:00",
    }
    partition = {
        "partition_id": f"partition-{content_suffix}",
        "attempt_id": attempt_id,
        "attempt_no": attempt_no,
        "selection_key": "selection-stock",
        "status": "completed",
        "trade_date": "2026-03-19",
        "asset_type": "stock",
        "evaluation_profile_id": "production_v1",
        "content_hash": f"content-{content_suffix}",
        "completed_at": "2026-03-19T08:01:00+00:00",
    }
    return attempt, partition


def _commit(repository, attempt, partition, *, now_provider):
    return repository.commit_partition(
        attempt_id=attempt["attempt_id"],
        claim_owner=attempt["claim_owner"],
        claim_token=attempt["claim_token"],
        now="2026-03-19T08:00:00+00:00",
        commit_lease_expires_at="2026-03-19T08:30:00+00:00",
        now_provider=now_provider,
        partition=partition,
        memberships=[{"partition_id": partition["partition_id"], "kind": "member"}],
        snapshots=[{"partition_id": partition["partition_id"], "kind": "snapshot"}],
        stats=[{"partition_id": partition["partition_id"], "kind": "stat"}],
    )


def test_snapshot_query_applies_direction_filter_in_mongo_contract():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection()

    page = repository.query_snapshots(
        ["partition-stock"],
        {
            "directions": ["buy"],
            "min_model_count": 1,
            "limit": 50,
        },
    )

    assert page == {"rows": [], "total": 0, "next_cursor": None}
    assert repository.snapshots.last_query["directions"] == {"$in": ["buy"]}


def test_snapshot_query_applies_exact_tristate_line_filters():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection()

    repository.query_snapshots(
        ["partition-stock"],
        {
            "line_flags": {
                "above_ma250": "yes",
                "above_chanlun_line": "no",
                "above_reference_line": "unknown",
            },
            "limit": 50,
        },
    )

    assert repository.snapshots.last_query["above_ma250.value"] == "yes"
    assert repository.snapshots.last_query["above_chanlun_line.value"] == "no"
    assert repository.snapshots.last_query["above_reference_line.value"] == "unknown"


def test_snapshot_query_empty_line_flags_do_not_change_mongo_contract():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection()

    repository.query_snapshots(
        ["partition-stock"],
        {"line_flags": {}, "limit": 50},
    )

    assert not any(key.startswith("above_") for key in repository.snapshots.last_query)


@pytest.mark.parametrize(
    ("line_flags", "message"),
    [
        ({"above_unknown_line": "yes"}, "unsupported line_flags key"),
        ({"above_ma250": "false"}, "unsupported line_flags value"),
    ],
)
def test_snapshot_query_rejects_invalid_line_flag_contract(line_flags, message):
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection()

    with pytest.raises(ValueError, match=message):
        repository.query_snapshots(
            ["partition-stock"],
            {"line_flags": line_flags, "limit": 50},
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_model_count", {}),
        ("min_model_count", []),
        ("cursor", {}),
        ("cursor", []),
        ("limit", {}),
        ("limit", []),
    ],
)
def test_snapshot_query_rejects_structured_numeric_parameters(field, value):
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection()

    with pytest.raises(ValueError, match=rf"^{field} must be an integer$"):
        repository.query_snapshots(
            ["partition-stock"],
            {field: value},
        )

    assert repository.snapshots.last_query is None


def test_statistics_fact_reads_are_scoped_and_deterministically_sorted():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.snapshots = CapturingCollection(
        [
            {"partition_id": "partition-etf", "asset_type": "etf", "symbol": "510300"},
            {
                "partition_id": "partition-stock",
                "asset_type": "stock",
                "symbol": "000001",
            },
        ]
    )
    repository.memberships = CapturingCollection(
        [
            {
                "partition_id": "partition-stock",
                "asset_type": "stock",
                "symbol": "000001",
                "model_key": "S0002",
                "trigger_date": "2026-03-19",
            },
            {
                "partition_id": "partition-stock",
                "asset_type": "stock",
                "symbol": "000001",
                "model_key": "S0001",
                "trigger_date": "2026-03-19",
            },
        ]
    )

    snapshots = repository.get_snapshots(["partition-stock", "partition-etf"])
    memberships = repository.get_partition_memberships(
        ["partition-stock", "partition-etf"]
    )

    expected_query = {"partition_id": {"$in": ["partition-stock", "partition-etf"]}}
    assert repository.snapshots.last_query == expected_query
    assert repository.memberships.last_query == expected_query
    assert [(row["asset_type"], row["symbol"]) for row in snapshots] == [
        ("etf", "510300"),
        ("stock", "000001"),
    ]
    assert [row["model_key"] for row in memberships] == ["S0001", "S0002"]


def test_latest_partition_and_attempt_prioritize_marker_generation_timestamp():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.partitions = CapturingFindOneCollection()
    repository.attempts = CapturingFindOneCollection()

    repository.latest_partition("2026-03-19", "stock", "production_v1")
    repository.latest_attempt("2026-03-19", "stock", "production_v1")

    assert repository.partitions.last_sort == [
        ("marker_snapshot.document_updated_at", -1),
        ("completed_at", -1),
    ]
    assert repository.attempts.last_sort == [
        ("marker_snapshot.document_updated_at", -1),
        ("scheduled_at", -1),
        ("started_at", -1),
        ("attempt_no", -1),
    ]
    assert repository.partitions.last_query == {
        "trade_date": "2026-03-19",
        "asset_type": "stock",
        "evaluation_profile_id": "production_v1",
        **COMPLETED_PARTITION_QUERY,
    }


def test_completed_partition_read_requires_persisted_commit_result():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.partitions = CapturingFindOneCollection()
    repository.attempts = CapturingFindOneCollection()

    repository.find_completed_partition("selection-stock")

    assert repository.partitions.last_query == {
        "selection_key": "selection-stock",
        **COMPLETED_PARTITION_QUERY,
    }
    assert repository.attempts.last_query == {
        "selection_key": "selection-stock",
        "status": "completed",
        "commit_result.status": "completed",
        "commit_result.authoritative_partition": {"$exists": True},
    }
    assert repository.attempts.last_sort == [("attempt_no", 1)]


def test_commit_retry_recovers_authoritative_partition_after_insert_interruption():
    database = StatefulMongoDatabase()
    repository = ClxDailySelectionRepository(database)
    attempt, partition = _commit_fixture()
    repository.create_attempt(attempt)
    repository.partitions.fail_next_insert = RuntimeError(
        "simulated crash after attempt completion CAS"
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        _commit(
            repository,
            attempt,
            partition,
            now_provider=lambda: "2026-03-19T08:01:00+00:00",
        )

    completed_attempt = repository.get_attempt(attempt["attempt_id"])
    assert completed_attempt["status"] == "completed"
    assert completed_attempt["commit_result"]["content_hash"] == "content-a"
    assert repository.partitions.find_one({"selection_key": "selection-stock"}) is None

    recovered = _commit(
        repository,
        attempt,
        partition,
        now_provider=lambda: "2026-03-19T08:02:00+00:00",
    )

    assert recovered["partition_id"] == "partition-a"
    assert recovered["content_hash"] == "content-a"
    assert repository.find_completed_partition("selection-stock") == recovered
    assert len(repository.memberships.rows) == 1
    assert len(repository.snapshots.rows) == 1
    assert len(repository.model_stats.rows) == 1


def test_durable_commit_authorization_rejects_concurrent_different_content():
    database = StatefulMongoDatabase()
    repository = ClxDailySelectionRepository(database)
    first_attempt, first_partition = _commit_fixture()
    second_attempt, second_partition = _commit_fixture(attempt_no=2, content_suffix="b")
    repository.create_attempt(first_attempt)
    repository.create_attempt(second_attempt)
    repository.partitions.fail_next_insert = RuntimeError(
        "simulated crash after attempt completion CAS"
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        _commit(
            repository,
            first_attempt,
            first_partition,
            now_provider=lambda: "2026-03-19T08:01:00+00:00",
        )

    with pytest.raises(RuntimeError, match="immutable partition conflict"):
        _commit(
            repository,
            second_attempt,
            second_partition,
            now_provider=lambda: "2026-03-19T08:02:00+00:00",
        )

    authoritative = repository.find_completed_partition("selection-stock")
    assert authoritative["partition_id"] == "partition-a"
    assert authoritative["content_hash"] == "content-a"
    assert repository.get_attempt(first_attempt["attempt_id"])["status"] == (
        "completed"
    )
    assert repository.get_attempt(second_attempt["attempt_id"])["status"] == (
        "committing"
    )


def test_expired_committing_worker_cannot_authorize_or_recover_partition():
    database = StatefulMongoDatabase()
    repository = ClxDailySelectionRepository(database)
    attempt, partition = _commit_fixture()
    repository.create_attempt(attempt)

    with pytest.raises(RuntimeError, match="completion claim lost"):
        repository.commit_partition(
            attempt_id=attempt["attempt_id"],
            claim_owner=attempt["claim_owner"],
            claim_token=attempt["claim_token"],
            now="2026-03-19T08:00:00+00:00",
            commit_lease_expires_at="2026-03-19T08:05:00+00:00",
            now_provider=lambda: "2026-03-19T08:06:00+00:00",
            partition=partition,
            memberships=[],
            snapshots=[],
            stats=[],
        )

    with pytest.raises(RuntimeError, match="attempt claim lost"):
        repository.commit_partition(
            attempt_id=attempt["attempt_id"],
            claim_owner=attempt["claim_owner"],
            claim_token=attempt["claim_token"],
            now="2026-03-19T08:06:00+00:00",
            commit_lease_expires_at="2026-03-19T08:30:00+00:00",
            now_provider=lambda: "2026-03-19T08:06:00+00:00",
            partition=partition,
            memberships=[],
            snapshots=[],
            stats=[],
        )

    assert repository.partitions.find_one({"selection_key": "selection-stock"}) is None
    assert repository.get_attempt(attempt["attempt_id"])["status"] == "committing"


def test_default_batch_reads_only_select_published_final_records():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.batch_statuses = CapturingBatchCollection()

    assert repository.list_batches(limit=12, include_partial=False) == []
    repository.latest_batch(include_partial=False)

    assert repository.batch_statuses.last_query == PUBLISHED_FINAL_QUERY
    assert repository.batch_statuses.last_sort == [
        ("trade_date", -1),
        ("updated_at", -1),
    ]
    assert repository.batch_statuses.cursor.sort_spec == [
        ("trade_date", -1),
        ("updated_at", -1),
    ]
    assert repository.batch_statuses.cursor.limit_value == 12


def test_explicit_partial_batch_reads_remain_unfiltered():
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.batch_statuses = CapturingBatchCollection()

    repository.list_batches(limit=5, include_partial=True)
    repository.latest_batch(include_partial=True)

    assert repository.batch_statuses.last_query == {}


class InterleavingBatchCollection:
    def __init__(self, *, final_on_replace=None, existing=None):
        self.rows = {}
        if existing:
            self.rows[existing["_id"]] = deepcopy(existing)
        self.final_on_replace = deepcopy(final_on_replace)

    def find_one(self, query):
        row = self.rows.get(query.get("_id"))
        return deepcopy(row) if row else None

    def replace_one(self, query, payload, upsert=False):
        batch_id = query["_id"]
        if self.final_on_replace is not None:
            self.rows[batch_id] = deepcopy(self.final_on_replace)
            self.final_on_replace = None
            raise DuplicateKeyError("interleaved final insert")
        current = self.rows.get(batch_id)
        if current and current.get("is_final") is True:
            if upsert:
                raise DuplicateKeyError("immutable final already exists")
            return None
        self.rows[batch_id] = deepcopy(payload)
        return None


def test_partial_cas_cannot_overwrite_interleaved_final_batch():
    batch_id = "clx-2026-03-19-production_v1-generation"
    final = {
        "_id": batch_id,
        "batch_id": batch_id,
        "is_final": True,
        "release_status": "final",
        "content_hash": "final-content",
    }
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.batch_statuses = InterleavingBatchCollection(final_on_replace=final)

    stored = repository.upsert_batch_status(
        {
            "batch_id": batch_id,
            "is_final": False,
            "release_status": "partial",
            "content_hash": None,
        }
    )

    assert stored["is_final"] is True
    assert stored["content_hash"] == "final-content"
    assert repository.get_batch(batch_id)["release_status"] == "final"


def test_final_cas_rejects_different_content_after_winner_commits():
    batch_id = "clx-2026-03-19-production_v1-generation"
    existing = {
        "_id": batch_id,
        "batch_id": batch_id,
        "is_final": True,
        "release_status": "final",
        "content_hash": "winner-content",
    }
    repository = ClxDailySelectionRepository.__new__(ClxDailySelectionRepository)
    repository.batch_statuses = InterleavingBatchCollection(existing=existing)

    with pytest.raises(RuntimeError, match="immutable final batch conflict"):
        repository.upsert_batch_status(
            {
                "batch_id": batch_id,
                "is_final": True,
                "release_status": "final",
                "content_hash": "loser-content",
            }
        )


class ReadRepository:
    def __init__(self):
        self.query = None
        self.batch = {
            "batch_id": "clx-2026-03-19-production_v1",
            "trade_date": "2026-03-19",
            "status": "partial",
            "release_status": "partial",
            "is_final": False,
            "partitions": {
                "stock": {
                    "status": "completed",
                    "partition_id": "partition-stock",
                },
                "etf": {"status": "running", "attempt_no": 1},
            },
            "counts": {"stock": {"evaluated_count": 10}, "etf": {}, "total": {}},
        }

    def latest_batch(self, *, include_partial):
        return deepcopy(self.batch) if include_partial else None

    def get_batch(self, batch_id):
        return deepcopy(self.batch) if batch_id == self.batch["batch_id"] else None

    def query_snapshots(self, partition_ids, payload):
        self.query = (list(partition_ids), deepcopy(payload))
        return {"rows": [{"symbol": "000001"}], "total": 1, "next_cursor": None}


def test_partial_read_model_never_claims_final_and_only_queries_completed_side():
    from freshquant.clx_daily_selection.service import ClxDailySelectionService

    repository = ReadRepository()
    service = ClxDailySelectionService(
        repository=repository,
        market_data_provider=object(),
        engine=object(),
    )

    default_latest = service.get_latest_batch(include_partial=False)
    partial_latest = service.get_latest_batch(include_partial=True)
    results = service.query_results(
        repository.batch["batch_id"],
        {"directions": ["buy"], "limit": 50},
    )

    assert default_latest["status"] == "no_ready_batch"
    assert default_latest["is_final"] is False
    assert partial_latest["release_status"] == "partial"
    assert partial_latest["is_final"] is False
    assert results["release_status"] == "partial"
    assert results["is_final"] is False
    assert repository.query == (
        ["partition-stock"],
        {"directions": ["buy"], "limit": 50},
    )
