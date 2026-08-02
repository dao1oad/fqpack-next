from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def dagster_sensor_stub():
    module = ModuleType("dagster")

    class RunRequest:
        def __init__(self, run_key=None, run_config=None, tags=None):
            self.run_key = run_key
            self.run_config = run_config or {}
            self.tags = tags or {}

    class SkipReason:
        def __init__(self, skip_message):
            self.skip_message = skip_message

    class SensorDefinition:
        def __init__(self, fn, **kwargs):
            self.fn = fn
            self.job = kwargs.get("job")

        def __call__(self, *args, **kwargs):
            return self.fn(*args, **kwargs)

    def sensor(fn=None, **kwargs):
        if fn is None:
            return lambda inner: SensorDefinition(inner, **kwargs)
        return SensorDefinition(fn, **kwargs)

    module.RunRequest = RunRequest
    module.SkipReason = SkipReason
    module.sensor = sensor
    return module


def import_sensor_module(monkeypatch):
    src = Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    monkeypatch.syspath_prepend(str(src))
    monkeypatch.setitem(sys.modules, "dagster", dagster_sensor_stub())
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.jobs.gantt",
        SimpleNamespace(job_gantt_postclose=SimpleNamespace(name="gantt")),
    )
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.jobs.daily_screening",
        SimpleNamespace(daily_screening_postclose_job=SimpleNamespace(name="daily")),
    )
    monkeypatch.setitem(
        sys.modules,
        "fqdagster.defs.jobs.clx_daily_selection",
        SimpleNamespace(
            clx_daily_selection_partition_job=SimpleNamespace(name="partition"),
            clx_daily_selection_finalize_job=SimpleNamespace(name="finalize"),
        ),
    )
    for name in (
        "fqdagster.defs.sensors",
        "fqdagster.defs.sensors.postclose",
        "fqdagster.defs.sensors.clx_daily_selection",
    ):
        sys.modules.pop(name, None)
    return importlib.import_module("fqdagster.defs.sensors.clx_daily_selection")


def test_stock_sensor_starts_from_stock_marker_without_reading_etf(monkeypatch):
    module = import_sensor_module(monkeypatch)
    marker_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: (
            marker_calls.append((pipeline_key, trade_date))
            or {
                "pipeline_key": pipeline_key,
                "trade_date": trade_date,
                "status": "success",
            }
        ),
    )
    service = SimpleNamespace(
        plan_partition=lambda asset_type, _marker: {
            "action": "run",
            "run_key": "stock-attempt-1",
            "attempt_id": "attempt-stock-1",
            "attempt_no": 1,
            "selection_key": "selection-stock",
            "marker_snapshot_hash": "hash-stock",
        }
    )
    monkeypatch.setattr(module, "_make_service", lambda: service)

    result = module.clx_daily_selection_stock_sensor(SimpleNamespace())

    assert result.run_key == "stock-attempt-1"
    assert result.tags["fq_clx_asset_type"] == "stock"
    assert marker_calls == [("stock_postclose_ready", "2026-03-19")]


def test_etf_sensor_uses_independent_retry_attempt(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: {
            "pipeline_key": pipeline_key,
            "trade_date": trade_date,
            "status": "success",
        },
    )
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(
            plan_partition=lambda asset_type, _marker: {
                "action": "run",
                "run_key": "etf-attempt-2",
                "attempt_id": "attempt-etf-2",
                "attempt_no": 2,
                "selection_key": "selection-etf",
                "marker_snapshot_hash": "hash-etf",
            }
        ),
    )

    result = module.clx_daily_selection_etf_sensor(SimpleNamespace())

    assert result.run_key == "etf-attempt-2"
    assert result.tags["fq_clx_attempt_no"] == "2"
    assert result.tags["fq_clx_asset_type"] == "etf"


def test_partition_sensor_skips_completed_side(monkeypatch):
    module = import_sensor_module(monkeypatch)
    plan_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-20", "2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: {
            "pipeline_key": pipeline_key,
            "trade_date": trade_date,
            "status": "success",
        },
    )
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(
            plan_partition=lambda _asset, marker: (
                plan_calls.append(marker["trade_date"]) or {"action": "reuse"}
            )
        ),
    )

    result = module.clx_daily_selection_stock_sensor(SimpleNamespace())

    assert "already completed" in result.skip_message
    assert plan_calls == ["2026-03-20", "2026-03-19"]


def test_finalizer_sensor_waits_for_both_partitions(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(
            plan_finalization=lambda *_args: {
                "action": "wait",
                "partitions": {
                    "stock": {"status": "completed"},
                    "etf": {"status": "running"},
                },
            }
        ),
    )

    result = module.clx_daily_selection_finalizer_sensor(SimpleNamespace())

    assert result.skip_message.endswith("stock=completed, etf=running")


def test_finalizer_sensor_skips_active_publication_claim(monkeypatch):
    module = import_sensor_module(monkeypatch)
    plan_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-19", "2026-03-18"],
    )
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(
            plan_finalization=lambda trade_date, *_args: (
                plan_calls.append(trade_date)
                or {
                    "action": "active",
                    "publication_status": "publishing",
                }
            )
        ),
    )

    result = module.clx_daily_selection_finalizer_sensor(SimpleNamespace())

    assert result.skip_message == (
        "CLX final batch publication already active for 2026-03-19"
    )
    assert plan_calls == ["2026-03-19"]


def test_finalizer_sensor_dispatches_once_both_partitions_are_immutable(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(
            plan_finalization=lambda *_args: {
                "action": "run",
                "run_key": "finalize-hash",
                "batch_id": "clx-2026-03-19-production_v1",
                "partition_ids": ["stock-p", "etf-p"],
                "finalization_attempt_id": "finalize-attempt-1",
                "finalization_attempt_no": 1,
            }
        ),
    )

    result = module.clx_daily_selection_finalizer_sensor(SimpleNamespace())

    assert result.run_key == "finalize-hash"
    assert result.tags["fq_clx_partition_ids"] == "stock-p,etf-p"
    assert result.tags["fq_clx_finalization_attempt_id"] == "finalize-attempt-1"


def test_partition_sensor_catches_up_delayed_old_marker_with_attempt_two(monkeypatch):
    module = import_sensor_module(monkeypatch)
    marker_calls = []
    plan_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-20", "2026-03-19"],
    )

    def get_marker(pipeline_key, trade_date):
        marker_calls.append((pipeline_key, trade_date))
        if trade_date == "2026-03-20":
            return None
        return {
            "pipeline_key": pipeline_key,
            "trade_date": trade_date,
            "status": "success",
        }

    def plan_partition(asset_type, marker):
        plan_calls.append((asset_type, marker["trade_date"]))
        return {
            "action": "run",
            "run_key": "stock-2026-03-19-attempt-2",
            "attempt_id": "attempt-stock-old-2",
            "attempt_no": 2,
            "selection_key": "selection-stock-old",
            "marker_snapshot_hash": "hash-stock-old",
        }

    monkeypatch.setattr(module, "get_postclose_marker", get_marker)
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(plan_partition=plan_partition),
    )

    result = module.clx_daily_selection_stock_sensor(SimpleNamespace())

    assert result.tags["fq_trade_date"] == "2026-03-19"
    assert result.tags["fq_clx_attempt_no"] == "2"
    assert marker_calls == [
        ("stock_postclose_ready", "2026-03-20"),
        ("stock_postclose_ready", "2026-03-19"),
    ]
    assert plan_calls == [("stock", "2026-03-19")]


def test_partition_sensor_stops_when_newest_day_attempt_is_active(monkeypatch):
    module = import_sensor_module(monkeypatch)
    plan_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-20", "2026-03-19"],
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: {
            "pipeline_key": pipeline_key,
            "trade_date": trade_date,
            "status": "success",
        },
    )

    def plan_partition(_asset_type, marker):
        plan_calls.append(marker["trade_date"])
        return {"action": "active"}

    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(plan_partition=plan_partition),
    )

    result = module.clx_daily_selection_stock_sensor(SimpleNamespace())

    assert "already active for 2026-03-20" in result.skip_message
    assert plan_calls == ["2026-03-20"]


def test_finalizer_sensor_catches_up_old_publication_retry_newest_first(monkeypatch):
    module = import_sensor_module(monkeypatch)
    plan_calls = []
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-03-20", "2026-03-19", "2026-03-18", "2026-03-17"],
    )

    def plan_finalization(trade_date, _marker_provider):
        plan_calls.append(trade_date)
        if trade_date == "2026-03-20":
            return {"action": "reuse"}
        if trade_date == "2026-03-19":
            return {
                "action": "wait",
                "partitions": {
                    "stock": {"status": "completed"},
                    "etf": {"status": "waiting"},
                },
            }
        return {
            "action": "run",
            "run_key": "finalize-old-publish-attempt-2",
            "batch_id": "batch-old",
            "partition_ids": ["stock-old", "etf-old"],
            "finalization_attempt_id": "finalize-old-attempt-2",
            "finalization_attempt_no": 2,
            "publication_status": "failed",
        }

    monkeypatch.setattr(
        module,
        "_make_service",
        lambda: SimpleNamespace(plan_finalization=plan_finalization),
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: (pipeline_key, trade_date),
    )

    result = module.clx_daily_selection_finalizer_sensor(SimpleNamespace())

    assert result.run_key == "finalize-old-publish-attempt-2"
    assert result.tags["fq_trade_date"] == "2026-03-18"
    assert result.tags["fq_clx_finalization_attempt_no"] == "2"
    assert plan_calls == ["2026-03-20", "2026-03-19", "2026-03-18"]


def dagster_job_stub():
    module = ModuleType("dagster")

    class Failure(Exception):
        pass

    def op(fn=None, **_kwargs):
        return fn if fn is not None else lambda inner: inner

    def job(fn=None, **_kwargs):
        return fn if fn is not None else lambda inner: inner

    module.Failure = Failure
    module.op = op
    module.job = job
    return module


def import_job_module(monkeypatch):
    src = Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    monkeypatch.syspath_prepend(str(src))
    monkeypatch.setitem(sys.modules, "dagster", dagster_job_stub())
    sys.modules.pop("fqdagster.defs.jobs.clx_daily_selection", None)
    return importlib.import_module("fqdagster.defs.jobs.clx_daily_selection")


def test_partition_job_turns_upstream_drift_into_failed_dagster_run(monkeypatch):
    module = import_job_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda **_kwargs: SimpleNamespace(
            execute_partition=lambda _attempt, _marker_provider, **_kwargs: {
                "status": "upstream_drift"
            }
        ),
    )
    context = SimpleNamespace(
        run=SimpleNamespace(
            tags={
                "fq_clx_asset_type": "stock",
                "fq_clx_attempt_id": "attempt-1",
                "fq_trade_date": "2026-03-19",
            }
        )
    )

    with pytest.raises(module.Failure, match="upstream_drift"):
        module.clx_daily_selection_partition_op(context)


def test_finalizer_job_uses_persisted_attempt_and_exact_planned_tags(monkeypatch):
    module = import_job_module(monkeypatch)
    calls = {}

    class Service:
        def execute_finalization(
            self,
            finalization_attempt_id,
            marker_provider,
            *,
            claim_owner,
            expected_trade_date,
            expected_batch_id,
            expected_partition_ids,
        ):
            calls.update(
                {
                    "finalization_attempt_id": finalization_attempt_id,
                    "claim_owner": claim_owner,
                    "expected_trade_date": expected_trade_date,
                    "expected_batch_id": expected_batch_id,
                    "expected_partition_ids": expected_partition_ids,
                    "stock_marker": marker_provider("stock"),
                }
            )
            return {
                "status": "completed",
                "is_final": True,
                "publication": {"status": "published"},
            }

    monkeypatch.setattr(module, "_make_service", lambda **_kwargs: Service())
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: (pipeline_key, trade_date),
    )
    context = SimpleNamespace(
        run_id="dagster-finalizer-run-1",
        run=SimpleNamespace(
            tags={
                "fq_trade_date": "2026-03-19",
                "fq_clx_batch_id": "batch-1",
                "fq_clx_partition_ids": "stock-p,etf-p",
                "fq_clx_finalization_attempt_id": "finalize-attempt-1",
            }
        ),
    )

    result = module.clx_daily_selection_finalize_op(context)

    assert result["publication"]["status"] == "published"
    assert calls == {
        "finalization_attempt_id": "finalize-attempt-1",
        "claim_owner": "dagster-finalizer-run-1",
        "expected_trade_date": "2026-03-19",
        "expected_batch_id": "batch-1",
        "expected_partition_ids": ["stock-p", "etf-p"],
        "stock_marker": ("stock_postclose_ready", "2026-03-19"),
    }
