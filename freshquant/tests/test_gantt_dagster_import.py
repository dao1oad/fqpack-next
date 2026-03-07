import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _build_dagster_stub():
    module = ModuleType("dagster")

    def op(fn=None, **kwargs):
        if fn is None:
            return lambda inner: inner
        return fn

    def job(fn=None, **kwargs):
        if fn is None:
            return lambda inner: inner
        return fn

    class ScheduleDefinition:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.op = op
    module.job = job
    module.ScheduleDefinition = ScheduleDefinition
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING")
    return module


def test_gantt_dagster_modules_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    monkeypatch.setitem(sys.modules, "dagster", _build_dagster_stub())

    ops_module = importlib.import_module("fqdagster.defs.ops.gantt")
    jobs_module = importlib.import_module("fqdagster.defs.jobs.gantt")
    schedules_module = importlib.import_module("fqdagster.defs.schedules.gantt")

    assert hasattr(ops_module, "op_sync_xgb_history_daily")
    assert hasattr(ops_module, "op_run_gantt_postclose_incremental")
    assert hasattr(ops_module, "op_build_stock_hot_reason_daily")
    assert hasattr(jobs_module, "job_gantt_postclose")
    assert hasattr(schedules_module, "gantt_postclose_schedule")
