import importlib
import inspect
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest
from requests.exceptions import SSLError  # type: ignore[import-untyped]


def _build_dagster_stub():
    module = ModuleType("dagster")
    module.__path__ = []  # mark as package for submodule imports
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
    module.DefaultScheduleStatus = SimpleNamespace(RUNNING="RUNNING")
    return module


def _install_dagster_stub(monkeypatch):
    dagster_module = _build_dagster_stub()
    dagster_core_module = ModuleType("dagster._core")
    dagster_core_events_module = ModuleType("dagster._core.events")
    dagster_core_events_module.DagsterEvent = dagster_module.DagsterEvent
    dagster_core_events_module.EngineEventData = dagster_module.EngineEventData
    dagster_core_module.events = dagster_core_events_module

    monkeypatch.setitem(sys.modules, "dagster", dagster_module)
    monkeypatch.setitem(sys.modules, "dagster._core", dagster_core_module)
    monkeypatch.setitem(sys.modules, "dagster._core.events", dagster_core_events_module)


def _load_ops_module(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    _install_dagster_stub(monkeypatch)
    sys.modules.pop("fqdagster.defs.ops.gantt", None)
    return importlib.import_module("fqdagster.defs.ops.gantt")


def _load_jobs_module(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    _install_dagster_stub(monkeypatch)
    sys.modules.pop("fqdagster.defs.jobs.gantt", None)
    sys.modules.pop("fqdagster.defs.ops.gantt", None)
    return importlib.import_module("fqdagster.defs.jobs.gantt")


class _LogCollector:
    def __init__(self):
        self.messages = []

    def info(self, message, *args, **kwargs):
        if args:
            message = message % args
        self.messages.append(str(message))

    def warning(self, message, *args, **kwargs):
        if args:
            message = message % args
        self.messages.append(str(message))


def _build_context():
    events = []

    def log_event(event):
        events.append(event)

    def get_step_execution_context():
        return SimpleNamespace()

    return SimpleNamespace(
        log=_LogCollector(),
        log_event=log_event,
        get_step_execution_context=get_step_execution_context,
        events=events,
    )


def _collect_output_value(items):
    outputs = [item.value for item in items if hasattr(item, "output_name")]
    assert len(outputs) == 1
    return outputs[0]


def _collect_messages(items):
    return [
        item.message
        for item in items
        if hasattr(item, "message") and item.message is not None
    ]


def test_resolve_gantt_backfill_trade_dates_returns_latest_day_when_no_progress(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(ops, "_query_latest_completed_gantt_trade_date", lambda: None)
    monkeypatch.setattr(
        ops,
        "_query_trade_dates_between",
        lambda start_date, end_date: ["2026-03-06"],
    )

    assert ops.resolve_gantt_backfill_trade_dates() == ["2026-03-06"]


def test_resolve_gantt_backfill_trade_dates_returns_empty_when_no_gap(monkeypatch):
    ops = _load_ops_module(monkeypatch)

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-06"
    )
    monkeypatch.setattr(
        ops,
        "_has_legacy_shouban30_snapshot",
        lambda trade_date: False,
        raising=False,
    )

    assert ops.resolve_gantt_backfill_trade_dates() == []


def test_resolve_gantt_backfill_trade_dates_returns_latest_day_when_no_gap_but_shouban30_is_legacy(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-06"
    )
    monkeypatch.setattr(
        ops,
        "_has_legacy_shouban30_snapshot",
        lambda trade_date: trade_date == "2026-03-06",
        raising=False,
    )

    assert ops.resolve_gantt_backfill_trade_dates() == ["2026-03-06"]


def test_resolve_gantt_backfill_trade_dates_returns_incremental_window(monkeypatch):
    ops = _load_ops_module(monkeypatch)

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-03"
    )
    monkeypatch.setattr(
        ops,
        "_query_trade_dates_between",
        lambda start_date, end_date: [
            "2026-03-03",
            "2026-03-04",
            "2026-03-05",
            "2026-03-06",
        ],
    )

    assert ops.resolve_gantt_backfill_trade_dates() == [
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
    ]


def test_resolve_gantt_backfill_trade_dates_retries_transient_ssl_error(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)
    from freshquant.trading import dt as trading_dt

    attempts = []

    class FakeDateTime(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 3, 6, 15, 10)

    def fake_fetch():
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise SSLError("temporary ssl failure")
        return pd.DataFrame(
            {
                "trade_date": [
                    datetime(2026, 3, 5).date(),
                    datetime(2026, 3, 6).date(),
                ]
            }
        )

    monkeypatch.setattr(
        ops,
        "tool_trade_date_hist_sina",
        lambda: trading_dt._fetch_trade_dates_from_source(
            trading_dt.ak.tool_trade_date_hist_sina
        ),
    )
    monkeypatch.setattr(trading_dt.ak, "tool_trade_date_hist_sina", fake_fetch)
    monkeypatch.setattr(ops, "datetime", FakeDateTime)
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-05"
    )
    monkeypatch.setattr(
        ops,
        "_query_trade_dates_between",
        lambda start_date, end_date: ["2026-03-05", "2026-03-06"],
    )

    assert ops.resolve_gantt_backfill_trade_dates() == ["2026-03-06"]
    assert attempts == [1, 2]


def test_run_gantt_backfill_executes_each_trade_date_in_order(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    calls = []

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-05")
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-03"
    )
    monkeypatch.setattr(
        ops,
        "resolve_gantt_backfill_trade_dates",
        lambda: ["2026-03-04", "2026-03-05"],
    )
    monkeypatch.setattr(
        ops,
        "sync_xgb_history_for_date",
        lambda trade_date: calls.append(("xgb", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "sync_jygs_action_for_date",
        lambda trade_date: calls.append(("jygs", trade_date))
        or {"trade_date": trade_date},
    )
    monkeypatch.setattr(
        ops,
        "persist_plate_reason_daily_for_date",
        lambda trade_date: calls.append(("plate_reason", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "persist_gantt_daily_for_date",
        lambda trade_date: calls.append(("gantt", trade_date))
        or {"trade_date": trade_date},
    )
    monkeypatch.setattr(
        ops,
        "persist_stock_hot_reason_daily_for_date",
        lambda trade_date: calls.append(("stock_hot_reason", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "refresh_quality_stock_universe",
        lambda: calls.append(("quality_stock_universe",)) or {"count": 2},
    )
    monkeypatch.setattr(
        ops,
        "persist_shouban30_for_date",
        lambda trade_date, stock_window_days=30, chanlun_result_cache=None: calls.append(
            ("shouban30", trade_date, stock_window_days)
        )
        or {"as_of_date": trade_date},
    )

    assert ops.run_gantt_backfill(context) == ["2026-03-04", "2026-03-05"]
    assert calls == [
        ("xgb", "2026-03-04"),
        ("jygs", "2026-03-04"),
        ("plate_reason", "2026-03-04"),
        ("gantt", "2026-03-04"),
        ("stock_hot_reason", "2026-03-04"),
        ("quality_stock_universe",),
        ("shouban30", "2026-03-04", 30),
        ("shouban30", "2026-03-04", 45),
        ("shouban30", "2026-03-04", 60),
        ("shouban30", "2026-03-04", 90),
        ("xgb", "2026-03-05"),
        ("jygs", "2026-03-05"),
        ("plate_reason", "2026-03-05"),
        ("gantt", "2026-03-05"),
        ("stock_hot_reason", "2026-03-05"),
        ("quality_stock_universe",),
        ("shouban30", "2026-03-05", 30),
        ("shouban30", "2026-03-05", 45),
        ("shouban30", "2026-03-05", 60),
        ("shouban30", "2026-03-05", 90),
    ]


def test_run_gantt_backfill_stops_on_first_failed_trade_date(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    calls = []

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(
        ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-03"
    )
    monkeypatch.setattr(
        ops,
        "resolve_gantt_backfill_trade_dates",
        lambda: ["2026-03-04", "2026-03-05", "2026-03-06"],
    )
    monkeypatch.setattr(
        ops,
        "sync_xgb_history_for_date",
        lambda trade_date: calls.append(("xgb", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "sync_jygs_action_for_date",
        lambda trade_date: calls.append(("jygs", trade_date))
        or {"trade_date": trade_date},
    )
    monkeypatch.setattr(
        ops,
        "persist_plate_reason_daily_for_date",
        lambda trade_date: calls.append(("plate_reason", trade_date)) or 1,
    )

    def _persist_gantt(trade_date):
        calls.append(("gantt", trade_date))
        if trade_date == "2026-03-05":
            raise RuntimeError("boom")
        return {"trade_date": trade_date}

    monkeypatch.setattr(ops, "persist_gantt_daily_for_date", _persist_gantt)
    monkeypatch.setattr(
        ops,
        "persist_stock_hot_reason_daily_for_date",
        lambda trade_date: calls.append(("stock_hot_reason", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "refresh_quality_stock_universe",
        lambda: calls.append(("quality_stock_universe",)) or {"count": 2},
    )
    monkeypatch.setattr(
        ops,
        "persist_shouban30_for_date",
        lambda trade_date, stock_window_days=30, chanlun_result_cache=None: calls.append(
            ("shouban30", trade_date, stock_window_days)
        )
        or {"as_of_date": trade_date},
    )

    with pytest.raises(RuntimeError, match="boom"):
        ops.run_gantt_backfill(context)

    assert calls == [
        ("xgb", "2026-03-04"),
        ("jygs", "2026-03-04"),
        ("plate_reason", "2026-03-04"),
        ("gantt", "2026-03-04"),
        ("stock_hot_reason", "2026-03-04"),
        ("quality_stock_universe",),
        ("shouban30", "2026-03-04", 30),
        ("shouban30", "2026-03-04", 45),
        ("shouban30", "2026-03-04", 60),
        ("shouban30", "2026-03-04", 90),
        ("xgb", "2026-03-05"),
        ("jygs", "2026-03-05"),
        ("plate_reason", "2026-03-05"),
        ("gantt", "2026-03-05"),
    ]


def test_op_build_shouban30_daily_builds_all_stock_window_days(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    calls = []

    monkeypatch.setattr(
        ops,
        "persist_shouban30_for_date",
        lambda trade_date, stock_window_days=30, chanlun_result_cache=None: calls.append(
            (trade_date, stock_window_days)
        )
        or {"as_of_date": trade_date, "stock_window_days": stock_window_days},
    )

    result = list(ops.op_build_shouban30_daily(context, "2026-03-05"))
    payload = _collect_output_value(result)

    assert calls == [
        ("2026-03-05", 30),
        ("2026-03-05", 45),
        ("2026-03-05", 60),
        ("2026-03-05", 90),
    ]
    assert payload["trade_date"] == "2026-03-05"
    assert payload["windows"] == [30, 45, 60, 90]


def test_build_shouban30_snapshots_for_date_shares_chanlun_result_cache(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    cache_refs = []

    def persist_shouban30_for_date_stub(
        trade_date, stock_window_days=30, chanlun_result_cache=None
    ):
        cache_refs.append((trade_date, stock_window_days, chanlun_result_cache))
        return {"as_of_date": trade_date, "stock_window_days": stock_window_days}

    monkeypatch.setattr(
        ops, "persist_shouban30_for_date", persist_shouban30_for_date_stub
    )

    result = ops._build_shouban30_snapshots_for_date(context, "2026-03-05")

    assert result["windows"] == [30, 45, 60, 90]
    assert [item[:2] for item in cache_refs] == [
        ("2026-03-05", 30),
        ("2026-03-05", 45),
        ("2026-03-05", 60),
        ("2026-03-05", 90),
    ]
    assert len({id(item[2]) for item in cache_refs}) == 1
    assert isinstance(cache_refs[0][2], dict)


def test_trade_date_sync_ops_use_explicit_input(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    calls = []

    def _unexpected_resolve():
        raise AssertionError("should not resolve latest trade_date")

    monkeypatch.setattr(ops, "_query_latest_trade_date", _unexpected_resolve)
    monkeypatch.setattr(
        ops,
        "sync_xgb_history_for_date",
        lambda trade_date: calls.append(("xgb", trade_date)) or 1,
    )
    monkeypatch.setattr(
        ops,
        "sync_jygs_action_for_date",
        lambda trade_date: calls.append(("jygs", trade_date))
        or {"trade_date": trade_date},
    )

    assert (
        _collect_output_value(
            list(ops.op_sync_xgb_history_for_trade_date(context, "2026-03-05"))
        )
        == "2026-03-05"
    )
    assert (
        _collect_output_value(
            list(ops.op_sync_jygs_action_for_trade_date(context, "2026-03-05"))
        )
        == "2026-03-05"
    )
    assert calls == [("xgb", "2026-03-05"), ("jygs", "2026-03-05")]


def test_op_sync_jygs_action_for_trade_date_requires_result_trade_date(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()

    monkeypatch.setattr(
        ops,
        "sync_jygs_action_for_date",
        lambda trade_date: {},
    )

    with pytest.raises(RuntimeError, match="missing trade_date"):
        list(ops.op_sync_jygs_action_for_trade_date(context, "2026-03-05"))


def test_has_legacy_shouban30_snapshot_detects_missing_chanlun_filter_version(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)

    class FakeCollection:
        def __init__(self, docs):
            self.docs = list(docs)

        def count_documents(self, query):
            return len(self.find(query))

        def distinct(self, field, query):
            return list({doc[field] for doc in self.find(query) if field in doc})

        def find(self, query, projection=None):
            return [
                doc
                for doc in self.docs
                if all(doc.get(key) == value for key, value in query.items())
            ]

    monkeypatch.setattr(
        ops,
        "DBGantt",
        {
            ops.COL_SHOUBAN30_PLATES: FakeCollection(
                [
                    {"as_of_date": "2026-03-05", "stock_window_days": 30},
                    {"as_of_date": "2026-03-05", "stock_window_days": 45},
                    {"as_of_date": "2026-03-05", "stock_window_days": 60},
                    {"as_of_date": "2026-03-05", "stock_window_days": 90},
                ]
            )
        },
    )

    assert ops._has_legacy_shouban30_snapshot("2026-03-05") is True


def test_has_legacy_shouban30_snapshot_detects_mixed_legacy_and_new_rows(monkeypatch):
    ops = _load_ops_module(monkeypatch)

    class FakeCollection:
        def __init__(self, docs):
            self.docs = list(docs)

        def count_documents(self, query):
            return len(self.find(query))

        def distinct(self, field, query):
            return list({doc[field] for doc in self.find(query) if field in doc})

        def find(self, query, projection=None):
            return [
                doc
                for doc in self.docs
                if all(doc.get(key) == value for key, value in query.items())
            ]

    monkeypatch.setattr(
        ops,
        "DBGantt",
        {
            ops.COL_SHOUBAN30_PLATES: FakeCollection(
                [
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 30,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "plate_key": "legacy-missing-fields",
                    },
                ]
            )
        },
    )

    assert ops._has_legacy_shouban30_snapshot("2026-03-05") is True


def test_has_legacy_shouban30_snapshot_detects_missing_extra_filter_stock_fields(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)

    class FakeCollection:
        def __init__(self, docs):
            self.docs = list(docs)

        def find(self, query, projection=None):
            return [
                doc
                for doc in self.docs
                if all(doc.get(key) == value for key, value in query.items())
            ]

    monkeypatch.setattr(
        ops,
        "DBGantt",
        {
            ops.COL_SHOUBAN30_PLATES: FakeCollection(
                [
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 30,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 45,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 60,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 90,
                        "chanlun_filter_version": "30m_v1",
                    },
                ]
            ),
            ops.COL_SHOUBAN30_PLATES.replace("plates", "stocks"): FakeCollection(
                [
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 30,
                        "provider": "xgb",
                        "plate_key": "11",
                        "code6": "000001",
                        "chanlun_filter_version": "30m_v1",
                    }
                ]
            ),
        },
    )

    assert ops._has_legacy_shouban30_snapshot("2026-03-05") is True


def test_has_legacy_shouban30_snapshot_accepts_stock_rows_with_extra_filter_fields(
    monkeypatch,
):
    ops = _load_ops_module(monkeypatch)

    class FakeCollection:
        def __init__(self, docs):
            self.docs = list(docs)

        def find(self, query, projection=None):
            return [
                doc
                for doc in self.docs
                if all(doc.get(key) == value for key, value in query.items())
            ]

    monkeypatch.setattr(
        ops,
        "DBGantt",
        {
            ops.COL_SHOUBAN30_PLATES: FakeCollection(
                [
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 30,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 45,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 60,
                        "chanlun_filter_version": "30m_v1",
                    },
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 90,
                        "chanlun_filter_version": "30m_v1",
                    },
                ]
            ),
            ops.COL_SHOUBAN30_PLATES.replace("plates", "stocks"): FakeCollection(
                [
                    {
                        "as_of_date": "2026-03-05",
                        "stock_window_days": 30,
                        "provider": "xgb",
                        "plate_key": "11",
                        "code6": "000001",
                        "chanlun_filter_version": "30m_v1",
                        "is_credit_subject": False,
                        "credit_subject_snapshot_ready": True,
                        "near_long_term_ma_passed": False,
                        "is_quality_subject": False,
                        "quality_subject_snapshot_ready": False,
                    }
                ]
            ),
        },
    )

    assert ops._has_legacy_shouban30_snapshot("2026-03-05") is False


def test_job_gantt_postclose_uses_multi_op_graph(monkeypatch):
    jobs = _load_jobs_module(monkeypatch)

    node_names = {node.name for node in jobs.job_gantt_postclose.graph.node_defs}

    assert "op_run_gantt_postclose_incremental" not in node_names
    assert "op_resolve_pending_gantt_trade_dates" in node_names
    assert "op_refresh_quality_stock_universe_daily" in node_names


def test_op_resolve_pending_gantt_trade_dates_yields_dynamic_outputs(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()

    monkeypatch.setattr(
        ops,
        "resolve_gantt_backfill_trade_dates",
        lambda: ["2026-03-04", "2026-03-05"],
    )

    result = list(ops.op_resolve_pending_gantt_trade_dates(context))
    outputs = [item for item in result if hasattr(item, "mapping_key")]

    assert [item.value for item in outputs] == ["2026-03-04", "2026-03-05"]
    assert [item.mapping_key for item in outputs] == ["2026_03_04", "2026_03_05"]


def test_job_gantt_postclose_daily_pipeline_dependencies(monkeypatch):
    jobs = _load_jobs_module(monkeypatch)

    dependency_map = jobs.job_gantt_postclose.graph.dependency_map

    assert dependency_map["op_sync_xgb_history_for_trade_date"] == {
        "op_resolve_pending_gantt_trade_dates"
    }
    assert dependency_map["op_sync_jygs_action_for_trade_date"] == {
        "op_resolve_pending_gantt_trade_dates"
    }
    assert dependency_map["op_build_plate_reason_daily"] == {
        "op_sync_xgb_history_for_trade_date",
        "op_sync_jygs_action_for_trade_date",
    }
    assert dependency_map["op_build_gantt_daily"] == {"op_build_plate_reason_daily"}
    assert dependency_map["op_build_stock_hot_reason_daily"] == {"op_build_gantt_daily"}
    assert dependency_map["op_refresh_quality_stock_universe_daily"] == {
        "op_build_stock_hot_reason_daily"
    }
    assert dependency_map["op_build_shouban30_daily"] == {
        "op_refresh_quality_stock_universe_daily"
    }


def test_op_refresh_quality_stock_universe_daily_calls_refresh_once(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()
    calls = []

    def refresh_stub():
        calls.append("called")
        return {"count": 2, "source_version": "xgt_hot_blocks_v1"}

    monkeypatch.setattr(ops, "refresh_quality_stock_universe", refresh_stub)

    result = list(ops.op_refresh_quality_stock_universe_daily(context, "2026-03-09"))

    assert _collect_output_value(result) == "2026-03-09"
    assert calls == ["called"]


def test_op_resolve_pending_gantt_trade_dates_logs_pending_summary(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()

    monkeypatch.setattr(
        ops,
        "resolve_gantt_backfill_trade_dates",
        lambda: ["2026-03-04", "2026-03-05"],
    )

    result = list(ops.op_resolve_pending_gantt_trade_dates(context))
    outputs = [item for item in result if hasattr(item, "mapping_key")]
    messages = _collect_messages(result)

    assert [item.value for item in outputs] == ["2026-03-04", "2026-03-05"]
    assert any(
        "gantt postclose event=done stage=resolve_pending_trade_dates pending_count=2 trade_dates=2026-03-04,2026-03-05"
        in message
        for message in messages
    )


def test_op_sync_xgb_history_for_trade_date_logs_stage_start_and_done(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()

    monkeypatch.setattr(ops, "sync_xgb_history_for_date", lambda trade_date: 12)

    result = list(ops.op_sync_xgb_history_for_trade_date(context, "2026-03-05"))
    messages = _collect_messages(result)

    assert _collect_output_value(result) == "2026-03-05"
    assert any(
        "gantt postclose event=start stage=sync_xgb_history trade_date=2026-03-05"
        in message
        for message in messages
    )
    assert any(
        "gantt postclose event=done stage=sync_xgb_history trade_date=2026-03-05 rows=12"
        in message
        for message in messages
    )


def test_op_build_shouban30_daily_logs_window_progress_and_summary(monkeypatch):
    ops = _load_ops_module(monkeypatch)
    context = _build_context()

    monkeypatch.setattr(
        ops,
        "persist_shouban30_for_date",
        lambda trade_date, stock_window_days=30, chanlun_result_cache=None: {
            "as_of_date": trade_date,
            "plates": stock_window_days // 15,
            "stocks": stock_window_days,
            "stock_window_days": stock_window_days,
        },
    )

    result = list(ops.op_build_shouban30_daily(context, "2026-03-05"))
    messages = _collect_messages(result)
    payload = _collect_output_value(result)

    assert payload["trade_date"] == "2026-03-05"
    assert any(
        "gantt postclose event=start stage=build_shouban30 trade_date=2026-03-05"
        in message
        for message in messages
    )
    assert any(
        "gantt postclose event=progress stage=build_shouban30 trade_date=2026-03-05 stock_window_days=30 status=start"
        in message
        for message in messages
    )
    assert any(
        "gantt postclose event=progress stage=build_shouban30 trade_date=2026-03-05 stock_window_days=90 status=done plates=6 stocks=90"
        in message
        for message in messages
    )
    assert any(
        "gantt postclose event=done stage=build_shouban30 trade_date=2026-03-05 windows=30,45,60,90"
        in message
        for message in messages
    )
