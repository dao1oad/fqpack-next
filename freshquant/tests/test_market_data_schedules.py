import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _prepare_schedule_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))

    class FakeSelection:
        @classmethod
        def assets(cls, *assets):
            return cls()

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
    for name in ("bond_list", "etf_list", "future_list", "index_list", "stock_list"):
        setattr(assets, name, SimpleNamespace(name=name))
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets.market_data", assets)
    sys.modules.pop("fqdagster.defs.schedules.market_data", None)


def test_stock_and_etf_jobs_bound_runtime_and_failed_run_retries(monkeypatch):
    _prepare_schedule_import(monkeypatch)
    module = importlib.import_module("fqdagster.defs.schedules.market_data")

    expected_tags = {
        "dagster/max_concurrent_runs": "1",
        "dagster/max_retries": "2",
        "dagster/max_runtime": "28800",
    }
    assert module.stock_data_job.tags == expected_tags
    assert module.etf_data_job.tags == expected_tags
