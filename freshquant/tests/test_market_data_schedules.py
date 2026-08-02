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
        def __init__(self, assets=()):
            self.asset_names = tuple(asset.name for asset in assets)

        @classmethod
        def assets(cls, *assets):
            return cls(assets)

        @classmethod
        def groups(cls, *groups):
            return cls()

        def downstream(self):
            return self

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
        "etf_xdxr",
        "future_list",
        "index_day",
        "index_list",
        "index_min",
        "stock_block",
        "stock_day",
        "stock_list",
        "stock_min",
        "stock_postclose_ready_asset",
        "stock_xdxr",
    ):
        setattr(assets, name, SimpleNamespace(name=name))
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets.market_data", assets)
    postclose = ModuleType("fqdagster.defs.assets.postclose_ready")
    postclose.refresh_quality_stock_universe_snapshot = SimpleNamespace(
        name="refresh_quality_stock_universe_snapshot"
    )
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets.postclose_ready", postclose)
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
    assert set(module.stock_data_job.selection.asset_names) == {
        "stock_list",
        "stock_block",
        "stock_day",
        "stock_min",
        "refresh_quality_stock_universe_snapshot",
        "stock_postclose_ready_asset",
    }
    assert set(module.etf_data_job.selection.asset_names) == {
        "etf_list",
        "etf_day",
        "etf_min",
        "etf_postclose_ready_asset",
    }
    assert set(module.index_data_job.selection.asset_names) == {
        "index_list",
        "index_day",
        "index_min",
    }


def test_dagster_instance_disables_resume_for_default_run_launcher():
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "morningglory" / "fqdagsterconfig" / "dagster.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["run_launcher"]["class"] == "DefaultRunLauncher"
    assert config["run_monitoring"]["max_resume_run_attempts"] == 0
    assert {
        "key": "freshquant/mongo_writer",
        "value": "quantaxis_market_data",
        "limit": 1,
    } in config["run_coordinator"]["config"]["tag_concurrency_limits"]


def test_dagster_schedule_does_not_import_xtdata_qfq_writer():
    repo_root = Path(__file__).resolve().parents[2]
    assets_text = (
        repo_root
        / "morningglory"
        / "fqdagster"
        / "src"
        / "fqdagster"
        / "defs"
        / "assets"
        / "market_data.py"
    ).read_text(encoding="utf-8")
    assert "market_data.xtdata.qfq" not in assets_text
