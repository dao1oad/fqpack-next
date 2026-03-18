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


def _make_service_with_screening_repo(*, fake_db=None, screening_db=None, session_store=None):
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
        event_id = next(line.split(": ", 1)[1] for line in lines if line.startswith("id: "))
        event = next(line.split(": ", 1)[1] for line in lines if line.startswith("event: "))
        data = next(line.split(": ", 1)[1] for line in lines if line.startswith("data: "))
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
    assert [option["value"] for option in all_clxs_field["options"]] == FULL_CLXS_MODEL_OPTS
    assert [option["label"] for option in all_clxs_field["options"]] == FULL_CLXS_MODEL_LABELS
    assert any(field["name"] == "chanlun_signal_types" for field in all_model["fields"])
    clxs_model = next(item for item in schema["models"] if item["id"] == "clxs")
    clxs_field = next(field for field in clxs_model["fields"] if field["name"] == "model_opts")
    assert clxs_field["default"] == [10001]
    assert [option["value"] for option in clxs_field["options"]] == FULL_CLXS_MODEL_OPTS
    assert [option["label"] for option in clxs_field["options"]] == FULL_CLXS_MODEL_LABELS
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
    assert [item["model_label"] for item in run["results"][:12]] == FULL_CLXS_MODEL_LABELS
    assert [item["branch"] for item in run["results"][:12]] == ["clxs"] * 12
    assert [item["model_key"] for item in run["results"][12:]] == [
        "buy_zs_huila",
        "macd_bullish_divergence",
    ]
    clxs_persisted = [item for item in persisted if item["remark"] == "daily-screening:clxs"]
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
    assert [item["screening_model_label"] for item in persisted] == FULL_CLXS_MODEL_LABELS


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


def _seed_run_scope_snapshot_fixture(repository, *, run_id="run-1"):
    scope = f"run:{run_id}"
    repository.replace_stage_memberships(
        run_id=run_id,
        stage="clxs",
        scope=scope,
        memberships=[
            {
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
                "chanlun_variants": [
                    {"signal_type": "buy_zs_huila", "period": "30m"}
                ],
                "shouban30_providers": ["jygs", "xgb"],
            },
            {
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

    detail = service.get_stock_detail("run-1", "000001")

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
