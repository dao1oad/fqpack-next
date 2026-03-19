import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _build_dagster_stub():
    module = ModuleType("dagster")
    module.__path__ = []
    builder_stack = []

    class DynamicOut:
        def __init__(self, dagster_type=None):
            self.dagster_type = dagster_type

    class DynamicOutput:
        def __init__(self, value, mapping_key):
            self.value = value
            self.mapping_key = mapping_key

    class DagsterEvent:
        def __init__(self, message):
            self.message = message

        @staticmethod
        def engine_event(step_context, message, event_specific_data=None):
            return DagsterEvent(message)

    class EngineEventData:
        def __init__(self, *args, **kwargs):
            pass

    class Output:
        def __init__(self, value, output_name="result", metadata=None):
            self.value = value
            self.output_name = output_name
            self.metadata = metadata or {}

    class _FakeValue:
        def __init__(self, producer_name=None, is_dynamic=False):
            self.producer_name = producer_name
            self.is_dynamic = is_dynamic

        def map(self, fn):
            if not self.is_dynamic:
                raise TypeError("map() only supported on dynamic outputs")
            return fn(_FakeValue(f"{self.producer_name}__item"))

    def _collect_dependencies(args):
        dependencies = set()
        for arg in args:
            if isinstance(arg, _FakeValue) and arg.producer_name:
                dependencies.add(arg.producer_name.removesuffix("__item"))
            elif isinstance(arg, (list, tuple, set)):
                dependencies.update(_collect_dependencies(arg))
        return dependencies

    class _FakeBuilder:
        def __init__(self, owner):
            self.owner = owner
            self.node_defs = []
            self.node_names = set()
            self.dependency_map = {}

        def add_node(self, node_def, args):
            if node_def.name not in self.node_names:
                self.node_defs.append(node_def)
                self.node_names.add(node_def.name)
            self.dependency_map.setdefault(node_def.name, set()).update(
                _collect_dependencies(args)
            )

        def extend_graph(self, graph_def):
            graph_def._ensure_built()
            for node_def in graph_def.node_defs:
                if node_def.name not in self.node_names:
                    self.node_defs.append(node_def)
                    self.node_names.add(node_def.name)
            for node_name, dependencies in graph_def.dependency_map.items():
                self.dependency_map.setdefault(node_name, set()).update(dependencies)

        def finalize(self):
            self.owner.node_defs = list(self.node_defs)
            self.owner.dependency_map = {
                node_name: set(dependencies)
                for node_name, dependencies in self.dependency_map.items()
            }

    class _FakeNodeDef:
        def __init__(self, fn, name):
            self._fn = fn
            self.name = name

        def __call__(self, *args, **kwargs):
            if not builder_stack:
                return self._fn(*args, **kwargs)
            builder = builder_stack[-1]
            builder.add_node(self, args)
            return _FakeValue(
                self.name,
                is_dynamic=getattr(self, "_is_dynamic_output", False),
            )

    class _FakeOpDef(_FakeNodeDef):
        def __init__(self, fn, name, out=None):
            super().__init__(fn, name)
            self._is_dynamic_output = isinstance(out, DynamicOut)

    class _FakeGraphDef(_FakeNodeDef):
        def __init__(self, fn, name):
            super().__init__(fn, name)
            self.node_defs = []
            self.dependency_map = {}

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

        def __call__(self, *args, **kwargs):
            if not builder_stack:
                return self._fn(*args, **kwargs)
            builder = builder_stack[-1]
            builder.add_node(self, args)
            self._ensure_built()
            builder.extend_graph(self)
            input_dependency_map = {
                f"input_{name}": _collect_dependencies([arg])
                for name, arg in zip(inspect.signature(self._fn).parameters, args)
            }
            for node_name, dependencies in self.dependency_map.items():
                remapped_dependencies = set()
                for dependency in dependencies:
                    remapped_dependencies.update(
                        input_dependency_map.get(dependency, {dependency})
                    )
                existing_dependencies = builder.dependency_map.get(node_name, set())
                builder.dependency_map[node_name] = {
                    dependency
                    for dependency in existing_dependencies
                    if dependency not in input_dependency_map
                }
                builder.dependency_map[node_name].update(remapped_dependencies)
            return _FakeValue(self.name)

        def to_job(self, name=None):
            self._ensure_built()
            return _FakeJobDef(name or self.name, self)

    class _FakeJobDef:
        def __init__(self, name, graph_def):
            self.name = name
            self.graph = graph_def

    def op(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeOpDef(
                inner, kwargs.get("name") or inner.__name__, kwargs.get("out")
            )
        return _FakeOpDef(fn, kwargs.get("name") or fn.__name__, kwargs.get("out"))

    def graph(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeGraphDef(
                inner, kwargs.get("name") or inner.__name__
            )
        return _FakeGraphDef(fn, kwargs.get("name") or fn.__name__)

    def job(fn=None, **kwargs):
        def _build_job(inner):
            graph_def = _FakeGraphDef(inner, inner.__name__)
            graph_def._ensure_built()
            return _FakeJobDef(kwargs.get("name") or inner.__name__, graph_def)

        if fn is None:
            return _build_job
        return _build_job(fn)

    class ScheduleDefinition:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.op = op
    module.graph = graph
    module.job = job
    module.DynamicOut = DynamicOut
    module.DynamicOutput = DynamicOutput
    module.DagsterEvent = DagsterEvent
    module.EngineEventData = EngineEventData
    module.Output = Output
    module.ScheduleDefinition = ScheduleDefinition
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING", STOPPED="STOPPED")
    return module


def test_gantt_dagster_modules_import(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    dagster_module = _build_dagster_stub()
    dagster_core_module = ModuleType("dagster._core")
    dagster_core_events_module = ModuleType("dagster._core.events")
    dagster_core_events_module.DagsterEvent = dagster_module.DagsterEvent
    dagster_core_events_module.EngineEventData = dagster_module.EngineEventData
    dagster_core_module.events = dagster_core_events_module
    monkeypatch.setitem(sys.modules, "dagster", dagster_module)
    monkeypatch.setitem(sys.modules, "dagster._core", dagster_core_module)
    monkeypatch.setitem(sys.modules, "dagster._core.events", dagster_core_events_module)

    ops_module = importlib.import_module("fqdagster.defs.ops.gantt")
    jobs_module = importlib.import_module("fqdagster.defs.jobs.gantt")
    schedules_module = importlib.import_module("fqdagster.defs.schedules.gantt")

    assert hasattr(ops_module, "op_sync_xgb_history_daily")
    assert hasattr(ops_module, "op_sync_xgb_history_for_trade_date")
    assert hasattr(ops_module, "op_resolve_pending_gantt_trade_dates")
    assert hasattr(ops_module, "op_build_stock_hot_reason_daily")
    assert hasattr(ops_module, "graph_gantt_postclose_for_trade_date")
    assert hasattr(ops_module, "graph_gantt_postclose")
    assert hasattr(jobs_module, "job_gantt_postclose")
    assert hasattr(schedules_module, "gantt_postclose_schedule")
