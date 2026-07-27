from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from flask import Flask

from freshquant.rear.clx_backtest import (
    MemoryClxBacktestStore,
    create_clx_backtest_blueprint,
)
from freshquant.rear.clx_backtest.artifacts import (
    canonical_json_bytes,
)
from freshquant.rear.clx_backtest.artifacts import content_hash as artifact_content_hash
from freshquant.rear.clx_backtest.service import frozen_rank_digest
from freshquant.rear.clx_backtest.store import (
    DERIVED_DATABASE_NAME,
    INDEX_DEFINITIONS,
    MongoClxBacktestStore,
)
from freshquant.rear.clx_backtest.utils import content_hash, encode_cursor


@pytest.fixture
def store() -> MemoryClxBacktestStore:
    return MemoryClxBacktestStore()


@pytest.fixture
def app(store: MemoryClxBacktestStore) -> Flask:
    application = Flask(__name__)
    application.config.update(TESTING=True, MAX_CONTENT_LENGTH=1024 * 1024)
    application.register_blueprint(create_clx_backtest_blueprint(store))
    return application


@pytest.fixture
def client(app: Flask):
    return app.test_client()


def create_run(client, *, name: str = "fixture", config: dict | None = None) -> dict:
    response = client.post(
        "/api/clx-backtest/runs",
        json={
            "name": name,
            "config": config or {"wave_opt": 1560, "models": ["S0000", "S0001"]},
            "lineage": {"snapshot_id": "sha256:snapshot"},
        },
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def seed_complete_run(
    store: MemoryClxBacktestStore, run_id: str = "RUN_COMPLETE"
) -> dict:
    config = {"split": "v1", "fee": {"commission": 0.0003}}
    document = {
        "_id": run_id,
        "run_id": run_id,
        "name": "complete",
        "status": "COMPLETE",
        "config": config,
        "config_sha256": content_hash(config),
        "lineage": {"snapshot_id": "sha256:snapshot"},
        "created_at": "2026-07-22T00:00:00.000Z",
        "updated_at": "2026-07-22T01:00:00.000Z",
    }
    store.seed("runs", [document])
    return document


def error_code(response) -> str:
    payload = response.get_json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) >= {"code", "message"}
    return payload["error"]["code"]


class FakeRunsCollection:
    def __init__(self, document: dict) -> None:
        self.document = copy.deepcopy(document)

    @staticmethod
    def _get(document: dict, path: str):
        value = document
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    @staticmethod
    def _set(document: dict, path: str, value) -> None:
        target = document
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = copy.deepcopy(value)

    def _matches(self, query: dict) -> bool:
        for field, expected in query.items():
            actual = self._get(self.document, field)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif actual != expected:
                return False
        return True

    def _apply(self, update: dict) -> None:
        for field, value in update.get("$set", {}).items():
            self._set(self.document, field, value)
        for field, value in update.get("$push", {}).items():
            target = self.document.setdefault(field, [])
            target.append(copy.deepcopy(value))

    def find_one_and_update(self, query: dict, update: dict, **_kwargs):
        if not self._matches(query):
            return None
        self._apply(update)
        return copy.deepcopy(self.document)

    def find_one(self, query: dict, _projection=None):
        return copy.deepcopy(self.document) if self._matches(query) else None

    def update_one(self, query: dict, update: dict, **_kwargs):
        matched = self._matches(query)
        if matched:
            self._apply(update)
        return FakeUpdateResult(1 if matched else 0)


class FakeUpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeMongoDatabase:
    name = DERIVED_DATABASE_NAME

    def __init__(self, run: dict) -> None:
        self.runs = FakeRunsCollection(run)


class CrashingMongoClxBacktestStore(MongoClxBacktestStore):
    def _project_control(self, job, event) -> None:
        raise SystemExit("injected hard crash after authoritative update")


class RecordingMongoClxBacktestStore(MongoClxBacktestStore):
    def __init__(self, database) -> None:
        super().__init__(database, create_indexes=False)
        self.projected_event_types: list[str] = []

    def _project_control(self, job, event) -> None:
        self.projected_event_types.append(str(event["event_type"]))


def test_health_and_empty_state_are_explicit(client):
    health = client.get("/api/clx-backtest/health")
    assert health.status_code == 200
    assert health.get_json()["data"] == {
        "status": "ok",
        "service": "clx-backtest",
        "database": "freshquant_clx_backtest",
        "capabilities": {
            "inline_worker": False,
            "execution_mode": "EXTERNAL_WORKER",
            "holdout_exactly_once": True,
            "cursor_pagination": True,
        },
    }
    assert client.get("/api/clx-backtest/runs").get_json()["data"] == {
        "items": [],
        "next_cursor": None,
    }


def test_canonical_hash_normalizes_integral_floats_recursively(client):
    server_value = {
        "weight": 1.0,
        "nested": [2.0, {"threshold": 3.0, "ratio": 0.25}],
    }
    browser_value = {
        "weight": 1,
        "nested": [2, {"threshold": 3, "ratio": 0.25}],
    }
    assert canonical_json_bytes(server_value) == canonical_json_bytes(browser_value)
    assert artifact_content_hash(server_value) == artifact_content_hash(browser_value)
    assert content_hash(server_value) == content_hash(browser_value)

    run = create_run(client, config=server_value)
    assert run["config_sha256"] == content_hash(browser_value)


def test_run_create_clone_and_config_is_immutable_after_start(client):
    source_config = {"wave_opt": 1560, "nested": {"models": [0, 1]}}
    run = create_run(client, config=source_config)
    original_hash = run["config_sha256"]
    source_config["nested"]["models"].append(17)

    started = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/start",
        json={"config_sha256": original_hash},
    )
    assert started.status_code == 202
    assert started.get_json()["data"]["job"]["status"] == "QUEUED"
    assert started.get_json()["data"]["job"]["execution_mode"] == "EXTERNAL_WORKER"
    assert started.get_json()["data"]["run"]["projection_pending"] is False

    detail = client.get(f"/api/clx-backtest/runs/{run['run_id']}").get_json()["data"]
    assert detail["run"]["config"] == {
        "wave_opt": 1560,
        "nested": {"models": [0, 1]},
    }
    assert detail["run"]["config_sha256"] == original_hash

    rejected_mutation = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/start",
        json={"config": {"wave_opt": 1}},
    )
    assert rejected_mutation.status_code == 400
    assert error_code(rejected_mutation) == "INVALID_REQUEST"

    clone = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/clone",
        json={"name": "new experiment", "config": {"wave_opt": 777}},
    )
    assert clone.status_code == 201
    cloned = clone.get_json()["data"]
    assert cloned["run_id"] != run["run_id"]
    assert cloned["cloned_from"] == run["run_id"]
    assert cloned["config_sha256"] != original_hash
    assert cloned["status"] == "DRAFT"


def test_start_transition_is_atomic_under_concurrency(app, client):
    run = create_run(client)

    def start_once(_: int) -> tuple[int, str | None]:
        with app.test_client() as thread_client:
            response = thread_client.post(
                f"/api/clx-backtest/runs/{run['run_id']}/start",
                json={"config_sha256": run["config_sha256"]},
            )
            code = None if response.status_code == 202 else error_code(response)
            return response.status_code, code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(start_once, range(8)))

    assert [status for status, _ in results].count(202) == 1
    assert [status for status, _ in results].count(409) == 7
    assert {code for status, code in results if status == 409} == {"INVALID_RUN_STATE"}


def test_cancel_is_an_atomic_state_transition(client):
    run = create_run(client)
    assert (
        client.post(f"/api/clx-backtest/runs/{run['run_id']}/start").status_code == 202
    )
    cancelled = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/cancel",
        json={"reason": "fixture cancellation"},
    )
    assert cancelled.status_code == 202
    assert cancelled.get_json()["data"]["run"]["status"] == "CANCEL_REQUESTED"
    duplicate = client.post(f"/api/clx-backtest/runs/{run['run_id']}/cancel")
    assert duplicate.status_code == 409
    assert error_code(duplicate) == "INVALID_RUN_STATE"


def test_run_embeds_authoritative_job_when_projections_fail():
    class ProjectionFailingStore(MemoryClxBacktestStore):
        def _project_control_locked(self, job, event):
            raise OSError("injected projection failure")

    store = ProjectionFailingStore()
    application = Flask(__name__)
    application.config.update(TESTING=True)
    application.register_blueprint(create_clx_backtest_blueprint(store))
    with application.test_client() as local_client:
        run = create_run(local_client)
        started = local_client.post(f"/api/clx-backtest/runs/{run['run_id']}/start")
        assert started.status_code == 202
        assert store.get_one("jobs", {"run_id": run["run_id"]}) is None
        detail = local_client.get(f"/api/clx-backtest/runs/{run['run_id']}").get_json()[
            "data"
        ]
        assert detail["run"]["status"] == "QUEUED"
        assert detail["run"]["projection_pending"] is True
        assert detail["job"]["status"] == "QUEUED"

        cancelled = local_client.post(f"/api/clx-backtest/runs/{run['run_id']}/cancel")
        assert cancelled.status_code == 202
        detail = local_client.get(f"/api/clx-backtest/runs/{run['run_id']}").get_json()[
            "data"
        ]
        assert detail["run"]["status"] == "CANCEL_REQUESTED"
        assert detail["run"]["projection_pending"] is True
        assert detail["job"]["status"] == "CANCEL_REQUESTED"
        assert [event["event_type"] for event in detail["run"]["control_events"]] == [
            "RUN_QUEUED",
            "CANCEL_REQUESTED",
        ]


def test_mongo_start_survives_a_hard_crash_after_the_authoritative_update():
    config = {"wave_opt": 1560}
    database = FakeMongoDatabase(
        {
            "_id": "RUN_MONGO_START_CRASH",
            "run_id": "RUN_MONGO_START_CRASH",
            "status": "DRAFT",
            "config": config,
            "config_sha256": content_hash(config),
        }
    )
    store = CrashingMongoClxBacktestStore(database, create_indexes=False)

    with pytest.raises(SystemExit, match="injected hard crash"):
        store.start_run(
            "RUN_MONGO_START_CRASH",
            content_hash(config),
            now="2026-07-22T02:00:00.000Z",
            job_id="JOB_START_CRASH",
        )

    run = database.runs.document
    assert run["status"] == "QUEUED"
    assert run["active_job"] == {
        "_id": "JOB_START_CRASH",
        "job_id": "JOB_START_CRASH",
        "run_id": "RUN_MONGO_START_CRASH",
        "kind": "BACKTEST",
        "status": "QUEUED",
        "execution_mode": "EXTERNAL_WORKER",
        "progress": 0.0,
        "created_at": "2026-07-22T02:00:00.000Z",
        "updated_at": "2026-07-22T02:00:00.000Z",
    }
    assert run["control_events"][0] == run["last_control_event"]
    assert run["control_events"][0]["event_type"] == "RUN_QUEUED"
    assert run["projection_pending"] is True


def test_mongo_cancel_survives_a_hard_crash_after_the_authoritative_update():
    active_job = {
        "_id": "JOB_CANCEL_CRASH",
        "job_id": "JOB_CANCEL_CRASH",
        "run_id": "RUN_MONGO_CANCEL_CRASH",
        "kind": "BACKTEST",
        "status": "RUNNING",
        "execution_mode": "EXTERNAL_WORKER",
        "progress": 0.5,
        "created_at": "2026-07-22T02:00:00.000Z",
        "updated_at": "2026-07-22T02:30:00.000Z",
    }
    database = FakeMongoDatabase(
        {
            "_id": "RUN_MONGO_CANCEL_CRASH",
            "run_id": "RUN_MONGO_CANCEL_CRASH",
            "status": "RUNNING",
            "active_job_id": active_job["job_id"],
            "active_job": active_job,
            "control_events": [],
        }
    )
    store = CrashingMongoClxBacktestStore(database, create_indexes=False)

    with pytest.raises(SystemExit, match="injected hard crash"):
        store.cancel_run(
            "RUN_MONGO_CANCEL_CRASH",
            now="2026-07-22T03:00:00.000Z",
            reason="fixture cancellation",
        )

    run = database.runs.document
    assert run["status"] == "CANCEL_REQUESTED"
    assert run["active_job"]["status"] == "CANCEL_REQUESTED"
    assert run["active_job"]["cancel_reason"] == "fixture cancellation"
    assert run["control_events"][-1] == run["last_control_event"]
    assert run["control_events"][-1]["event_type"] == "CANCEL_REQUESTED"
    assert run["projection_pending"] is True


def test_mongo_clears_projection_marker_only_after_each_projection_succeeds():
    config = {"wave_opt": 1560}
    database = FakeMongoDatabase(
        {
            "_id": "RUN_MONGO_PROJECTED",
            "run_id": "RUN_MONGO_PROJECTED",
            "status": "DRAFT",
            "config": config,
            "config_sha256": content_hash(config),
        }
    )
    store = RecordingMongoClxBacktestStore(database)

    started = store.start_run(
        "RUN_MONGO_PROJECTED",
        content_hash(config),
        now="2026-07-22T02:00:00.000Z",
        job_id="JOB_PROJECTED",
    )
    assert started["run"]["projection_pending"] is False
    assert database.runs.document["projection_pending"] is False

    cancelled = store.cancel_run(
        "RUN_MONGO_PROJECTED",
        now="2026-07-22T03:00:00.000Z",
        reason=None,
    )
    assert cancelled["run"]["projection_pending"] is False
    assert database.runs.document["projection_pending"] is False
    assert store.projected_event_types == ["RUN_QUEUED", "CANCEL_REQUESTED"]


def test_later_projection_does_not_hide_an_earlier_unreconciled_event():
    config = {"wave_opt": 1560}
    database = FakeMongoDatabase(
        {
            "_id": "RUN_MONGO_PENDING_HISTORY",
            "run_id": "RUN_MONGO_PENDING_HISTORY",
            "status": "DRAFT",
            "config": config,
            "config_sha256": content_hash(config),
        }
    )
    crashing_store = CrashingMongoClxBacktestStore(database, create_indexes=False)
    with pytest.raises(SystemExit):
        crashing_store.start_run(
            "RUN_MONGO_PENDING_HISTORY",
            content_hash(config),
            now="2026-07-22T02:00:00.000Z",
            job_id="JOB_PENDING_HISTORY",
        )

    restarted_store = RecordingMongoClxBacktestStore(database)
    cancelled = restarted_store.cancel_run(
        "RUN_MONGO_PENDING_HISTORY",
        now="2026-07-22T03:00:00.000Z",
        reason=None,
    )

    assert cancelled["run"]["status"] == "CANCEL_REQUESTED"
    assert cancelled["run"]["projection_pending"] is True
    assert database.runs.document["projection_pending"] is True
    assert restarted_store.projected_event_types == ["CANCEL_REQUESTED"]


def test_rankings_and_detail_pages_use_stable_keyset_cursors(client, store):
    run = seed_complete_run(store)
    combos = [f"C{number:02d}" for number in range(5)]
    store.seed(
        "combo_definitions",
        [
            {
                "_id": f"definition-{combo_id}",
                "run_id": run["run_id"],
                "combo_id": combo_id,
                "dsl": {"model": number},
            }
            for number, combo_id in enumerate(combos)
        ],
    )
    scores = [10.0, 9.0, 9.0, 8.0, 7.0]
    store.seed(
        "combo_metrics",
        [
            {
                "_id": f"metric-{combo_id}",
                "run_id": run["run_id"],
                "combo_id": combo_id,
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": score,
                "sample_count": 100,
                "model_ids": [2, 7] if index in {0, 2} else [2],
                "model_id": 2,
                "primary_triggers": (
                    ["PIN_BAR", "MACD_CROSS"] if index in {0, 2} else ["PIN_BAR"]
                ),
                "primary_trigger": "PIN_BAR",
                "occurrences": [1, 2] if index in {0, 2} else [1],
                "occurrence": 1,
            }
            for index, (combo_id, score) in enumerate(zip(combos, scores, strict=True))
        ]
        + [
            {
                "_id": "metric-other-horizon",
                "run_id": run["run_id"],
                "combo_id": combos[0],
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 20,
                "score": 99.0,
                "sample_count": 100,
            },
            {
                "_id": "metric-other-segment",
                "run_id": run["run_id"],
                "combo_id": combos[0],
                "split_id": "VALIDATION",
                "segment_type": "SINGLE_MODEL",
                "segment_value": "S0000",
                "horizon": 5,
                "score": 98.0,
                "sample_count": 100,
            },
        ],
    )

    seen: list[str] = []
    cursor = None
    while True:
        query = (
            f"?page_size=2&split_id=VALIDATION{f'&cursor={cursor}' if cursor else ''}"
        )
        response = client.get(f"/api/clx-backtest/runs/{run['run_id']}/rankings{query}")
        assert response.status_code == 200
        page = response.get_json()["data"]
        seen.extend(item["combo_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == combos
    assert len(seen) == len(set(seen))

    explicit_horizon = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings"
        "?split_id=VALIDATION&horizon=20"
    )
    assert explicit_horizon.status_code == 200
    assert [
        (item["combo_id"], item["horizon"], item["segment_type"])
        for item in explicit_horizon.get_json()["data"]["items"]
    ] == [(combos[0], 20, "ALL")]

    filtered = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings"
        "?split_id=VALIDATION&horizon=5&min_score=9&page_size=20"
    )
    assert [
        item["combo_id"] for item in filtered.get_json()["data"]["items"]
    ] == combos[:3]

    membership_seen: list[str] = []
    cursor = None
    while True:
        query = (
            "?split_id=VALIDATION&model_id=7&primary_trigger=MACD_CROSS"
            f"&occurrence=2&page_size=1{f'&cursor={cursor}' if cursor else ''}"
        )
        response = client.get(f"/api/clx-backtest/runs/{run['run_id']}/rankings{query}")
        assert response.status_code == 200
        page = response.get_json()["data"]
        membership_seen.extend(item["combo_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert membership_seen == [combos[0], combos[2]]

    detail = client.get(f"/api/clx-backtest/runs/{run['run_id']}/combos/{combos[0]}")
    assert detail.status_code == 200
    metrics = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/combos/{combos[0]}/metrics"
        "?page_size=1"
    )
    assert metrics.status_code == 200
    assert metrics.get_json()["data"]["items"][0]["score"] == 10.0


def test_combo_time_series_heatmap_compare_quality_and_manifest(client, store):
    run = seed_complete_run(store, "RUN_VIEWS")
    combo_ids = ["COMBO_A", "COMBO_B"]
    store.seed(
        "combo_definitions",
        [
            {
                "_id": f"def-{combo}",
                "run_id": run["run_id"],
                "combo_id": combo,
                "dsl": {"id": combo},
            }
            for combo in combo_ids
        ],
    )
    store.seed(
        "combo_metrics",
        [
            {
                "_id": f"metric-{combo}",
                "run_id": run["run_id"],
                "combo_id": combo,
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": 2.0 - index,
            }
            for index, combo in enumerate(combo_ids)
        ],
    )
    store.seed(
        "portfolio_summaries",
        [
            {
                "_id": "summary-a",
                "run_id": run["run_id"],
                "portfolio_id": "P1",
                "combo_id": "COMBO_A",
                "split_id": "VALIDATION",
            }
        ],
    )
    store.seed(
        "portfolio_equity",
        [
            {
                "_id": f"eq-{day}",
                "run_id": run["run_id"],
                "combo_id": "COMBO_A",
                "split_id": "VALIDATION",
                "trade_date": f"2026-01-0{day}",
                "equity": 100 + day,
            }
            for day in range(1, 4)
        ],
    )
    store.seed(
        "portfolio_trades",
        [
            {
                "_id": "trade-1",
                "run_id": run["run_id"],
                "combo_id": "COMBO_A",
                "split_id": "VALIDATION",
                "sequence": 1,
                "code": "000001",
            }
        ],
    )
    store.seed(
        "combo_signals",
        [
            {
                "_id": "signal-1",
                "run_id": run["run_id"],
                "combo_id": "COMBO_A",
                "split_id": "VALIDATION",
                "reveal_date": "2025-12-31",
                "signal_fact_id": "SF1",
            }
        ],
    )
    store.seed(
        "model_heatmap",
        [
            {
                "_id": "hm-1",
                "run_id": run["run_id"],
                "split_id": "VALIDATION",
                "model_id": 0,
                "trigger_key": "FRACTAL",
                "score": 1.25,
            }
        ],
    )
    store.seed(
        "manifests",
        [
            {
                "_id": "manifest-1",
                "run_id": run["run_id"],
                "manifest_sha256": "sha256:manifest",
                "state": "COMPLETE",
                "quality": {"adjustment_gap_count": 7},
            }
        ],
    )
    store.seed(
        "audit_findings",
        [
            {
                "_id": "audit-1",
                "run_id": run["run_id"],
                "kind": "ADJ_GAP",
                "severity": "WARNING",
                "status": "OPEN",
                "created_at": "2026-07-22T00:00:00.000Z",
            }
        ],
    )

    base = f"/api/clx-backtest/runs/{run['run_id']}/combos/COMBO_A"
    assert (
        len(client.get(base + "/equity?page_size=2").get_json()["data"]["items"]) == 2
    )
    assert (
        client.get(base + "/trades").get_json()["data"]["items"][0]["code"] == "000001"
    )
    assert (
        client.get(base + "/signals").get_json()["data"]["items"][0]["signal_fact_id"]
        == "SF1"
    )

    heatmap = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/model-heatmap?metric=score"
    )
    assert heatmap.get_json()["data"]["items"][0]["trigger_key"] == "FRACTAL"
    compared = client.post(
        "/api/clx-backtest/compare",
        json={
            "run_id": run["run_id"],
            "combo_ids": combo_ids,
            "split_id": "VALIDATION",
            "horizon": 5,
        },
    )
    assert compared.status_code == 200
    assert [
        item["combo"]["combo_id"] for item in compared.get_json()["data"]["items"]
    ] == combo_ids
    assert (
        client.get(f"/api/clx-backtest/runs/{run['run_id']}/manifest").get_json()[
            "data"
        ]["state"]
        == "COMPLETE"
    )
    quality = client.get(f"/api/clx-backtest/runs/{run['run_id']}/quality").get_json()[
        "data"
    ]
    assert quality["quality"]["adjustment_gap_count"] == 7
    assert quality["audit_findings"][0]["kind"] == "ADJ_GAP"


def test_holdout_freeze_and_reveal_are_atomic_exactly_once(app, client, store):
    run = seed_complete_run(store, "RUN_HOLDOUT")
    ranking_config = {"score": "v1", "weight": 1.0}
    ranking_config_sha256 = content_hash(ranking_config)
    split_config_sha256 = content_hash({"split": "v1"})
    rank_order = ["C1", "C2"]
    server_freeze_input = {
        "validation": {"selected_combo_ids": ["C1"], "rank_order": rank_order},
        "ranking_config": ranking_config,
        "split_config_sha256": split_config_sha256,
        "frozen_rank_digest": frozen_rank_digest(
            run["run_id"], rank_order, ranking_config_sha256
        ),
    }
    store.seed(
        "combo_metrics",
        [
            {
                "_id": "holdout-metric",
                "run_id": run["run_id"],
                "combo_id": "C1",
                "split_id": "HOLDOUT",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": 1.0,
            },
            {
                "_id": "validation-c1",
                "run_id": run["run_id"],
                "combo_id": "C1",
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": 2.0,
                "frozen_rank": 1,
                "ranking_config_sha256": ranking_config_sha256,
            },
            {
                "_id": "validation-c2",
                "run_id": run["run_id"],
                "combo_id": "C2",
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": 1.0,
                "frozen_rank": 2,
                "ranking_config_sha256": ranking_config_sha256,
            },
        ],
    )
    locked = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings?split_id=HOLDOUT"
    )
    assert locked.status_code == 423
    assert error_code(locked) == "HOLDOUT_LOCKED"
    store.seed(
        "combo_definitions",
        [
            {"_id": "holdout-def-1", "run_id": run["run_id"], "combo_id": "C1"},
            {"_id": "holdout-def-2", "run_id": run["run_id"], "combo_id": "C2"},
        ],
    )
    store.seed(
        "portfolio_summaries",
        [
            {
                "_id": "holdout-summary",
                "run_id": run["run_id"],
                "portfolio_id": "P-HOLDOUT",
                "combo_id": "C1",
                "split_id": "HOLDOUT",
                "holdout_return": 9.99,
            }
        ],
    )
    store.seed(
        "manifests",
        [
            {
                "_id": "holdout-manifest",
                "run_id": run["run_id"],
                "manifest_sha256": content_hash({"run_id": run["run_id"]}),
                "state": "COMPLETE",
                "config": {
                    "split_config_sha256": split_config_sha256,
                    "ranking_config": ranking_config,
                    "ranking_config_sha256": ranking_config_sha256,
                },
                "freeze_input": server_freeze_input,
            }
        ],
    )
    default_metrics = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/combos/C1/metrics"
    )
    assert default_metrics.status_code == 200
    assert default_metrics.get_json()["data"]["items"][0]["split_id"] == "VALIDATION"
    explicit_holdout = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/combos/C1/metrics?split_id=HOLDOUT"
    )
    assert explicit_holdout.status_code == 423
    locked_detail = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/combos/C1?split_id=HOLDOUT"
    )
    assert locked_detail.status_code == 423
    locked_export = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/exports",
        json={
            "resource": "metrics",
            "format": "csv",
            "combo_ids": ["C1"],
            "split_id": "HOLDOUT",
        },
    )
    assert locked_export.status_code == 423

    empty_freeze = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/freeze",
        json={"validation": {}},
    )
    assert empty_freeze.status_code == 400

    malformed_freeze = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/freeze",
        json={
            "validation": {
                "selected_combo_ids": ["C2"],
                "rank_order": ["C1"],
            },
            "ranking_config": {},
            "split_config_sha256": "sha256:short",
            "frozen_rank_digest": "sha256:short",
        },
    )
    assert malformed_freeze.status_code == 400

    published_manifest = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/manifest"
    ).get_json()["data"]
    freeze_payload = published_manifest["freeze_input"]
    assert freeze_payload == server_freeze_input
    frozen = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/freeze", json=freeze_payload
    )
    assert frozen.status_code == 201
    freeze = frozen.get_json()["data"]
    browser_round_trip = copy.deepcopy(freeze_payload)
    browser_round_trip["ranking_config"]["weight"] = 1
    repeated_freeze = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/freeze", json=browser_round_trip
    )
    assert repeated_freeze.status_code == 200
    assert repeated_freeze.get_json()["data"]["freeze_id"] == freeze["freeze_id"]
    conflicting_freeze = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/freeze",
        json={
            **freeze_payload,
            "validation": {
                "selected_combo_ids": ["C2"],
                "rank_order": rank_order,
            },
        },
    )
    assert conflicting_freeze.status_code == 409
    assert error_code(conflicting_freeze) == "FREEZE_SOURCE_MISMATCH"

    reveal_url = (
        f"/api/clx-backtest/runs/{run['run_id']}/freezes/"
        f"{freeze['freeze_id']}/holdout/reveal"
    )

    def reveal_once(_: int) -> tuple[int, str | None]:
        with app.test_client() as thread_client:
            response = thread_client.post(reveal_url)
            return (
                response.status_code,
                None if response.status_code == 200 else error_code(response),
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reveal_once, range(8)))
    assert [status for status, _ in results].count(200) == 1
    assert [status for status, _ in results].count(409) == 7
    assert {code for status, code in results if status == 409} == {
        "HOLDOUT_REVEAL_IN_PROGRESS"
    }

    still_locked = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings?split_id=HOLDOUT"
    )
    assert still_locked.status_code == 423
    locked_detail_after_queue = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/combos/C1?split_id=HOLDOUT"
    )
    assert locked_detail_after_queue.status_code == 423
    locked_export_after_queue = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/exports",
        json={
            "resource": "metrics",
            "format": "csv",
            "combo_ids": ["C1"],
            "split_id": "HOLDOUT",
        },
    )
    assert locked_export_after_queue.status_code == 423
    record = store.get_one(
        "freeze_records", {"run_id": run["run_id"], "freeze_id": freeze["freeze_id"]}
    )
    assert record["state"] == "REVEALING"
    assert record["reveal_count"] == 0
    assert record["holdout_revealed_at"] is None
    assert record["holdout_reveal_requested_at"]
    assert record["run_config_sha256"] == run["config_sha256"]
    assert record["specification"] == server_freeze_input
    queued_audit = store.get_one(
        "audit_findings",
        {"run_id": run["run_id"], "kind": "HOLDOUT_REVEAL_QUEUED"},
    )
    assert queued_audit is not None
    assert queued_audit["details"]["freeze_id"] == freeze["freeze_id"]
    assert queued_audit["details"]["job_id"] == record["holdout_job_id"]
    reloaded = client.get(f"/api/clx-backtest/runs/{run['run_id']}").get_json()["data"]
    assert reloaded["freeze"] == {
        "freeze_id": freeze["freeze_id"],
        "state": "REVEALING",
        "reveal_count": 0,
        "created_at": record["created_at"],
        "holdout_revealed_at": None,
        "run_config_sha256": run["config_sha256"],
    }


def test_holdout_queries_open_only_after_worker_publishes_reveal(client, store):
    run = seed_complete_run(store, "RUN_REVEALED_BY_WORKER")
    store.seed(
        "freeze_records",
        [
            {
                "_id": "worker-revealed-freeze",
                "run_id": run["run_id"],
                "freeze_id": "sha256:" + "a" * 64,
                "state": "REVEALED",
                "reveal_count": 1,
                "holdout_revealed_at": "2026-07-22T05:00:00.000Z",
            }
        ],
    )
    store.seed(
        "combo_metrics",
        [
            {
                "_id": f"validation-ranking-{combo_id}",
                "run_id": run["run_id"],
                "combo_id": combo_id,
                "split_id": "VALIDATION",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": validation_score,
                "frozen_rank": frozen_rank,
            }
            for combo_id, validation_score, frozen_rank in (
                ("C1", 0.91, 1),
                ("C2", 0.82, 2),
                ("C3", 0.73, 3),
            )
        ],
    )
    store.seed(
        "combo_metrics",
        [
            {
                "_id": f"holdout-ranking-{combo_id}",
                "run_id": run["run_id"],
                "combo_id": combo_id,
                "split_id": "HOLDOUT",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": holdout_score,
                "frozen_rank": frozen_rank,
                "mean_return": mean_return,
            }
            for combo_id, holdout_score, frozen_rank, mean_return in (
                ("C1", 1.0, 1, 0.011),
                ("C2", 2.0, 2, 0.022),
                ("C3", 3.0, 3, 0.033),
            )
        ],
    )

    seen: list[tuple[str, int, float, float, float]] = []
    cursor = None
    while True:
        query = f"?split_id=HOLDOUT&page_size=2{f'&cursor={cursor}' if cursor else ''}"
        rankings = client.get(f"/api/clx-backtest/runs/{run['run_id']}/rankings{query}")
        assert rankings.status_code == 200
        page = rankings.get_json()["data"]
        seen.extend(
            (
                item["combo_id"],
                item["frozen_rank"],
                item["score"],
                item["validation_score"],
                item["mean_return"],
            )
            for item in page["items"]
        )
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [
        ("C1", 1, 0.91, 0.91, 0.011),
        ("C2", 2, 0.82, 0.82, 0.022),
        ("C3", 3, 0.73, 0.73, 0.033),
    ]
    holdout_score_filter = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings"
        "?split_id=HOLDOUT&min_score=2"
    )
    assert holdout_score_filter.status_code == 400
    assert error_code(holdout_score_filter) == "INVALID_REQUEST"
    exported = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/exports",
        json={
            "resource": "metrics",
            "format": "csv",
            "combo_ids": [],
            "split_id": "HOLDOUT",
        },
    )
    assert exported.status_code == 202
    assert exported.get_json()["data"]["holdout_access"]["reveal_count"] == 1


@pytest.mark.parametrize(
    "validation_metric",
    [
        None,
        {"score": 0.91, "frozen_rank": 2},
        {"score": "not-a-number", "frozen_rank": 1},
        {"score": 0.91, "frozen_rank": True},
    ],
    ids=[
        "missing-validation-metric",
        "frozen-rank-mismatch",
        "invalid-validation-score",
        "invalid-frozen-rank-type",
    ],
)
def test_holdout_rankings_fail_closed_on_validation_link_drift(
    client, store, validation_metric
):
    run = seed_complete_run(store, "RUN_HOLDOUT_RANKING_DRIFT")
    store.seed(
        "freeze_records",
        [
            {
                "_id": "revealed-freeze-for-ranking-drift",
                "run_id": run["run_id"],
                "freeze_id": "sha256:" + "b" * 64,
                "state": "REVEALED",
                "reveal_count": 1,
                "holdout_revealed_at": "2026-07-22T05:00:00.000Z",
            }
        ],
    )
    store.seed(
        "combo_metrics",
        [
            {
                "_id": "holdout-ranking-with-drift",
                "run_id": run["run_id"],
                "combo_id": "C1",
                "split_id": "HOLDOUT",
                "segment_type": "ALL",
                "segment_value": "ALL",
                "horizon": 5,
                "score": 9.99,
                "frozen_rank": 1,
                "mean_return": 0.031,
            }
        ],
    )
    if validation_metric is not None:
        store.seed(
            "combo_metrics",
            [
                {
                    "_id": "validation-ranking-with-drift",
                    "run_id": run["run_id"],
                    "combo_id": "C1",
                    "split_id": "VALIDATION",
                    "segment_type": "ALL",
                    "segment_value": "ALL",
                    "horizon": 5,
                    **validation_metric,
                }
            ],
        )

    response = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings?split_id=HOLDOUT"
    )
    assert response.status_code == 500
    assert error_code(response) == "HOLDOUT_RANKING_INTEGRITY_ERROR"


def test_holdout_rankings_reject_pre_frozen_rank_cursor(client, store):
    run = seed_complete_run(store, "RUN_HOLDOUT_STALE_CURSOR")
    store.seed(
        "freeze_records",
        [
            {
                "_id": "revealed-freeze-for-stale-cursor",
                "run_id": run["run_id"],
                "freeze_id": "sha256:" + "c" * 64,
                "state": "REVEALED",
                "reveal_count": 1,
                "holdout_revealed_at": "2026-07-22T05:00:00.000Z",
            }
        ],
    )
    equals = {
        "run_id": run["run_id"],
        "split_id": "HOLDOUT",
        "horizon": 5,
        "segment_type": "ALL",
        "segment_value": "ALL",
    }
    old_filter_kind = (
        f"rankings:{run['run_id']}:HOLDOUT:"
        f"{content_hash({'equals': equals, 'ranges': {}})}"
    )
    stale_cursor = encode_cursor(
        old_filter_kind,
        [9.99, "C1", "holdout-ranking-before-frozen-rank-sort"],
    )

    response = client.get(
        f"/api/clx-backtest/runs/{run['run_id']}/rankings"
        f"?split_id=HOLDOUT&cursor={stale_cursor}"
    )
    assert response.status_code == 400
    assert error_code(response) == "INVALID_CURSOR"


def test_export_metadata_and_progress_stream(client):
    run = create_run(client)
    client.post(f"/api/clx-backtest/runs/{run['run_id']}/start")
    progress = client.get(f"/api/clx-backtest/runs/{run['run_id']}/progress")
    assert progress.get_json()["data"]["items"][0]["event_type"] == "RUN_QUEUED"
    stream = client.get(f"/api/clx-backtest/runs/{run['run_id']}/progress/stream")
    assert stream.status_code == 200
    assert stream.mimetype == "text/event-stream"
    assert b"event: progress" in stream.data
    assert b"RUN_QUEUED" in stream.data

    exported = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/exports",
        json={"resource": "signals", "format": "csv", "combo_ids": []},
    )
    assert exported.status_code == 202
    job = exported.get_json()["data"]
    assert job["status"] == "QUEUED"
    assert job["split_id"] == "VALIDATION"
    assert "holdout_access" not in job
    assert job["artifact_key"].startswith(f"exports/{run['run_id']}/")
    assert client.get(f"/api/clx-backtest/exports/{job['job_id']}").status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "json_body", "expected_code"),
    [
        ("get", "/api/clx-backtest/runs?page_size=201", None, "INVALID_REQUEST"),
        ("get", "/api/clx-backtest/runs?filter[$where]=1", None, "INVALID_REQUEST"),
        ("get", "/api/clx-backtest/runs?cursor=not-a-cursor", None, "INVALID_CURSOR"),
        (
            "post",
            "/api/clx-backtest/runs",
            {"name": "bad", "config": {"$where": "x"}},
            "INVALID_REQUEST",
        ),
    ],
)
def test_limits_and_query_injection_return_stable_errors(
    client, method, path, json_body, expected_code
):
    if "cursor=" in path:
        create_run(client)
    response = getattr(client, method)(path, json=json_body)
    assert response.status_code == 400
    assert error_code(response) == expected_code


def test_clx_body_limit_is_local_and_returns_a_stable_error(client):
    response = client.post(
        "/api/clx-backtest/runs",
        data=b"x" * (1024 * 1024 + 1),
        content_type="application/json",
    )
    assert response.status_code == 413
    assert error_code(response) == "PAYLOAD_TOO_LARGE"


def test_export_never_accepts_a_caller_supplied_path(client):
    run = create_run(client)
    response = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/exports",
        json={
            "resource": "signals",
            "format": "csv",
            "combo_ids": [],
            "path": "../../etc/passwd",
        },
    )
    assert response.status_code == 400
    assert error_code(response) == "INVALID_REQUEST"


def test_required_unique_and_query_indexes_are_declared():
    assert any(index.unique for index in INDEX_DEFINITIONS["manifests"])
    assert any(index.unique for index in INDEX_DEFINITIONS["combo_definitions"])
    assert any(index.unique for index in INDEX_DEFINITIONS["combo_metrics"])
    assert any(index.unique for index in INDEX_DEFINITIONS["freeze_records"])
    assert any(
        index.name == "combo_metric_rank"
        for index in INDEX_DEFINITIONS["combo_metrics"]
    )
    assert any(
        index.name == "combo_metric_frozen_rank"
        and index.keys[-3:] == (("frozen_rank", 1), ("combo_id", 1), ("_id", 1))
        for index in INDEX_DEFINITIONS["combo_metrics"]
    )
    assert any(
        index.name == "progress_run_page"
        for index in INDEX_DEFINITIONS["progress_events"]
    )
    assert any(
        index.name == "portfolio_summary_combo_split" and ("split_id", 1) in index.keys
        for index in INDEX_DEFINITIONS["portfolio_summaries"]
    )


def test_mongo_store_is_hard_bound_to_the_derived_database():
    class WrongDatabase:
        name = "quantaxis"

    with pytest.raises(ValueError, match=DERIVED_DATABASE_NAME):
        MongoClxBacktestStore(WrongDatabase(), create_indexes=False)


def test_api_server_registers_the_injected_clx_blueprint(store):
    from freshquant.rear.api_server import create_app

    application = create_app(
        {"TESTING": True},
        clx_backtest_store=store,
    )
    rules = {rule.rule for rule in application.url_map.iter_rules()}
    assert "/api/clx-backtest/health" in rules
    assert application.config["MAX_CONTENT_LENGTH"] is None
    assert application.test_client().get("/api/clx-backtest/health").status_code == 200


def test_malformed_json_and_repeated_query_do_not_trigger_actions(client):
    run = create_run(client)
    malformed = client.post(
        f"/api/clx-backtest/runs/{run['run_id']}/start",
        data="{",
        content_type="application/json",
    )
    assert malformed.status_code == 400
    assert error_code(malformed) == "INVALID_REQUEST"
    detail = client.get(f"/api/clx-backtest/runs/{run['run_id']}").get_json()["data"]
    assert detail["run"]["status"] == "DRAFT"
    repeated = client.get("/api/clx-backtest/runs?page_size=1&page_size=2")
    assert repeated.status_code == 400
    assert error_code(repeated) == "INVALID_REQUEST"
