import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _build_dagster_stub():
    module = ModuleType("dagster")
    module.__path__ = []
    builder_stack = []

    class Output:
        def __init__(self, value, output_name="result", metadata=None):
            self.value = value
            self.output_name = output_name
            self.metadata = metadata or {}

    class _FakeValue:
        def __init__(self, producer_name=None):
            self.producer_name = producer_name

    class _FakeBuilder:
        def __init__(self, owner):
            self.owner = owner
            self.node_defs = []

        def add_node(self, node_def):
            if node_def not in self.node_defs:
                self.node_defs.append(node_def)

        def finalize(self):
            self.owner.node_defs = list(self.node_defs)

    class _FakeNodeDef:
        def __init__(self, fn, name):
            self._fn = fn
            self.name = name

        def __call__(self, *args, **kwargs):
            if not builder_stack:
                return self._fn(*args, **kwargs)
            builder = builder_stack[-1]
            builder.add_node(self)
            return _FakeValue(self.name)

    class _FakeOpDef(_FakeNodeDef):
        pass

    class _FakeGraphDef(_FakeNodeDef):
        def __init__(self, fn, name):
            super().__init__(fn, name)
            self.node_defs = []

        def _ensure_built(self):
            if self.node_defs:
                return
            builder = _FakeBuilder(self)
            builder_stack.append(builder)
            try:
                params = inspect.signature(self._fn).parameters
                args = [_FakeValue(f"input_{name}") for name in params]
                self._fn(*args)
            finally:
                builder_stack.pop()
            builder.finalize()

        def to_job(self, name=None):
            self._ensure_built()
            return _FakeJobDef(name or self.name, self)

    class _FakeJobDef:
        def __init__(self, name, graph_def):
            self.name = name
            self.graph = graph_def

    def op(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeOpDef(inner, kwargs.get("name") or inner.__name__)
        return _FakeOpDef(fn, kwargs.get("name") or fn.__name__)

    def graph(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeGraphDef(
                inner, kwargs.get("name") or inner.__name__
            )
        return _FakeGraphDef(fn, kwargs.get("name") or fn.__name__)

    class ScheduleDefinition:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.job = kwargs.get("job")
            self.cron_schedule = kwargs.get("cron_schedule")

    module.graph = graph
    module.op = op
    module.Output = Output
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
    for module_name in [
        "fqdagster.defs.ops.daily_screening",
        "fqdagster.defs.jobs.daily_screening",
        "fqdagster.defs.schedules.daily_screening",
    ]:
        sys.modules.pop(module_name, None)


def test_daily_screening_dagster_modules_import(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    ops_module = importlib.import_module("fqdagster.defs.ops.daily_screening")
    jobs_module = importlib.import_module("fqdagster.defs.jobs.daily_screening")
    schedules_module = importlib.import_module(
        "fqdagster.defs.schedules.daily_screening"
    )

    assert hasattr(ops_module, "op_run_daily_screening_postclose")
    assert hasattr(ops_module, "graph_daily_screening_postclose")
    assert hasattr(jobs_module, "job_daily_screening_postclose")
    assert hasattr(schedules_module, "daily_screening_postclose_schedule")
    assert (
        schedules_module.daily_screening_postclose_schedule.cron_schedule
        == "0 19 * * 1-5"
    )
    assert (
        jobs_module.job_daily_screening_postclose.name
        == "job_daily_screening_postclose"
    )


def test_daily_screening_dagster_op_runs_full_pipeline(monkeypatch):
    _prepare_fqdagster_import(monkeypatch)

    captured = {}

    class FakeService:
        def start_run(self, payload, run_async=True, trigger_type="manual_api"):
            captured["call"] = {
                "payload": dict(payload),
                "run_async": run_async,
                "trigger_type": trigger_type,
            }
            return {"id": "run-1900", "status": "completed"}

    monkeypatch.setitem(
        sys.modules,
        "freshquant.daily_screening.service",
        SimpleNamespace(DailyScreeningService=lambda: FakeService()),
    )

    ops_module = importlib.import_module("fqdagster.defs.ops.daily_screening")
    monkeypatch.setattr(
        ops_module,
        "_query_latest_trade_date",
        lambda: "2026-03-18",
    )

    context = SimpleNamespace(log=SimpleNamespace(info=lambda *args, **kwargs: None))
    output = ops_module.op_run_daily_screening_postclose(context)

    assert output.value == {"run_id": "run-1900", "trade_date": "2026-03-18"}
    assert captured["call"] == {
        "payload": {"model": "all", "trade_date": "2026-03-18"},
        "run_async": False,
        "trigger_type": "dagster_schedule",
    }
