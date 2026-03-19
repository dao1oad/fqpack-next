from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]

    def find(self, query=None):
        query = query or {}
        return [
            dict(doc)
            for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]


class ScreeningCollection(FakeCollection):
    def find_one(self, query=None):
        rows = self.find(query)
        return rows[0] if rows else None

    def replace_one(self, query, document, upsert=False):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(document)
                return
        if upsert:
            self.docs.append(dict(document))

    def delete_many(self, query):
        self.docs = [
            dict(doc)
            for doc in self.docs
            if not all(doc.get(key) == value for key, value in query.items())
        ]

    def insert_many(self, documents, ordered=False):
        self.docs.extend(dict(doc) for doc in documents)


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


class FakeScreeningRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def save_run(self, run=None, **document):
        payload = dict(run or {})
        payload.update(document)
        run_id = payload["run_id"]
        existing = dict(self.runs.get(run_id, {}))
        existing.update(payload)
        self.runs[run_id] = existing
        return dict(existing)

    def get_run(self, run_id):
        row = self.runs.get(run_id)
        return dict(row) if row is not None else None


def _make_service(*, fake_db=None, session_store=None):
    from freshquant.daily_screening.pipeline_service import (
        DailyScreeningPipelineService,
    )
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    return DailyScreeningService(
        session_store=session_store or DailyScreeningSessionStore(),
        db=fake_db or FakeDB(stock_pre_pools=FakeCollection([])),
        pipeline_service=DailyScreeningPipelineService(
            repository=FakeScreeningRepository()
        ),
    )


def _make_service_with_screening_repo(
    *, fake_db=None, screening_db=None, session_store=None
):
    from freshquant.daily_screening.pipeline_service import (
        DailyScreeningPipelineService,
    )
    from freshquant.daily_screening.repository import DailyScreeningRepository
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    target_screening_db = screening_db or FakeDB(
        daily_screening_runs=ScreeningCollection([]),
        daily_screening_memberships=ScreeningCollection([]),
        daily_screening_stock_snapshots=ScreeningCollection([]),
    )
    repository = DailyScreeningRepository(db=target_screening_db)
    service = DailyScreeningService(
        session_store=session_store or DailyScreeningSessionStore(),
        db=fake_db or FakeDB(stock_pre_pools=FakeCollection([])),
        pipeline_service=DailyScreeningPipelineService(repository=repository),
    )
    return service, repository, target_screening_db


FULL_CLXS_MODEL_OPTS = list(range(10001, 10013))
FULL_CLXS_MODEL_LABELS = [f"S{i:04d}" for i in range(1, 13)]


def _parse_sse_events(chunks: list[str]) -> list[dict]:
    parsed = []
    for chunk in chunks:
        lines = [line for line in chunk.strip().splitlines() if line]
        event_id = next(
            line.split(": ", 1)[1] for line in lines if line.startswith("id: ")
        )
        event = next(
            line.split(": ", 1)[1] for line in lines if line.startswith("event: ")
        )
        data = next(
            line.split(": ", 1)[1] for line in lines if line.startswith("data: ")
        )
        parsed.append({"id": int(event_id), "event": event, "data": json.loads(data)})
    return parsed


def test_daily_screening_schema_exposes_dynamic_pre_pool_options():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(
        stock_pre_pools=FakeCollection(
            [
                {
                    "code": "000001",
                    "category": "CLXS_10001",
                    "remark": "daily-screening:clxs",
                },
                {
                    "code": "000002",
                    "category": "chanlun_service",
                    "remark": "daily-screening:chanlun",
                },
            ]
        )
    )

    service = _make_service(fake_db=fake_db)

    schema = service.get_schema()

    assert [model["id"] for model in schema["models"]] == ["all", "clxs", "chanlun"]
    assert schema["options"]["pre_pool_categories"] == [
        "CLXS_10001",
        "chanlun_service",
    ]
    assert schema["options"]["pre_pool_remarks"] == [
        "daily-screening:chanlun",
        "daily-screening:clxs",
    ]
    all_model = next(item for item in schema["models"] if item["id"] == "all")
    all_clxs_field = next(
        field for field in all_model["fields"] if field["name"] == "clxs_model_opts"
    )
    assert all_clxs_field["default"] == FULL_CLXS_MODEL_OPTS
    assert [
        option["value"] for option in all_clxs_field["options"]
    ] == FULL_CLXS_MODEL_OPTS
    assert [
        option["label"] for option in all_clxs_field["options"]
    ] == FULL_CLXS_MODEL_LABELS
    assert any(field["name"] == "chanlun_signal_types" for field in all_model["fields"])
    clxs_model = next(item for item in schema["models"] if item["id"] == "clxs")
    clxs_field = next(
        field for field in clxs_model["fields"] if field["name"] == "model_opts"
    )
    assert clxs_field["default"] == [10001]
    assert [option["value"] for option in clxs_field["options"]] == FULL_CLXS_MODEL_OPTS
    assert [
        option["label"] for option in clxs_field["options"]
    ] == FULL_CLXS_MODEL_LABELS
    chanlun_model = next(item for item in schema["models"] if item["id"] == "chanlun")
    assert any(field["name"] == "input_mode" for field in chanlun_model["fields"])


def test_daily_screening_service_normalizes_all_mode_to_full_clxs_model_set():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    service = _make_service()

    config = service._normalize_start_payload({"model": "all"})

    assert config["clxs"]["model_opts"] == FULL_CLXS_MODEL_OPTS
    assert config["clxs"]["model_opt"] == 10001
    assert config["clxs"]["remark"] == "daily-screening:clxs"


def test_daily_screening_service_start_run_supports_dagster_trigger_type():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    captured = {}

    class FakePipelineService:
        def start_run(self, params, *, trigger_type):
            captured["trigger_type"] = trigger_type
            return {"id": "run-dagster", "run_id": "run-dagster"}

        def execute_run(self, run_id, config, *, execute_stage, on_event):
            captured["execute_run"] = {
                "run_id": run_id,
                "model": config["model"],
            }
            on_event(
                "run_started",
                {"run_id": run_id, "status": "running", "model": config["model"]},
            )
            on_event(
                "run_completed",
                {
                    "run_id": run_id,
                    "status": "completed",
                    "summary": {"accepted_count": 0, "persisted_count": 0},
                    "stage_summaries": {},
                },
            )
            return {"run_id": run_id, "status": "completed"}

    service = DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=FakeDB(stock_pre_pools=FakeCollection([])),
        pipeline_service=FakePipelineService(),
    )

    run = service.start_run(
        {"model": "all"},
        run_async=False,
        trigger_type="dagster_schedule",
    )

    assert captured["trigger_type"] == "dagster_schedule"
    assert captured["execute_run"] == {"run_id": "run-dagster", "model": "all"}
    assert run["status"] == "completed"


def test_daily_screening_service_ensures_screening_indexes_on_init():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    captured = {"ensure_indexes": 0}

    class FakePipelineService:
        def __init__(self):
            self.repository = SimpleNamespace(
                ensure_indexes=lambda: captured.__setitem__(
                    "ensure_indexes", captured["ensure_indexes"] + 1
                )
            )

    DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=FakeDB(stock_pre_pools=FakeCollection([])),
        pipeline_service=FakePipelineService(),
    )

    assert captured["ensure_indexes"] == 1


def test_daily_screening_service_runs_clxs_and_persists_results_with_remark(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = _make_service(fake_db=fake_db)

    persisted = []
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: persisted.append(kwargs),
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )

    class FakeClxsStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, days=1, code=None, **_kwargs):
            self.kwargs["on_universe"](
                {"strategy": "clxs", "total": 1, "mode": "market", "code": code}
            )
            self.kwargs["on_stock_progress"](
                {
                    "strategy": "clxs",
                    "processed": 1,
                    "total": 1,
                    "code": "000001",
                    "name": "alpha",
                    "result_count": 1,
                    "status": "ok",
                }
            )
            payload = {
                "strategy": "clxs",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": "CLXS_10001",
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_hit_raw"](payload)
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type="CLXS_10001",
                    position="BUY_LONG",
                )
            ]

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            **service._make_strategy_hooks(run_id, config)
        ),
    )

    snapshot = service.start_run(
        {
            "model": "clxs",
            "days": 1,
            "save_pre_pools": True,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])
    events = service.session_store.get_events(run["id"])

    assert run["status"] == "completed"
    assert run["stage_summaries"]["clxs"]["status"] == "completed"
    assert run["stage_summaries"]["clxs"]["accepted_count"] == 1
    assert run["progress"]["accepted"] == 1
    assert run["progress"]["persisted"] == 1
    assert run["results"][0]["code"] == "000001"
    assert [event["event"] for event in events] == [
        "run_started",
        "stage_started",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_completed",
        "run_completed",
    ]
    assert persisted == [
        {
            "code": "000001",
            "category": "CLXS_10001",
            "dt": datetime(2026, 3, 17, 15, 0),
            "stop_loss_price": 9.8,
            "expire_at_days": 89,
            "remark": "daily-screening:clxs",
            "screening_run_id": run["id"],
            "screening_model": "clxs",
            "screening_branch": "clxs",
            "screening_model_key": "CLXS_10001",
            "screening_model_label": "S0001",
            "screening_input_mode": "market",
            "screening_source_scope": "market",
            "screening_signal_type": "CLXS_10001",
            "screening_signal_name": "CLXS_10001",
            "screening_period": "1d",
            "screening_params": {
                "days": 1,
                "code": None,
                "wave_opt": 1560,
                "stretch_opt": 0,
                "trend_opt": 1,
                "model_opt": 10001,
            },
        }
    ]


def test_daily_screening_service_streams_stage_events(monkeypatch):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = _make_service(fake_db=fake_db)

    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )

    class FakeClxsStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            self.kwargs["on_result_accepted"](
                {
                    "strategy": "clxs",
                    "code": "000001",
                    "name": "alpha",
                    "symbol": "sz000001",
                    "period": "1d",
                    "fire_time": datetime(2026, 3, 17, 15, 0),
                    "price": 10.5,
                    "stop_loss_price": 9.8,
                    "signal_type": "CLXS_10001",
                    "position": "BUY_LONG",
                    "remark": "",
                    "category": "",
                    "tags": [],
                }
            )
            return []

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            **service._make_strategy_hooks(run_id, config)
        ),
    )

    snapshot = service.start_run(
        {
            "model": "clxs",
            "days": 1,
            "save_pre_pools": False,
        },
        run_async=False,
    )

    events = service.session_store.get_events(snapshot["id"])

    assert events[0]["event"] == "run_started"
    assert events[1]["event"] == "stage_started"
    assert events[-2]["event"] == "stage_completed"
    assert events[-1]["event"] == "run_completed"


def test_daily_screening_service_iter_sse_keeps_new_internal_events_and_streams_legacy_compat():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    store = DailyScreeningSessionStore()
    service = _make_service(session_store=store)
    store.create_run(
        run_id="run-1",
        model="clxs",
        params={"model": "clxs"},
    )
    store.publish_event(
        "run-1",
        "run_started",
        {"model": "clxs", "params": {"model": "clxs"}},
    )
    store.publish_event(
        "run-1",
        "stage_started",
        {"stage": "clxs", "label": "CLXS_10001"},
    )
    store.publish_event(
        "run-1",
        "stage_progress",
        {"stage": "clxs", "kind": "universe", "total": 3},
    )
    store.publish_event(
        "run-1",
        "stage_progress",
        {"stage": "clxs", "kind": "stock_progress", "processed": 1, "total": 3},
    )
    store.publish_event(
        "run-1",
        "stage_progress",
        {
            "stage": "clxs",
            "kind": "hit_raw",
            "code": "000001",
            "signal_type": "CLXS_10001",
        },
    )
    store.publish_event(
        "run-1",
        "stage_progress",
        {
            "stage": "clxs",
            "kind": "accepted",
            "accepted_delta": 1,
            "code": "000001",
        },
    )
    store.publish_event(
        "run-1",
        "stage_progress",
        {
            "stage": "clxs",
            "kind": "persisted",
            "persisted_delta": 1,
            "code": "000001",
        },
    )
    store.publish_event(
        "run-1",
        "stage_completed",
        {
            "stage": "clxs",
            "label": "CLXS_10001",
            "status": "completed",
            "accepted_count": 1,
            "persisted_count": 1,
        },
    )
    store.publish_event(
        "run-1",
        "run_completed",
        {
            "status": "completed",
            "summary": {
                "accepted_count": 1,
                "persisted_count": 1,
                "stage_count": 1,
            },
            "stage_summaries": {
                "clxs": {
                    "stage": "clxs",
                    "status": "completed",
                    "accepted_count": 1,
                    "persisted_count": 1,
                }
            },
        },
    )

    internal_events = store.get_events("run-1")
    sse_events = _parse_sse_events(list(service.iter_sse("run-1", once=True)))

    assert [event["event"] for event in internal_events] == [
        "run_started",
        "stage_started",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_progress",
        "stage_completed",
        "run_completed",
    ]
    assert [event["event"] for event in sse_events] == [
        "run_started",
        "started",
        "stage_started",
        "phase_started",
        "stage_progress",
        "universe",
        "stage_progress",
        "progress",
        "stage_progress",
        "hit_raw",
        "stage_progress",
        "accepted",
        "stage_progress",
        "persisted",
        "stage_completed",
        "phase_completed",
        "run_completed",
        "summary",
        "completed",
    ]
    assert [event["id"] for event in sse_events] == [
        10,
        11,
        20,
        21,
        30,
        31,
        40,
        41,
        50,
        51,
        60,
        61,
        70,
        71,
        80,
        81,
        90,
        91,
        92,
    ]


def test_daily_screening_service_iter_sse_resume_after_internal_event_replays_pending_legacy_frame():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    store = DailyScreeningSessionStore()
    service = _make_service(session_store=store)
    store.create_run(
        run_id="run-3",
        model="clxs",
        params={"model": "clxs"},
    )
    store.publish_event(
        "run-3",
        "run_started",
        {"model": "clxs", "params": {"model": "clxs"}},
    )
    store.publish_event(
        "run-3",
        "stage_started",
        {"stage": "clxs", "label": "CLXS_10001"},
    )

    initial_events = _parse_sse_events(list(service.iter_sse("run-3", once=True)))
    resumed_events = _parse_sse_events(
        list(service.iter_sse("run-3", after=initial_events[0]["id"], once=True))
    )

    assert initial_events[0]["event"] == "run_started"
    assert initial_events[1]["event"] == "started"
    assert resumed_events[0]["event"] == "started"
    assert resumed_events[0]["id"] == 11
    assert resumed_events[1]["event"] == "stage_started"
    assert resumed_events[2]["event"] == "phase_started"


def test_daily_screening_service_iter_sse_maps_run_failed_to_legacy_error_and_completed():
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    store = DailyScreeningSessionStore()
    service = _make_service(session_store=store)
    store.create_run(
        run_id="run-2",
        model="clxs",
        params={"model": "clxs"},
    )
    store.publish_event(
        "run-2",
        "run_started",
        {"model": "clxs", "params": {"model": "clxs"}},
    )
    store.publish_event(
        "run-2",
        "stage_started",
        {"stage": "clxs", "label": "CLXS_10001"},
    )
    store.publish_event(
        "run-2",
        "run_failed",
        {
            "status": "failed",
            "error": "boom",
            "stage_summaries": {
                "clxs": {"stage": "clxs", "status": "failed", "error": "boom"}
            },
        },
    )

    sse_events = _parse_sse_events(list(service.iter_sse("run-2", once=True)))

    assert [event["event"] for event in sse_events] == [
        "run_started",
        "started",
        "stage_started",
        "phase_started",
        "run_failed",
        "error",
        "completed",
    ]
    assert sse_events[-2]["data"]["data"]["message"] == "boom"
    assert sse_events[-1]["data"]["data"]["status"] == "failed"


def test_daily_screening_service_passes_filtered_pre_pool_query_to_chanlun(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = _make_service(fake_db=fake_db)

    captured = {}
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )

    class FakeChanlunStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            **service._make_strategy_hooks(run_id, config)
        ),
    )

    snapshot = service.start_run(
        {
            "model": "chanlun",
            "days": 1,
            "input_mode": "remark_filtered_pre_pools",
            "pre_pool_remark": "daily-screening:clxs",
            "save_pre_pools": False,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])

    assert run["status"] == "completed"
    assert captured["pre_pool_query"] == {"remark": "daily-screening:clxs"}


def test_daily_screening_service_runs_all_pipeline_and_persists_model_metadata(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = _make_service(fake_db=fake_db)

    persisted = []
    captured = {}
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: persisted.append(kwargs),
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )

    class FakeClxsStrategy:
        def __init__(self, model_opt, **kwargs):
            self.model_opt = model_opt
            self.kwargs = kwargs

        async def screen(self, days=1, code=None, **_kwargs):
            signal_type = f"CLXS_{self.model_opt}"
            payload = {
                "strategy": "clxs",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": signal_type,
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type=signal_type,
                    position="BUY_LONG",
                    remark="",
                    category="",
                )
            ]

    class FakeChanlunStrategy:
        def __init__(self, signal_types, **kwargs):
            self.signal_types = signal_types
            self.kwargs = kwargs

        async def screen(self, **kwargs):
            captured.setdefault("chanlun_calls", []).append(
                {
                    "code": kwargs.get("code"),
                    "symbol": kwargs.get("symbol"),
                    "pre_pool_query": kwargs.get("pre_pool_query"),
                }
            )
            results = []
            labels = {
                "buy_zs_huila": "回拉中枢上涨",
                "macd_bullish_divergence": "MACD看涨背驰",
            }
            for signal_type in self.signal_types:
                payload = {
                    "strategy": "chanlun_service",
                    "code": "000001",
                    "name": "alpha",
                    "symbol": "sz000001",
                    "period": "30m",
                    "fire_time": datetime(2026, 3, 17, 15, 0),
                    "price": 10.8,
                    "stop_loss_price": 9.6,
                    "signal_type": signal_type,
                    "position": "BUY_LONG",
                    "remark": labels[signal_type],
                    "category": "CLXS_8",
                    "tags": [],
                }
                self.kwargs["on_result_accepted"](payload)
                results.append(
                    SimpleNamespace(
                        code="000001",
                        name="alpha",
                        symbol="sz000001",
                        period="30m",
                        fire_time=datetime(2026, 3, 17, 15, 0),
                        price=10.8,
                        stop_loss_price=9.6,
                        signal_type=signal_type,
                        position="BUY_LONG",
                        remark=labels[signal_type],
                        category="CLXS_8",
                    )
                )
            return results

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            model_opt=config["model_opt"],
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            signal_types=config["signal_types"],
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_run_shouban30_agg90_stage",
        lambda run_id, config: [],
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_run_market_flags_stage",
        lambda run_id, config: [],
        raising=False,
    )

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "chanlun_signal_types": [
                "buy_zs_huila",
                "macd_bullish_divergence",
            ],
            "save_pre_pools": True,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])

    assert run["status"] == "completed"
    assert run["progress"]["accepted"] == 14
    assert run["progress"]["persisted"] == 14
    assert captured["chanlun_calls"] == [
        {
            "code": "000001",
            "symbol": "sz000001",
            "pre_pool_query": None,
        }
    ]
    assert [item["model_key"] for item in run["results"][:12]] == [
        f"CLXS_{model_opt}" for model_opt in FULL_CLXS_MODEL_OPTS
    ]
    assert [
        item["model_label"] for item in run["results"][:12]
    ] == FULL_CLXS_MODEL_LABELS
    assert [item["branch"] for item in run["results"][:12]] == ["clxs"] * 12
    assert [item["model_key"] for item in run["results"][12:]] == [
        "buy_zs_huila",
        "macd_bullish_divergence",
    ]
    clxs_persisted = [
        item for item in persisted if item["remark"] == "daily-screening:clxs"
    ]
    chanlun_persisted = [
        item for item in persisted if item["remark"] == "daily-screening:chanlun"
    ]
    assert len(clxs_persisted) == 12
    assert len(chanlun_persisted) == 2
    assert clxs_persisted[0]["screening_model_key"] == "CLXS_10001"
    assert clxs_persisted[0]["screening_model_label"] == "S0001"
    assert clxs_persisted[0]["screening_params"]["model_opt"] == 10001
    assert clxs_persisted[-1]["screening_model_key"] == "CLXS_10012"
    assert clxs_persisted[-1]["screening_model_label"] == "S0012"
    assert clxs_persisted[-1]["screening_params"]["model_opt"] == 10012
    assert chanlun_persisted[0]["screening_model_key"] == "buy_zs_huila"
    assert chanlun_persisted[1]["screening_model_key"] == "macd_bullish_divergence"


def test_daily_screening_service_all_mode_keeps_intermediate_pre_pool_writes(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = _make_service(fake_db=fake_db)

    persisted = []
    captured = {}
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: persisted.append(kwargs),
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )

    class FakeClxsStrategy:
        def __init__(self, model_opt, **kwargs):
            self.model_opt = model_opt
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            signal_type = f"CLXS_{self.model_opt}"
            payload = {
                "strategy": "clxs",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": signal_type,
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type=signal_type,
                    position="BUY_LONG",
                    remark="",
                    category="",
                )
            ]

    class FakeChanlunStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **kwargs):
            captured["chanlun_call"] = {
                "code": kwargs.get("code"),
                "symbol": kwargs.get("symbol"),
                "pre_pool_query": kwargs.get("pre_pool_query"),
            }
            return []

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            model_opt=config["model_opt"],
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_run_shouban30_agg90_stage",
        lambda run_id, config: [],
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_run_market_flags_stage",
        lambda run_id, config: [],
        raising=False,
    )

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "save_pre_pools": False,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])

    assert run["status"] == "completed"
    assert run["params"]["clxs"]["save_pre_pools"] is True
    assert run["params"]["chanlun"]["save_pre_pools"] is True
    assert captured["chanlun_call"] == {
        "code": "000001",
        "symbol": "sz000001",
        "pre_pool_query": None,
    }
    assert len(persisted) == 12
    assert {item["remark"] for item in persisted} == {"daily-screening:clxs"}
    assert [item["screening_model_key"] for item in persisted] == [
        f"CLXS_{model_opt}" for model_opt in FULL_CLXS_MODEL_OPTS
    ]
    assert [
        item["screening_model_label"] for item in persisted
    ] == FULL_CLXS_MODEL_LABELS


def test_daily_screening_service_all_mode_runs_chanlun_against_current_clxs_universe(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    service = _make_service()

    captured = {"chanlun_calls": []}
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: None,
    )

    class FakeClxsStrategy:
        def __init__(self, model_opt, **kwargs):
            self.model_opt = model_opt
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            code = "000001" if self.model_opt == 10001 else "000002"
            signal_type = f"CLXS_{self.model_opt}"
            payload = {
                "strategy": "clxs",
                "code": code,
                "name": f"name-{code}",
                "symbol": f"sz{code}",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": signal_type,
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code=code,
                    name=f"name-{code}",
                    symbol=f"sz{code}",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type=signal_type,
                    position="BUY_LONG",
                    remark="",
                    category="",
                )
            ]

    class FakeChanlunStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **kwargs):
            captured["chanlun_calls"].append(
                {
                    "code": kwargs.get("code"),
                    "symbol": kwargs.get("symbol"),
                    "pre_pool_query": kwargs.get("pre_pool_query"),
                }
            )
            return []

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            model_opt=config["model_opt"],
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_run_shouban30_agg90_stage",
        lambda run_id, config: [],
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_run_market_flags_stage",
        lambda run_id, config: [],
        raising=False,
    )

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "clxs_model_opts": [10001, 10002],
            "chanlun_signal_types": ["buy_zs_huila"],
            "save_pre_pools": False,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])

    assert run["status"] == "completed"
    assert captured["chanlun_calls"] == [
        {
            "code": "000001",
            "symbol": "sz000001",
            "pre_pool_query": None,
        },
        {
            "code": "000002",
            "symbol": "sz000002",
            "pre_pool_query": None,
        },
    ]


def test_daily_screening_service_all_mode_executes_special_stage_handlers(
    monkeypatch,
):
    service = _make_service()

    captured = {"special_stages": []}
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: None,
    )

    class FakeClxsStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            payload = {
                "strategy": "clxs",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": "CLXS_10001",
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type="CLXS_10001",
                    position="BUY_LONG",
                    remark="",
                    category="",
                )
            ]

    class FakeChanlunStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            return []

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )

    def fake_shouban30_handler(run_id, config):
        captured["special_stages"].append(config["model"])
        return [
            SimpleNamespace(
                code="000002",
                name="beta",
                symbol="sz000002",
                period="90d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="agg90",
                position="BUY_LONG",
                remark="90日聚合",
                category="shouban30_agg90",
            )
        ]

    def fake_market_flags_handler(run_id, config):
        captured["special_stages"].append(config["model"])
        return [
            SimpleNamespace(
                code="000003",
                name="gamma",
                symbol="sz000003",
                period="1d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="credit_subject",
                position="BUY_LONG",
                remark="融资标的",
                category="credit_subject",
            )
        ]

    monkeypatch.setattr(
        service,
        "_run_shouban30_agg90_stage",
        fake_shouban30_handler,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_run_market_flags_stage",
        fake_market_flags_handler,
        raising=False,
    )

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "clxs_model_opts": [10001],
            "chanlun_signal_types": ["buy_zs_huila"],
            "save_pre_pools": False,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])

    assert run["status"] == "completed"
    assert captured["special_stages"] == ["shouban30_agg90", "market_flags"]
    assert set(run["stage_summaries"]) == {
        "clxs",
        "chanlun",
        "shouban30_agg90",
        "market_flags",
    }
    assert run["progress"]["accepted"] == 3
    assert [item["branch"] for item in run["results"]] == [
        "clxs",
        "shouban30_agg90",
        "market_flags",
    ]


def test_daily_screening_service_persists_run_scope_read_model_for_all_pipeline(
    monkeypatch,
):
    service, repository, _screening_db = _make_service_with_screening_repo()

    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_database_outputs",
        lambda results, config: None,
    )
    monkeypatch.setattr(
        "freshquant.daily_screening.service._save_pre_pool",
        lambda **kwargs: None,
    )

    class FakeClxsStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            payload = {
                "strategy": "clxs",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "1d",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.5,
                "stop_loss_price": 9.8,
                "signal_type": "CLXS_10001",
                "position": "BUY_LONG",
                "remark": "",
                "category": "",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="1d",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.5,
                    stop_loss_price=9.8,
                    signal_type="CLXS_10001",
                    position="BUY_LONG",
                    remark="",
                    category="",
                )
            ]

    class FakeChanlunStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def screen(self, **_kwargs):
            payload = {
                "strategy": "chanlun_service",
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "period": "30m",
                "fire_time": datetime(2026, 3, 17, 15, 0),
                "price": 10.8,
                "stop_loss_price": 9.6,
                "signal_type": "buy_zs_huila",
                "position": "BUY_LONG",
                "remark": "回拉中枢上涨",
                "category": "chanlun_service",
                "tags": [],
            }
            self.kwargs["on_result_accepted"](payload)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="30m",
                    fire_time=datetime(2026, 3, 17, 15, 0),
                    price=10.8,
                    stop_loss_price=9.6,
                    signal_type="buy_zs_huila",
                    position="BUY_LONG",
                    remark="回拉中枢上涨",
                    category="chanlun_service",
                )
            ]

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        lambda run_id, config: FakeChanlunStrategy(
            **service._make_strategy_hooks(run_id, config),
        ),
    )
    monkeypatch.setattr(
        service,
        "_run_shouban30_agg90_stage",
        lambda run_id, config: [
            SimpleNamespace(
                code="000001",
                name="alpha",
                symbol="sz000001",
                period="90d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="agg90",
                position="BUY_LONG",
                remark="90日聚合",
                category="shouban30_agg90",
                providers=["xgb", "jygs"],
            )
        ],
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_run_market_flags_stage",
        lambda run_id, config: [
            SimpleNamespace(
                code="000001",
                name="alpha",
                symbol="sz000001",
                period="1d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="credit_subject",
                position="BUY_LONG",
                remark="融资标的",
                category="credit_subject",
            ),
            SimpleNamespace(
                code="000001",
                name="alpha",
                symbol="sz000001",
                period="1d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="quality_subject",
                position="BUY_LONG",
                remark="优质标的",
                category="quality_subject",
            ),
            SimpleNamespace(
                code="000001",
                name="alpha",
                symbol="sz000001",
                period="1d",
                fire_time=datetime(2026, 3, 17, 15, 0),
                price=None,
                stop_loss_price=None,
                signal_type="near_long_term_ma",
                position="BUY_LONG",
                remark="均线附近 ma250",
                category="near_long_term_ma",
            ),
        ],
        raising=False,
    )

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "clxs_model_opts": [10001],
            "chanlun_signal_types": ["buy_zs_huila"],
            "save_pre_pools": False,
        },
        run_async=False,
    )

    run = service.get_run(snapshot["id"])
    scope = f"run:{run['id']}"

    summary = repository.query_scope_summary(run_id=run["id"], scope=scope)
    memberships = repository.get_stock_detail_memberships(
        run_id=run["id"],
        scope=scope,
        code="000001",
    )
    snapshots = repository.query_scope_stocks(run_id=run["id"], scope=scope)

    assert run["status"] == "completed"
    assert summary["stage_counts"] == {
        "chanlun": 1,
        "clxs": 1,
        "market_flags": 3,
        "shouban30_agg90": 1,
    }
    assert {(item["stage"], item["signal_type"]) for item in memberships} == {
        ("clxs", "CLXS_10001"),
        ("chanlun", "buy_zs_huila"),
        ("shouban30_agg90", "agg90"),
        ("market_flags", "credit_subject"),
        ("market_flags", "quality_subject"),
        ("market_flags", "near_long_term_ma"),
    }
    assert len(snapshots) == 1
    assert snapshots[0]["selected_by"] == {
        "clxs": True,
        "chanlun": True,
        "shouban30_agg90": True,
        "credit_subject": True,
        "quality_subject": True,
        "near_long_term_ma": True,
    }
    assert snapshots[0]["clxs_models"] == ["CLXS_10001"]
    assert snapshots[0]["chanlun_variants"] == [
        {"signal_type": "buy_zs_huila", "period": "30m"}
    ]
    assert snapshots[0]["shouban30_providers"] == ["jygs", "xgb"]


def test_daily_screening_service_materializes_trade_date_scope_for_dagster_runs():
    service, repository, _screening_db = _make_service_with_screening_repo()

    service._persist_run_scope_read_model(
        "run-dagster-1",
        "clxs",
        {
            "model": "clxs",
            "model_opt": 10001,
            "trade_date": "2026-03-18",
            "_trigger_type": "dagster_schedule",
            "remark": "",
        },
        [
            SimpleNamespace(
                code="000001",
                name="alpha",
                symbol="sz000001",
                period="1d",
                fire_time=datetime(2026, 3, 18, 15, 0),
                price=10.5,
                stop_loss_price=9.8,
                signal_type="CLXS_10001",
                position="BUY_LONG",
                remark="",
                category="",
            )
        ],
    )

    official_scope = "trade_date:2026-03-18"
    summary = repository.query_scope_summary(
        run_id=official_scope,
        scope=official_scope,
    )
    memberships = repository.get_stock_detail_memberships(
        run_id=official_scope,
        scope=official_scope,
        code="000001",
    )
    snapshots = repository.query_scope_stocks(
        run_id=official_scope,
        scope=official_scope,
    )

    assert summary["stage_counts"] == {"clxs": 1}
    assert memberships[0]["origin_run_id"] == "run-dagster-1"
    assert snapshots[0]["origin_run_id"] == "run-dagster-1"
    assert snapshots[0]["clxs_models"] == ["CLXS_10001"]


def _seed_run_scope_snapshot_fixture(
    repository,
    *,
    run_id="run-1",
    scope=None,
    origin_run_id=None,
):
    scope = scope or f"run:{run_id}"
    origin_run_id = origin_run_id or run_id
    repository.replace_stage_memberships(
        run_id=run_id,
        stage="clxs",
        scope=scope,
        memberships=[
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "clxs",
                "model_key": "CLXS_10001",
                "model_label": "S0001",
                "signal_type": "CLXS_10001",
                "period": "1d",
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000002",
                "name": "beta",
                "symbol": "sz000002",
                "branch": "clxs",
                "model_key": "CLXS_10002",
                "model_label": "S0002",
                "signal_type": "CLXS_10002",
                "period": "1d",
            },
        ],
    )
    repository.replace_stage_memberships(
        run_id=run_id,
        stage="chanlun",
        scope=scope,
        memberships=[
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "chanlun",
                "model_key": "buy_zs_huila",
                "model_label": "回拉中枢上涨",
                "signal_type": "buy_zs_huila",
                "period": "30m",
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000003",
                "name": "gamma",
                "symbol": "sz000003",
                "branch": "chanlun",
                "model_key": "macd_bullish_divergence",
                "model_label": "MACD看涨背驰",
                "signal_type": "macd_bullish_divergence",
                "period": "1d",
            },
        ],
    )
    repository.replace_stage_memberships(
        run_id=run_id,
        stage="shouban30_agg90",
        scope=scope,
        memberships=[
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "shouban30_agg90",
                "model_key": "agg90",
                "model_label": "90日聚合",
                "signal_type": "agg90",
                "period": "90d",
                "providers": ["xgb", "jygs"],
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000003",
                "name": "gamma",
                "symbol": "sz000003",
                "branch": "shouban30_agg90",
                "model_key": "agg90",
                "model_label": "90日聚合",
                "signal_type": "agg90",
                "period": "90d",
                "providers": ["jygs"],
            },
        ],
    )
    repository.replace_stage_memberships(
        run_id=run_id,
        stage="market_flags",
        scope=scope,
        memberships=[
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "market_flags",
                "model_key": "credit_subject",
                "model_label": "融资标的",
                "signal_type": "credit_subject",
                "period": "1d",
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "market_flags",
                "model_key": "near_long_term_ma",
                "model_label": "均线附近",
                "signal_type": "near_long_term_ma",
                "period": "1d",
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000003",
                "name": "gamma",
                "symbol": "sz000003",
                "branch": "market_flags",
                "model_key": "quality_subject",
                "model_label": "优质标的",
                "signal_type": "quality_subject",
                "period": "1d",
            },
        ],
    )
    repository.upsert_stock_snapshots(
        run_id=run_id,
        scope=scope,
        snapshots=[
            {
                "origin_run_id": origin_run_id,
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "selected_by": {
                    "clxs": True,
                    "chanlun": True,
                    "shouban30_agg90": True,
                    "credit_subject": True,
                    "quality_subject": False,
                    "near_long_term_ma": True,
                },
                "clxs_models": ["CLXS_10001"],
                "chanlun_variants": [{"signal_type": "buy_zs_huila", "period": "30m"}],
                "shouban30_providers": ["jygs", "xgb"],
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000002",
                "name": "beta",
                "symbol": "sz000002",
                "selected_by": {
                    "clxs": True,
                    "chanlun": False,
                    "shouban30_agg90": False,
                    "credit_subject": False,
                    "quality_subject": False,
                    "near_long_term_ma": False,
                },
                "clxs_models": ["CLXS_10002"],
                "chanlun_variants": [],
                "shouban30_providers": [],
            },
            {
                "origin_run_id": origin_run_id,
                "code": "000003",
                "name": "gamma",
                "symbol": "sz000003",
                "selected_by": {
                    "clxs": False,
                    "chanlun": True,
                    "shouban30_agg90": True,
                    "credit_subject": False,
                    "quality_subject": True,
                    "near_long_term_ma": False,
                },
                "clxs_models": [],
                "chanlun_variants": [
                    {"signal_type": "macd_bullish_divergence", "period": "1d"}
                ],
                "shouban30_providers": ["jygs"],
            },
        ],
    )
    return scope


def test_daily_screening_service_get_scope_summary_uses_run_scope():
    service, repository, _screening_db = _make_service_with_screening_repo()
    scope = _seed_run_scope_snapshot_fixture(repository)

    summary = service.get_scope_summary("run-1")

    assert summary["run_id"] == "run-1"
    assert summary["scope"] == scope
    assert summary["stage_counts"] == {
        "clxs": 2,
        "chanlun": 2,
        "shouban30_agg90": 2,
        "market_flags": 3,
    }
    assert summary["stock_codes"] == ["000001", "000002", "000003"]


def test_daily_screening_service_get_scopes_and_latest_scope_from_repository_runs():
    service, repository, _screening_db = _make_service_with_screening_repo()
    repository.save_run(
        run_id="run-1",
        id="run-1",
        status="completed",
        started_at="2026-03-17T19:00:00",
        trigger_type="dagster_schedule",
        params={"trade_date": "2026-03-17"},
    )
    repository.save_run(
        run_id="run-2",
        id="run-2",
        status="running",
        started_at="2026-03-18T19:30:00",
    )
    repository.save_run(
        run_id="run-3",
        id="run-3",
        status="completed",
        started_at="2026-03-18T19:00:00",
        trigger_type="dagster_schedule",
        params={"trade_date": "2026-03-18"},
    )

    scopes = service.get_scopes()
    latest = service.get_latest_scope()

    assert [item["run_id"] for item in scopes["items"][:2]] == [
        "trade_date:2026-03-18",
        "trade_date:2026-03-17",
    ]
    assert scopes["items"][0]["scope"] == "trade_date:2026-03-18"
    assert scopes["items"][0]["is_latest"] is True
    assert scopes["items"][0]["scope_kind"] == "trade_date"
    assert [item["run_id"] for item in scopes["items"][2:]] == [
        "run-2",
        "run-3",
        "run-1",
    ]
    assert latest["run_id"] == "trade_date:2026-03-18"
    assert latest["scope"] == "trade_date:2026-03-18"
    assert latest["label"] == "正式 2026-03-18"
    assert latest["is_latest"] is True
    assert latest["scope_kind"] == "trade_date"
    assert latest["source_run_id"] == "run-3"


def test_daily_screening_service_get_latest_scope_prefers_materialized_trade_date_scope():
    service, repository, _screening_db = _make_service_with_screening_repo()
    repository.upsert_stock_snapshots(
        scope_id="trade_date:2026-03-18",
        trade_date="2026-03-18",
        snapshots=[{"code": "000001", "name": "alpha"}],
    )
    repository.upsert_stock_snapshots(
        scope_id="trade_date:2026-03-17",
        trade_date="2026-03-17",
        snapshots=[{"code": "000002", "name": "beta"}],
    )
    repository.save_run(
        run_id="run-1",
        id="run-1",
        status="completed",
        started_at="2026-03-16T19:00:00",
    )

    scopes = service.get_scopes()
    latest = service.get_latest_scope()

    assert [item["run_id"] for item in scopes["items"][:2]] == [
        "trade_date:2026-03-18",
        "trade_date:2026-03-17",
    ]
    assert latest["run_id"] == "trade_date:2026-03-18"
    assert latest["scope_kind"] == "trade_date"


def _seed_condition_scope_fixture(
    repository,
    *,
    scope_id="trade_date:2026-03-18",
    trade_date="2026-03-18",
):
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="cls:S0001",
        codes=[{"code": "000001", "name": "alpha", "symbol": "sz000001"}],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="base:union",
        codes=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000002", "name": "beta", "symbol": "sz000002"},
        ],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="hot:30d",
        codes=[{"code": "000001", "name": "alpha", "symbol": "sz000001"}],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="flag:quality_subject",
        codes=[{"code": "000002", "name": "beta", "symbol": "sz000002"}],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="chanlun_period:30m",
        codes=[{"code": "000001", "name": "alpha", "symbol": "sz000001"}],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="chanlun_signal:buy_zs_huila",
        codes=[{"code": "000001", "name": "alpha", "symbol": "sz000001"}],
    )
    repository.upsert_stock_snapshots(
        scope_id=scope_id,
        trade_date=trade_date,
        snapshots=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000002", "name": "beta", "symbol": "sz000002"},
            {"code": "000003", "name": "gamma", "symbol": "sz000003"},
        ],
    )
    return scope_id


def _seed_condition_scope_with_metrics_fixture(
    repository,
    *,
    scope_id="trade_date:2026-03-19",
    trade_date="2026-03-19",
):
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="base:union",
        codes=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000002", "name": "beta", "symbol": "sz000002"},
        ],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="flag:credit_subject",
        codes=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000003", "name": "gamma", "symbol": "sz000003"},
        ],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="chanlun_period:30m",
        codes=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000002", "name": "beta", "symbol": "sz000002"},
        ],
    )
    repository.replace_condition_memberships(
        scope_id=scope_id,
        condition_key="chanlun_signal:buy_zs_huila",
        codes=[
            {"code": "000001", "name": "alpha", "symbol": "sz000001"},
            {"code": "000003", "name": "gamma", "symbol": "sz000003"},
        ],
    )
    repository.upsert_stock_snapshots(
        scope_id=scope_id,
        trade_date=trade_date,
        snapshots=[
            {
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "higher_multiple": 2.4,
                "segment_multiple": 2.7,
                "bi_gain_percent": 18.0,
            },
            {
                "code": "000002",
                "name": "beta",
                "symbol": "sz000002",
                "higher_multiple": 3.6,
                "segment_multiple": 3.1,
                "bi_gain_percent": 25.0,
            },
            {
                "code": "000003",
                "name": "gamma",
                "symbol": "sz000003",
                "higher_multiple": 1.8,
                "segment_multiple": 1.6,
                "bi_gain_percent": 12.0,
            },
        ],
    )
    return scope_id


def test_daily_screening_service_returns_unified_filter_catalog():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_condition_scope_fixture(repository)

    payload = service.get_filter_catalog("trade_date:2026-03-18")

    assert payload["scope_id"] == "trade_date:2026-03-18"
    assert "base:union" in payload["condition_keys"]
    hot_windows = {
        item["key"]: item["count"] for item in payload["groups"]["hot_windows"]
    }
    market_flags = {
        item["key"]: item["count"] for item in payload["groups"]["market_flags"]
    }
    chanlun_periods = {
        item["key"]: item["count"] for item in payload["groups"]["chanlun_periods"]
    }
    chanlun_signals = {
        item["key"]: item["count"] for item in payload["groups"]["chanlun_signals"]
    }
    cls_models = {
        item["key"]: item["count"] for item in payload["groups"]["cls_models"]
    }
    cls_groups = {
        item["key"]: item["count"] for item in payload["groups"]["cls_groups"]
    }

    assert hot_windows == {
        "hot:30d": 1,
        "hot:45d": 0,
        "hot:60d": 0,
        "hot:90d": 0,
    }
    assert market_flags == {
        "flag:near_long_term_ma": 0,
        "flag:quality_subject": 1,
        "flag:credit_subject": 0,
    }
    assert chanlun_periods == {
        "chanlun_period:30m": 1,
        "chanlun_period:60m": 0,
        "chanlun_period:1d": 0,
    }
    assert chanlun_signals["chanlun_signal:buy_zs_huila"] == 1
    assert chanlun_signals["chanlun_signal:macd_bullish_divergence"] == 0
    assert cls_models["cls:S0001"] == 1
    assert cls_models["cls:S0002"] == 0
    assert cls_groups == {
        "cls_group:erbai": 1,
        "cls_group:sanmai": 0,
        "cls_group:yali_support": 0,
        "cls_group:beichi": 0,
        "cls_group:break_pullback": 0,
    }


def test_query_scope_defaults_to_base_union_when_no_filters_selected():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_condition_scope_fixture(repository)

    result = service.query_scope("trade_date:2026-03-18", {})

    assert result["run_id"] == "trade_date:2026-03-18"
    assert result["scope"] == "trade_date:2026-03-18"
    assert [row["code"] for row in result["rows"]] == ["000001", "000002"]
    assert result["total"] == 2


def test_query_scope_applies_numeric_thresholds_inside_base_union():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_condition_scope_with_metrics_fixture(repository)

    result = service.query_scope(
        "trade_date:2026-03-19",
        {
            "condition_keys": ["flag:credit_subject"],
            "metric_filters": {"higher_multiple_lte": 2.5},
        },
    )

    assert [row["code"] for row in result["rows"]] == ["000001"]


def test_query_scope_intersects_chanlun_period_and_signal_independently():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_condition_scope_with_metrics_fixture(repository)

    result = service.query_scope(
        "trade_date:2026-03-19",
        {
            "condition_keys": [
                "chanlun_period:30m",
                "chanlun_signal:buy_zs_huila",
            ]
        },
    )

    assert [row["code"] for row in result["rows"]] == ["000001"]


def test_query_scope_filters_cls_groups_from_memberships_when_snapshots_lack_cls_models():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_condition_scope_fixture(repository)

    result = service.query_scope(
        "trade_date:2026-03-18",
        {
            "clxs_models": ["S0001"],
        },
    )

    assert [row["code"] for row in result["rows"]] == ["000001"]


def test_daily_screening_service_builds_universe_without_st_and_bj(monkeypatch):
    service = _make_service()

    import freshquant.instrument.stock as stock_module

    monkeypatch.setattr(
        stock_module,
        "fq_inst_fetch_stock_list",
        lambda: [
            {"code": "000001", "name": "alpha"},
            {"code": "430001", "name": "bj-alpha"},
            {"code": "000002", "name": "*ST beta"},
            {"code": "600000", "name": "gamma"},
        ],
    )

    universe = service.build_universe("2026-03-18")

    assert universe == ["000001", "600000"]


def test_daily_screening_service_builds_hot_window_memberships_from_aggregated_sources(
    monkeypatch,
):
    service = _make_service()

    monkeypatch.setattr(
        service,
        "_load_shouban30_agg90_rows",
        lambda config: [
            {
                "code6": "000001",
                "name": "alpha",
                "provider": "xgb",
                "plate_key": "p1",
                "as_of_date": "2026-03-18",
            },
            {
                "code6": "000001",
                "name": "alpha",
                "provider": "jygs",
                "plate_key": "p2",
                "as_of_date": "2026-03-18",
            },
            {
                "code6": "000002",
                "name": "beta",
                "provider": "xgb",
                "plate_key": "p3",
                "as_of_date": "2026-03-18",
            },
        ],
    )

    memberships = service.build_hot_window_memberships(
        "2026-03-18",
        days=30,
        candidate_codes=["000001"],
    )

    assert memberships == [
        {
            "condition_key": "hot:30d",
            "code": "000001",
            "name": "alpha",
            "symbol": "sz000001",
            "providers": ["jygs", "xgb"],
            "trade_date": "2026-03-18",
        }
    ]


def test_daily_screening_service_query_scope_applies_intersection_and_source_filters():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_run_scope_snapshot_fixture(repository)

    payload = {
        "selected_sets": ["clxs", "chanlun", "shouban30_agg90", "credit_subject"],
        "clxs_models": ["CLXS_10001"],
        "chanlun_signal_types": ["buy_zs_huila"],
        "chanlun_periods": ["30m"],
        "shouban30_providers": ["xgb"],
    }

    result = service.query_scope("run-1", payload)

    assert result["run_id"] == "run-1"
    assert result["scope"] == "run:run-1"
    assert result["total"] == 1
    assert [row["code"] for row in result["rows"]] == ["000001"]


def test_daily_screening_service_get_stock_detail_returns_snapshot_and_memberships():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_run_scope_snapshot_fixture(repository)
    hot_reason_rows = [
        {
            "date": "2026-03-18",
            "time": "09:31",
            "provider": "xgb",
            "plate_name": "机器人",
            "stock_reason": "情绪修复",
            "plate_reason": "机器人催化",
        }
    ]
    from freshquant.tests import test_daily_screening_service as test_module

    def fake_query_stock_hot_reason_rows(*, code6, provider, limit):
        assert code6 == "000001"
        assert provider == "all"
        assert limit == 0
        return hot_reason_rows

    import freshquant.daily_screening.service as service_module

    original_query_stock_hot_reason_rows = getattr(
        service_module,
        "query_stock_hot_reason_rows",
        None,
    )
    service_module.query_stock_hot_reason_rows = fake_query_stock_hot_reason_rows

    try:
        detail = service.get_stock_detail("run-1", "000001")
    finally:
        if original_query_stock_hot_reason_rows is None:
            delattr(service_module, "query_stock_hot_reason_rows")
        else:
            service_module.query_stock_hot_reason_rows = (
                original_query_stock_hot_reason_rows
            )

    assert detail["run_id"] == "run-1"
    assert detail["scope"] == "run:run-1"
    assert detail["snapshot"]["code"] == "000001"
    assert detail["snapshot"]["selected_by"]["credit_subject"] is True
    assert {(item["stage"], item["signal_type"]) for item in detail["memberships"]} == {
        ("clxs", "CLXS_10001"),
        ("chanlun", "buy_zs_huila"),
        ("shouban30_agg90", "agg90"),
        ("market_flags", "credit_subject"),
        ("market_flags", "near_long_term_ma"),
    }
    assert [item["signal_type"] for item in detail["clxs_memberships"]] == [
        "CLXS_10001"
    ]
    assert [item["signal_type"] for item in detail["chanlun_memberships"]] == [
        "buy_zs_huila"
    ]
    assert [item["signal_type"] for item in detail["agg90_memberships"]] == ["agg90"]
    assert {item["signal_type"] for item in detail["market_flag_memberships"]} == {
        "credit_subject",
        "near_long_term_ma",
    }
    assert detail["hot_reasons"] == hot_reason_rows


def test_daily_screening_service_supports_trade_date_scope_detail_and_pre_pool():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_run_scope_snapshot_fixture(
        repository,
        run_id="trade_date:2026-03-18",
        scope="trade_date:2026-03-18",
        origin_run_id="run-dagster-1",
    )
    persisted = []

    import freshquant.daily_screening.service as service_module

    original_save_pre_pool = service_module._save_pre_pool
    service_module._save_pre_pool = lambda **kwargs: persisted.append(kwargs)
    try:
        detail = service.get_stock_detail("trade_date:2026-03-18", "000001")
        payload = service.add_to_pre_pool(
            {"run_id": "trade_date:2026-03-18", "code": "000001"}
        )
    finally:
        service_module._save_pre_pool = original_save_pre_pool

    assert detail["run_id"] == "trade_date:2026-03-18"
    assert detail["scope"] == "trade_date:2026-03-18"
    assert detail["snapshot"]["origin_run_id"] == "run-dagster-1"
    assert payload == {
        "code": "000001",
        "category": "CLXS_10001",
        "remark": "daily-screening:clxs",
    }
    assert persisted[0]["screening_run_id"] == "run-dagster-1"
    assert persisted[0]["screening_source_scope"] == "trade_date:2026-03-18"
    assert persisted[0]["screening_input_mode"] == "trade_date_scope"


def test_daily_screening_service_add_to_pre_pool_uses_scope_snapshot_and_memberships():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_run_scope_snapshot_fixture(repository)
    persisted = []

    import freshquant.daily_screening.service as service_module

    original_save_pre_pool = service_module._save_pre_pool
    service_module._save_pre_pool = lambda **kwargs: persisted.append(kwargs)
    try:
        payload = service.add_to_pre_pool({"run_id": "run-1", "code": "000001"})
    finally:
        service_module._save_pre_pool = original_save_pre_pool

    assert payload == {
        "code": "000001",
        "category": "CLXS_10001",
        "remark": "daily-screening:clxs",
    }
    assert len(persisted) == 1
    assert persisted[0]["code"] == "000001"
    assert persisted[0]["category"] == "CLXS_10001"
    assert persisted[0]["remark"] == "daily-screening:clxs"
    assert persisted[0]["name"] == "alpha"
    assert persisted[0]["screening_run_id"] == "run-1"
    assert persisted[0]["screening_branch"] == "clxs"
    assert persisted[0]["screening_model_key"] == "CLXS_10001"
    assert persisted[0]["screening_model_label"] == "S0001"


def test_daily_screening_service_add_batch_to_pre_pool_uses_query_filters():
    service, repository, _screening_db = _make_service_with_screening_repo()
    _seed_run_scope_snapshot_fixture(repository)
    persisted = []

    import freshquant.daily_screening.service as service_module

    original_save_pre_pool = service_module._save_pre_pool
    service_module._save_pre_pool = lambda **kwargs: persisted.append(kwargs)
    try:
        result = service.add_batch_to_pre_pool(
            {
                "run_id": "run-1",
                "selected_sets": ["clxs", "chanlun", "shouban30_agg90"],
                "clxs_models": ["CLXS_10001"],
                "chanlun_signal_types": ["buy_zs_huila"],
                "chanlun_periods": ["30m"],
                "shouban30_providers": ["xgb"],
            }
        )
    finally:
        service_module._save_pre_pool = original_save_pre_pool

    assert result == {"created_count": 1, "codes": ["000001"]}
    assert len(persisted) == 1
    assert persisted[0]["code"] == "000001"


def test_daily_screening_service_builds_market_flag_memberships_without_run_session(
    monkeypatch,
):
    service = _make_service()

    monkeypatch.setattr(
        "freshquant.instrument.stock.fq_inst_fetch_stock_list",
        lambda: [{"code": "000001", "name": "alpha"}],
    )
    monkeypatch.setattr(
        "freshquant.data.gantt_readmodel._load_shouban30_credit_subject_lookup",
        lambda: ({}, True),
    )
    monkeypatch.setattr(
        "freshquant.data.gantt_readmodel._load_shouban30_quality_subject_lookup",
        lambda: ({}, True, "v1"),
    )
    monkeypatch.setattr(
        "freshquant.data.gantt_readmodel._resolve_shouban30_extra_filter_result",
        lambda *args, **kwargs: {
            "is_credit_subject": True,
            "is_quality_subject": False,
            "near_long_term_ma_passed": False,
        },
    )

    memberships = service.build_market_flag_memberships(
        "2026-03-18",
        ["000001"],
    )

    assert memberships == [
        {
            "code": "000001",
            "condition_key": "flag:credit_subject",
            "name": "alpha",
            "symbol": "sz000001",
            "trade_date": "2026-03-18",
        }
    ]


def test_daily_screening_service_builds_cls_memberships_for_all_models(
    monkeypatch,
):
    service = _make_service()

    class FakeClxsStrategy:
        def __init__(self, *, model_opt):
            self.model_opt = model_opt

        async def screen(self, **kwargs):
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    signal_type=f"CLXS_{self.model_opt}",
                )
            ]

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(model_opt=config["model_opt"]),
    )

    memberships = service.build_cls_memberships("2026-03-18", ["000001"])

    assert [item["condition_key"] for item in memberships] == [
        f"cls:{label}" for label in FULL_CLXS_MODEL_LABELS
    ]
    assert {item["code"] for item in memberships} == {"000001"}


def test_daily_screening_service_builds_cls_memberships_with_one_market_scan_per_model(
    monkeypatch,
):
    service = _make_service()
    calls = []

    class FakeClxsStrategy:
        def __init__(self, *, model_opt):
            self.model_opt = model_opt

        async def screen(self, **kwargs):
            calls.append({"model_opt": self.model_opt, **kwargs})
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    signal_type=f"CLXS_{self.model_opt}",
                ),
                SimpleNamespace(
                    code="000002",
                    name="beta",
                    symbol="sz000002",
                    signal_type=f"CLXS_{self.model_opt}",
                ),
            ]

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(model_opt=config["model_opt"]),
    )

    memberships = service.build_cls_memberships("2026-03-18", ["000001", "000002"])

    assert len(calls) == len(FULL_CLXS_MODEL_OPTS)
    assert all(call["code"] is None for call in calls)
    assert len(memberships) == len(FULL_CLXS_MODEL_OPTS) * 2


def test_daily_screening_service_builds_cls_memberships_for_requested_model_subset(
    monkeypatch,
):
    service = _make_service()
    calls = []

    class FakeClxsStrategy:
        def __init__(self, *, model_opt):
            self.model_opt = model_opt

        async def screen(self, **kwargs):
            calls.append(self.model_opt)
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    signal_type=f"CLXS_{self.model_opt}",
                )
            ]

    monkeypatch.setattr(
        service,
        "_make_clxs_strategy",
        lambda run_id, config: FakeClxsStrategy(model_opt=config["model_opt"]),
    )

    memberships = service.build_cls_memberships(
        "2026-03-18",
        ["000001"],
        model_opts=[10001, 10002],
    )

    assert calls == [10001, 10002]
    assert [item["condition_key"] for item in memberships] == [
        "cls:S0001",
        "cls:S0002",
    ]


def test_daily_screening_service_builds_chanlun_variant_memberships_without_run_session(
    monkeypatch,
):
    service = _make_service()
    captured = {}

    class FakeChanlunStrategy:
        async def screen(self, **kwargs):
            return [
                SimpleNamespace(
                    code="000001",
                    name="alpha",
                    symbol="sz000001",
                    period="30m",
                    signal_type="buy_zs_huila",
                )
            ]

    def fake_make_chanlun_strategy(run_id, config):
        captured["strategy"] = {
            "run_id": run_id,
            "include_sell_short": config.get("include_sell_short"),
        }
        return FakeChanlunStrategy()

    monkeypatch.setattr(
        service,
        "_make_chanlun_strategy",
        fake_make_chanlun_strategy,
    )

    memberships = service.build_chanlun_variant_memberships(
        "2026-03-18",
        ["000001"],
    )

    assert captured["strategy"] == {
        "run_id": "dagster-chanlun",
        "include_sell_short": True,
    }
    assert memberships == [
        {
            "code": "000001",
            "condition_key": "chanlun_period:30m",
            "name": "alpha",
            "symbol": "sz000001",
            "trade_date": "2026-03-18",
        },
        {
            "code": "000001",
            "condition_key": "chanlun_signal:buy_zs_huila",
            "name": "alpha",
            "symbol": "sz000001",
            "trade_date": "2026-03-18",
        },
    ]
