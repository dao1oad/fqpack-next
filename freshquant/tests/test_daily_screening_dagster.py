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
            self.dependency_names = list(inspect.signature(fn).parameters)

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

    module.asset = asset
    module.AssetSelection = _FakeAssetSelection
    module.define_asset_job = define_asset_job
    module.ScheduleDefinition = ScheduleDefinition
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING")
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
        "fqdagster.defs.schedules.daily_screening",
    ]:
        sys.modules.pop(module_name, None)


def test_daily_screening_dagster_modules_import(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    assets_module = importlib.import_module("fqdagster.defs.assets.daily_screening")
    schedules_module = importlib.import_module(
        "fqdagster.defs.schedules.daily_screening"
    )

    assert hasattr(assets_module, "daily_screening_context")
    assert hasattr(assets_module, "daily_screening_base_union")
    assert hasattr(assets_module, "daily_screening_publish_scope")
    assert hasattr(schedules_module, "daily_screening_postclose_job")
    assert hasattr(schedules_module, "daily_screening_postclose_schedule")
    assert schedules_module.daily_screening_postclose_job.name == (
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
