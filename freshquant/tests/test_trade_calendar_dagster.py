import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd

from freshquant.data.trade_calendar_cache import (
    FRAME_ATTR_ERROR_MESSAGE,
    FRAME_ATTR_ERROR_TYPE,
    FRAME_ATTR_STATUS,
    STATUS_FILE_SNAPSHOT,
    STATUS_LIVE,
)


def _build_dagster_stub():
    module = ModuleType("dagster")
    module.__path__ = []

    class _FakeAssetDef:
        def __init__(self, fn, name, group_name=None):
            self._fn = fn
            self.name = name
            self.group_name = group_name

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

    class _FakeAssetSelection:
        def __init__(self, asset_names=None):
            self.asset_names = tuple(asset_names or ())

        @classmethod
        def assets(cls, *assets):
            return cls([getattr(asset, "name", str(asset)) for asset in assets])

    class _FakeJobDef:
        def __init__(self, name, selection=None, tags=None):
            self.name = name
            self.selection = selection
            self.tags = tags or {}

    class ScheduleDefinition:
        def __init__(self, **kwargs):
            self.name = kwargs.get("name")
            self.job = kwargs.get("job")
            self.cron_schedule = kwargs.get("cron_schedule")
            self.execution_timezone = kwargs.get("execution_timezone")
            self.default_status = kwargs.get("default_status")

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

    def define_asset_job(name, selection=None, tags=None, **kwargs):
        return _FakeJobDef(name, selection=selection, tags=tags)

    module.asset = asset
    module.AssetSelection = _FakeAssetSelection
    module.define_asset_job = define_asset_job
    module.ScheduleDefinition = ScheduleDefinition
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING")
    return module


def _prepare_fqdagster_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    monkeypatch.setitem(sys.modules, "dagster", _build_dagster_stub())
    assets_dir = project_src / "fqdagster" / "defs" / "assets"
    assets_package = ModuleType("fqdagster.defs.assets")
    assets_package.__path__ = [str(assets_dir)]
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets", assets_package)
    for module_name in [
        "fqdagster.defs.assets.trade_calendar",
        "fqdagster.defs.schedules.trade_calendar",
    ]:
        sys.modules.pop(module_name, None)


def test_trade_calendar_asset_refreshes_persistent_cache(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.trade_calendar")

    monkeypatch.setattr(
        assets_module,
        "refresh_trade_date_hist_sina_cache",
        lambda: pd.DataFrame(
            {"trade_date": pd.to_datetime(["2026-03-18", "2026-03-19"]).date}
        ),
    )

    assert assets_module.trade_calendar_cache_asset.group_name == "trade_calendar"
    assert assets_module.trade_calendar_cache_asset() == {
        "date_count": 2,
        "min_trade_date": "2026-03-18",
        "max_trade_date": "2026-03-19",
        "source": "sina",
        "refresh_status": STATUS_LIVE,
        "degraded": False,
        "source_error_type": "",
        "source_error_message": "",
    }


def test_trade_calendar_asset_reports_degraded_cache_refresh(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)
    assets_module = importlib.import_module("fqdagster.defs.assets.trade_calendar")

    def fake_refresh():
        frame = pd.DataFrame(
            {"trade_date": pd.to_datetime(["2026-03-18", "2026-12-31"]).date}
        )
        frame.attrs[FRAME_ATTR_STATUS] = STATUS_FILE_SNAPSHOT
        frame.attrs[FRAME_ATTR_ERROR_TYPE] = "SSLError"
        frame.attrs[FRAME_ATTR_ERROR_MESSAGE] = "temporary ssl failure"
        return frame

    monkeypatch.setattr(
        assets_module,
        "refresh_trade_date_hist_sina_cache",
        fake_refresh,
    )

    assert assets_module.trade_calendar_cache_asset() == {
        "date_count": 2,
        "min_trade_date": "2026-03-18",
        "max_trade_date": "2026-12-31",
        "source": "sina",
        "refresh_status": STATUS_FILE_SNAPSHOT,
        "degraded": True,
        "source_error_type": "SSLError",
        "source_error_message": "temporary ssl failure",
    }


def test_trade_calendar_schedules_import(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)
    schedules_module = importlib.import_module(
        "fqdagster.defs.schedules.trade_calendar"
    )

    assert schedules_module.trade_calendar_refresh_job.name == (
        "trade_calendar_refresh_job"
    )
    assert schedules_module.trade_calendar_morning_refresh_schedule.cron_schedule == (
        "30 8 * * 1-5"
    )
    assert schedules_module.trade_calendar_postclose_refresh_schedule.cron_schedule == (
        "10 15 * * 1-5"
    )
    assert (
        schedules_module.trade_calendar_morning_refresh_schedule.default_status
        == "RUNNING"
    )
