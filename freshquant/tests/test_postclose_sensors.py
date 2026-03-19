from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _build_dagster_stub():
    module = ModuleType("dagster")

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

    module.RunRequest = RunRequest
    module.SkipReason = SkipReason
    module.sensor = sensor
    return module


def _import_sensor_module(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    monkeypatch.setitem(sys.modules, "dagster", _build_dagster_stub())
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.jobs.gantt",
        SimpleNamespace(job_gantt_postclose=SimpleNamespace(name="job_gantt_postclose")),
    )
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.jobs.daily_screening",
        SimpleNamespace(
            daily_screening_postclose_job=SimpleNamespace(
                name="daily_screening_postclose_job"
            )
        ),
    )
    sys.modules.pop("fqdagster.defs.sensors.postclose", None)
    return importlib.import_module("fqdagster.defs.sensors.postclose")


def test_gantt_postclose_sensor_skips_without_stock_ready(monkeypatch):
    module = _import_sensor_module(monkeypatch)

    monkeypatch.setattr(module, "resolve_latest_completed_trade_date", lambda: "2026-03-19")
    monkeypatch.setattr(
        module,
        "has_success_postclose_marker",
        lambda pipeline_key, trade_date: False,
    )

    result = module.gantt_postclose_sensor(SimpleNamespace())

    assert result.skip_message == "stock_postclose_ready missing for 2026-03-19"


def test_gantt_postclose_sensor_triggers_with_pending_trade_date(monkeypatch):
    module = _import_sensor_module(monkeypatch)

    marker_lookup = {
        ("stock_postclose_ready", "2026-03-19"): True,
        ("gantt_postclose_ready", "2026-03-19"): False,
    }
    monkeypatch.setattr(module, "resolve_latest_completed_trade_date", lambda: "2026-03-19")
    monkeypatch.setattr(
        module,
        "has_success_postclose_marker",
        lambda pipeline_key, trade_date: marker_lookup.get((pipeline_key, trade_date), False),
    )

    result = module.gantt_postclose_sensor(SimpleNamespace())

    assert result.run_key == "gantt-postclose:2026-03-19"
    assert result.tags == {"fq_trade_date": "2026-03-19"}


def test_daily_screening_postclose_sensor_skips_without_gantt_ready(monkeypatch):
    module = _import_sensor_module(monkeypatch)

    marker_lookup = {
        ("stock_postclose_ready", "2026-03-19"): True,
        ("gantt_postclose_ready", "2026-03-19"): False,
    }
    monkeypatch.setattr(module, "resolve_latest_completed_trade_date", lambda: "2026-03-19")
    monkeypatch.setattr(
        module,
        "has_success_postclose_marker",
        lambda pipeline_key, trade_date: marker_lookup.get((pipeline_key, trade_date), False),
    )

    result = module.daily_screening_postclose_sensor(SimpleNamespace())

    assert result.skip_message == "gantt_postclose_ready missing for 2026-03-19"


def test_daily_screening_postclose_sensor_triggers_with_trade_date_tag(monkeypatch):
    module = _import_sensor_module(monkeypatch)

    marker_lookup = {
        ("stock_postclose_ready", "2026-03-19"): True,
        ("gantt_postclose_ready", "2026-03-19"): True,
        ("daily_screening_ready", "2026-03-19"): False,
    }
    monkeypatch.setattr(module, "resolve_latest_completed_trade_date", lambda: "2026-03-19")
    monkeypatch.setattr(
        module,
        "has_success_postclose_marker",
        lambda pipeline_key, trade_date: marker_lookup.get((pipeline_key, trade_date), False),
    )

    result = module.daily_screening_postclose_sensor(SimpleNamespace())

    assert result.run_key == "daily-screening-postclose:2026-03-19"
    assert result.tags == {"fq_trade_date": "2026-03-19"}


def test_daily_screening_postclose_sensor_skips_when_marker_already_exists(monkeypatch):
    module = _import_sensor_module(monkeypatch)

    marker_lookup = {
        ("stock_postclose_ready", "2026-03-19"): True,
        ("gantt_postclose_ready", "2026-03-19"): True,
        ("daily_screening_ready", "2026-03-19"): True,
    }
    monkeypatch.setattr(module, "resolve_latest_completed_trade_date", lambda: "2026-03-19")
    monkeypatch.setattr(
        module,
        "has_success_postclose_marker",
        lambda pipeline_key, trade_date: marker_lookup.get((pipeline_key, trade_date), False),
    )

    result = module.daily_screening_postclose_sensor(SimpleNamespace())

    assert result.skip_message == "daily_screening_ready already exists for 2026-03-19"
