import importlib
import inspect
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _build_dagster_stub():
    module = ModuleType("dagster")
    module.__path__ = []

    class _FakeAssetDef:
        def __init__(self, fn, name, group_name=None):
            self._fn = fn
            self.name = name
            self.group_name = group_name
            self.dependency_names = [
                name
                for name in inspect.signature(fn).parameters
                if name != "context"
            ]

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

    class _FakeAssetSelection:
        def __init__(self, asset_names=None, group_names=None):
            self.asset_names = tuple(asset_names or ())
            self.group_names = tuple(group_names or ())

        @classmethod
        def assets(cls, *assets):
            asset_names = [
                getattr(asset, "name", str(asset)).strip() for asset in assets
            ]
            return cls(asset_names=asset_names)

        @classmethod
        def groups(cls, *groups):
            return cls(group_names=[str(group).strip() for group in groups])

        def downstream(self):
            return self

        def __sub__(self, other):
            return self

    class _FakeJobDef:
        def __init__(self, name, selection=None, description=None, tags=None):
            self.name = name
            self.selection = selection
            self.description = description
            self.tags = tags or {}

    def asset(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeAssetDef(
                inner,
                kwargs.get("name") or inner.__name__,
                group_name=kwargs.get("group_name"),
            )
        return _FakeAssetDef(
            fn,
            kwargs.get("name") or fn.__name__,
            group_name=kwargs.get("group_name"),
        )

    def define_asset_job(name, selection=None, description=None, tags=None):
        return _FakeJobDef(
            name,
            selection=selection,
            description=description,
            tags=tags,
        )

    class ScheduleDefinition:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.job = kwargs.get("job")
            self.cron_schedule = kwargs.get("cron_schedule")

    class RunRequest:
        def __init__(self, run_key=None, run_config=None, tags=None):
            self.run_key = run_key
            self.run_config = run_config or {}
            self.tags = tags or {}

    class SkipReason:
        def __init__(self, skip_message):
            self.skip_message = skip_message

    class _FakeSensorDef:
        def __init__(self, fn, name=None, job=None):
            self._fn = fn
            self.name = name or fn.__name__
            self.job = job

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

    def sensor(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeSensorDef(
                inner,
                name=kwargs.get("name"),
                job=kwargs.get("job"),
            )
        return _FakeSensorDef(fn, name=kwargs.get("name"), job=kwargs.get("job"))

    module.asset = asset
    module.AssetSelection = _FakeAssetSelection
    module.define_asset_job = define_asset_job
    module.ScheduleDefinition = ScheduleDefinition
    module.RunRequest = RunRequest
    module.SkipReason = SkipReason
    module.sensor = sensor
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING", STOPPED="STOPPED")
    return module


def _install_dagster_stub(monkeypatch):
    dagster_module = _build_dagster_stub()
    monkeypatch.setitem(sys.modules, "dagster", dagster_module)


def _prepare_fqdagster_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    _install_dagster_stub(monkeypatch)
    assets_dir = project_src / "fqdagster" / "defs" / "assets"
    assets_package = ModuleType("fqdagster.defs.assets")
    assets_package.__path__ = [str(assets_dir)]
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets", assets_package)
    for module_name in [
        "fqdagster.defs.assets.daily_screening",
        "fqdagster.defs.jobs.daily_screening",
        "fqdagster.defs.schedules.daily_screening",
        "fqdagster.defs.sensors.postclose",
    ]:
        sys.modules.pop(module_name, None)


def test_daily_screening_dagster_modules_import(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    jobs_module = importlib.import_module("fqdagster.defs.jobs.daily_screening")
    schedules_module = importlib.import_module(
        "fqdagster.defs.schedules.daily_screening"
    )
    sensors_module = importlib.import_module("fqdagster.defs.sensors.postclose")

    assert hasattr(assets_module, "daily_screening_context")
    assert hasattr(assets_module, "daily_screening_base_union")
    assert hasattr(assets_module, "daily_screening_publish_scope")
    assert hasattr(jobs_module, "daily_screening_postclose_job")
    assert hasattr(schedules_module, "daily_screening_postclose_schedule")
    assert hasattr(sensors_module, "daily_screening_postclose_sensor")
    assert jobs_module.daily_screening_postclose_job.name == (
        "daily_screening_postclose_job"
    )
    assert (
        schedules_module.daily_screening_postclose_schedule.cron_schedule
        == "0 19 * * 1-5"
    )


def test_daily_screening_assets_keep_publish_as_terminal_node(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    cls_asset_names = [f"daily_screening_cls_s{index:04d}" for index in range(1, 13)]

    assert assets_module.daily_screening_universe.dependency_names == [
        "daily_screening_upstream_guard"
    ]
    assert assets_module.DAILY_SCREENING_CLS_MODEL_ASSET_NAMES == cls_asset_names
    assert len(assets_module.DAILY_SCREENING_CLS_MODEL_ASSETS) == len(cls_asset_names)
    assert assets_module.daily_screening_cls.dependency_names == cls_asset_names
    assert assets_module.daily_screening_base_union.dependency_names == [
        "daily_screening_cls",
        "daily_screening_hot_30",
        "daily_screening_hot_45",
        "daily_screening_hot_60",
        "daily_screening_hot_90",
    ]
    assert assets_module.daily_screening_market_flags_snapshot.dependency_names == [
        "daily_screening_base_union"
    ]
    assert assets_module.daily_screening_flag_near_long_term_ma.dependency_names == [
        "daily_screening_market_flags_snapshot"
    ]
    assert assets_module.daily_screening_flag_quality_subject.dependency_names == [
        "daily_screening_market_flags_snapshot"
    ]
    assert assets_module.daily_screening_flag_credit_subject.dependency_names == [
        "daily_screening_market_flags_snapshot"
    ]
    assert assets_module.daily_screening_snapshot_assemble.dependency_names == [
        "daily_screening_context",
        "daily_screening_base_union",
        "daily_screening_flag_near_long_term_ma",
        "daily_screening_flag_quality_subject",
        "daily_screening_flag_credit_subject",
        "daily_screening_shouban30_chanlun_metrics",
        "daily_screening_chanlun_variants",
    ]
    assert assets_module.daily_screening_publish_scope.dependency_names == [
        "daily_screening_snapshot_assemble"
    ]


def test_daily_screening_asset_helper_uses_execution_timezone(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    monkeypatch.setattr(
        assets_module,
        "tool_trade_date_hist_sina",
        lambda: {
            "trade_date": [
                datetime(2026, 3, 17).date(),
                datetime(2026, 3, 18).date(),
            ]
        },
    )
    captured = {}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            captured["tz"] = tz
            return datetime(2026, 3, 18, 19, 0, tzinfo=tz)

    monkeypatch.setattr(assets_module, "datetime", FakeDateTime)

    assert assets_module._query_latest_trade_date() == "2026-03-18"
    assert str(captured["tz"]) == "Asia/Shanghai"
    assert assets_module.daily_screening_context() == {
        "trade_date": "2026-03-18",
        "scope_id": "trade_date:2026-03-18",
    }


def test_daily_screening_context_prefers_sensor_trade_date_tag(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")

    context = SimpleNamespace(run=SimpleNamespace(tags={"fq_trade_date": "2026-03-19"}))

    assert assets_module.daily_screening_context(context) == {
        "trade_date": "2026-03-19",
        "scope_id": "trade_date:2026-03-19",
    }


def test_daily_screening_membership_persistence_clears_expected_empty_condition(
    monkeypatch,
):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    calls = []

    class FakeRepository:
        def ensure_indexes(self):
            return None

        def replace_condition_memberships(self, *, scope_id, condition_key, codes):
            calls.append(
                {
                    "scope_id": scope_id,
                    "condition_key": condition_key,
                    "codes": list(codes),
                }
            )

    fake_service = SimpleNamespace(
        pipeline_service=SimpleNamespace(repository=FakeRepository())
    )

    assets_module._persist_condition_memberships(
        fake_service,
        scope_id="trade_date:2026-03-18",
        memberships=[],
        expected_condition_keys=["flag:near_long_term_ma"],
    )

    assert calls == [
        {
            "scope_id": "trade_date:2026-03-18",
            "condition_key": "flag:near_long_term_ma",
            "codes": [],
        }
    ]


def test_daily_screening_membership_persistence_clears_missing_expected_keys(
    monkeypatch,
):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    calls = []

    class FakeRepository:
        def ensure_indexes(self):
            return None

        def replace_condition_memberships(self, *, scope_id, condition_key, codes):
            calls.append(
                {
                    "scope_id": scope_id,
                    "condition_key": condition_key,
                    "codes": list(codes),
                }
            )

    fake_service = SimpleNamespace(
        pipeline_service=SimpleNamespace(repository=FakeRepository())
    )

    assets_module._persist_condition_memberships(
        fake_service,
        scope_id="trade_date:2026-03-18",
        memberships=[
            {
                "condition_key": "chanlun_signal:buy_zs_huila",
                "code": "000001",
                "name": "alpha",
            }
        ],
        expected_condition_keys=[
            "chanlun_signal:buy_zs_huila",
            "chanlun_signal:sell_zs_huila",
        ],
    )

    assert calls == [
        {
            "scope_id": "trade_date:2026-03-18",
            "condition_key": "chanlun_signal:buy_zs_huila",
            "codes": [{"code": "000001", "name": "alpha"}],
        },
        {
            "scope_id": "trade_date:2026-03-18",
            "condition_key": "chanlun_signal:sell_zs_huila",
            "codes": [],
        },
    ]


def test_daily_screening_market_flags_snapshot_scans_once_for_2026_03_19(
    monkeypatch,
):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    calls = []

    class FakeService:
        def build_market_flag_memberships(self, trade_date, candidate_codes):
            calls.append(
                {
                    "trade_date": trade_date,
                    "candidate_codes": list(candidate_codes),
                }
            )
            return [
                {
                    "condition_key": "flag:quality_subject",
                    "code": "000001",
                    "name": "alpha",
                    "symbol": "sz000001",
                },
                {
                    "condition_key": "flag:credit_subject",
                    "code": "000002",
                    "name": "beta",
                    "symbol": "sz000002",
                },
            ]

    monkeypatch.setattr(assets_module, "_make_service", lambda: FakeService())

    payload = assets_module.daily_screening_market_flags_snapshot(
        {
            "trade_date": "2026-03-19",
            "scope_id": "trade_date:2026-03-19",
            "candidate_codes": ["000001", "000002"],
        }
    )
    near_ma = assets_module.daily_screening_flag_near_long_term_ma(payload)
    quality = assets_module.daily_screening_flag_quality_subject(payload)
    credit = assets_module.daily_screening_flag_credit_subject(payload)

    assert calls == [
        {"trade_date": "2026-03-19", "candidate_codes": ["000001", "000002"]}
    ]
    assert near_ma["memberships"] == []
    assert [item["code"] for item in quality["memberships"]] == ["000001"]
    assert [item["code"] for item in credit["memberships"]] == ["000002"]


def test_daily_screening_publish_scope_marks_trade_date_ready(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    calls = []

    monkeypatch.setattr(
        assets_module,
        "upsert_postclose_marker",
        lambda pipeline_key, trade_date, **kwargs: calls.append(
            {
                "pipeline_key": pipeline_key,
                "trade_date": trade_date,
                **kwargs,
            }
        )
        or {
            "pipeline_key": pipeline_key,
            "trade_date": trade_date,
            "status": kwargs.get("status", "success"),
        },
    )

    payload = assets_module.daily_screening_publish_scope(
        {
            "trade_date": "2026-03-19",
            "scope_id": "trade_date:2026-03-19",
            "stage": "snapshot_assemble",
            "snapshots": [],
        }
    )

    assert calls == [
        {
            "pipeline_key": "daily_screening_ready",
            "trade_date": "2026-03-19",
            "run_id": "",
            "payload": {"scope_id": "trade_date:2026-03-19"},
        }
    ]
    assert payload["published"] is True
