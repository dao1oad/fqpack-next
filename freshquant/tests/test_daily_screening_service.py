from __future__ import annotations

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


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


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

    service = DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=fake_db,
    )

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
    assert any(field["name"] == "clxs_model_opts" for field in all_model["fields"])
    assert any(field["name"] == "chanlun_signal_types" for field in all_model["fields"])
    chanlun_model = next(item for item in schema["models"] if item["id"] == "chanlun")
    assert any(field["name"] == "input_mode" for field in chanlun_model["fields"])


def test_daily_screening_service_runs_clxs_and_persists_results_with_remark(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=fake_db,
    )

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
    assert run["progress"]["accepted"] == 1
    assert run["progress"]["persisted"] == 1
    assert run["results"][0]["code"] == "000001"
    assert [event["event"] for event in events] == [
        "started",
        "phase_started",
        "universe",
        "progress",
        "hit_raw",
        "accepted",
        "phase_completed",
        "persisted",
        "summary",
        "completed",
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
            "screening_model_label": "CLXS_10001",
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


def test_daily_screening_service_passes_filtered_pre_pool_query_to_chanlun(
    monkeypatch,
):
    from freshquant.daily_screening.service import DailyScreeningService
    from freshquant.daily_screening.session_store import DailyScreeningSessionStore

    fake_db = FakeDB(stock_pre_pools=FakeCollection([]))
    service = DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=fake_db,
    )

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
    service = DailyScreeningService(
        session_store=DailyScreeningSessionStore(),
        db=fake_db,
    )

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
            captured["pre_pool_query"] = kwargs.get("pre_pool_query")
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

    snapshot = service.start_run(
        {
            "model": "all",
            "days": 1,
            "clxs_model_opts": [8, 10001],
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
    assert run["progress"]["accepted"] == 4
    assert run["progress"]["persisted"] == 4
    assert captured["pre_pool_query"] == {
        "remark": "daily-screening:clxs",
        "extra.screening_run_id": run["id"],
    }
    assert [item["model_key"] for item in run["results"]] == [
        "CLXS_8",
        "CLXS_10001",
        "buy_zs_huila",
        "macd_bullish_divergence",
    ]
    assert [item["branch"] for item in run["results"]] == [
        "clxs",
        "clxs",
        "chanlun",
        "chanlun",
    ]
    assert persisted == [
        {
            "code": "000001",
            "category": "CLXS_8",
            "dt": datetime(2026, 3, 17, 15, 0),
            "stop_loss_price": 9.8,
            "expire_at_days": 89,
            "remark": "daily-screening:clxs",
            "screening_run_id": run["id"],
            "screening_model": "clxs",
            "screening_branch": "clxs",
            "screening_model_key": "CLXS_8",
            "screening_model_label": "CLXS_8",
            "screening_input_mode": "market",
            "screening_source_scope": "market",
            "screening_signal_type": "CLXS_8",
            "screening_signal_name": "CLXS_8",
            "screening_period": "1d",
            "screening_params": {
                "days": 1,
                "code": None,
                "wave_opt": 1560,
                "stretch_opt": 0,
                "trend_opt": 1,
                "model_opt": 8,
            },
        },
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
            "screening_model_label": "CLXS_10001",
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
        },
        {
            "code": "000001",
            "category": "CLXS_8",
            "dt": datetime(2026, 3, 17, 15, 0),
            "stop_loss_price": 9.6,
            "expire_at_days": 89,
            "remark": "daily-screening:chanlun",
            "screening_run_id": run["id"],
            "screening_model": "chanlun",
            "screening_branch": "chanlun",
            "screening_model_key": "buy_zs_huila",
            "screening_model_label": "回拉中枢上涨",
            "screening_input_mode": "remark_filtered_pre_pools",
            "screening_source_scope": "pre_pool_remark:daily-screening:clxs",
            "screening_signal_type": "buy_zs_huila",
            "screening_signal_name": "回拉中枢上涨",
            "screening_period": "30m",
            "screening_params": {
                "days": 1,
                "code": None,
                "input_mode": "remark_filtered_pre_pools",
                "period_mode": "all",
                "pre_pool_category": None,
                "pre_pool_remark": "daily-screening:clxs",
                "pre_pool_run_id": run["id"],
                "signal_types": [
                    "buy_zs_huila",
                    "macd_bullish_divergence",
                ],
                "max_concurrent": 50,
                "save_signal": False,
                "save_pools": False,
                "pool_expire_days": 10,
            },
        },
        {
            "code": "000001",
            "category": "CLXS_8",
            "dt": datetime(2026, 3, 17, 15, 0),
            "stop_loss_price": 9.6,
            "expire_at_days": 89,
            "remark": "daily-screening:chanlun",
            "screening_run_id": run["id"],
            "screening_model": "chanlun",
            "screening_branch": "chanlun",
            "screening_model_key": "macd_bullish_divergence",
            "screening_model_label": "MACD看涨背驰",
            "screening_input_mode": "remark_filtered_pre_pools",
            "screening_source_scope": "pre_pool_remark:daily-screening:clxs",
            "screening_signal_type": "macd_bullish_divergence",
            "screening_signal_name": "MACD看涨背驰",
            "screening_period": "30m",
            "screening_params": {
                "days": 1,
                "code": None,
                "input_mode": "remark_filtered_pre_pools",
                "period_mode": "all",
                "pre_pool_category": None,
                "pre_pool_remark": "daily-screening:clxs",
                "pre_pool_run_id": run["id"],
                "signal_types": [
                    "buy_zs_huila",
                    "macd_bullish_divergence",
                ],
                "max_concurrent": 50,
                "save_signal": False,
                "save_pools": False,
                "pool_expire_days": 10,
            },
        },
    ]
