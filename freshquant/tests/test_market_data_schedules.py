import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml  # type: ignore[import-untyped]


def _prepare_schedule_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))

    class FakeSelection:
        def __init__(self, asset_names=(), *, downstream_called=False):
            self.asset_names = tuple(asset_names)
            self.downstream_called = downstream_called

        @classmethod
        def assets(cls, *assets):
            return cls(getattr(asset, "name", str(asset)) for asset in assets)

        @classmethod
        def groups(cls, *groups):
            return cls(f"group:{group}" for group in groups)

        def downstream(self):
            return type(self)(self.asset_names, downstream_called=True)

        def __sub__(self, other):
            return self

    dagster = ModuleType("dagster")
    dagster.AssetSelection = FakeSelection
    dagster.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING")
    dagster.ScheduleDefinition = lambda **kwargs: SimpleNamespace(**kwargs)
    dagster.define_asset_job = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "dagster", dagster)

    assets = ModuleType("fqdagster.defs.assets.market_data")
    for name in (
        "bond_list",
        "etf_adj",
        "etf_day",
        "etf_list",
        "etf_min",
        "etf_postclose_ready_asset",
        "future_list",
        "index_day",
        "index_list",
        "index_min",
        "stock_adj",
        "stock_block",
        "stock_day",
        "stock_list",
        "stock_min",
        "stock_postclose_ready_asset",
        "stock_xdxr",
    ):
        setattr(assets, name, SimpleNamespace(name=name))
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets.market_data", assets)
    postclose_assets = ModuleType("fqdagster.defs.assets.postclose_ready")
    postclose_assets.refresh_quality_stock_universe_snapshot = SimpleNamespace(
        name="refresh_quality_stock_universe_snapshot"
    )
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.assets.postclose_ready",
        postclose_assets,
    )
    sys.modules.pop("fqdagster.defs.schedules.market_data", None)


def test_stock_and_etf_jobs_bound_runtime_and_failed_run_retries(monkeypatch):
    _prepare_schedule_import(monkeypatch)
    module = importlib.import_module("fqdagster.defs.schedules.market_data")

    expected_tags = {
        "freshquant/mongo_writer": "quantaxis_market_data",
        "dagster/max_concurrent_runs": "1",
        "dagster/max_retries": "2",
        "dagster/max_runtime": "28800",
    }
    assert module.stock_data_job.tags == expected_tags
    assert module.etf_data_job.tags == expected_tags
    assert module.index_data_job.tags == expected_tags


def test_market_jobs_use_exact_asset_whitelists_without_cjsd(monkeypatch):
    _prepare_schedule_import(monkeypatch)
    module = importlib.import_module("fqdagster.defs.schedules.market_data")

    assert module.stock_data_job.selection.asset_names == (
        "stock_list",
        "stock_block",
        "stock_day",
        "stock_min",
        "stock_adj",
        "refresh_quality_stock_universe_snapshot",
        "stock_postclose_ready_asset",
    )
    assert module.etf_data_job.selection.asset_names == (
        "etf_list",
        "etf_day",
        "etf_min",
        "etf_adj",
        "etf_postclose_ready_asset",
    )
    assert module.index_data_job.selection.asset_names == (
        "index_list",
        "index_day",
        "index_min",
    )
    for job in (
        module.stock_data_job,
        module.etf_data_job,
        module.index_data_job,
    ):
        assert job.selection.downstream_called is False
        assert all("cjsd" not in name for name in job.selection.asset_names)


def test_dagster_instance_disables_resume_for_default_run_launcher():
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "morningglory" / "fqdagsterconfig" / "dagster.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["run_launcher"]["class"] == "DefaultRunLauncher"
    assert config["run_monitoring"]["max_resume_run_attempts"] == 0

    limits = config["run_coordinator"]["config"]["tag_concurrency_limits"]
    assert {
        "key": "freshquant/mongo_writer",
        "value": "quantaxis_market_data",
        "limit": 1,
    } in limits
