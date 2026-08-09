from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

QFQ_SNAPSHOT_PAIR = {
    "stock": {
        "active_slot": "a",
        "snapshot_id": "stock-qfq-snapshot-1",
        "factor_asof": "2026-03-19",
    },
    "etf": {
        "active_slot": "b",
        "snapshot_id": "etf-qfq-snapshot-1",
        "factor_asof": "2026-03-19",
    },
}
QFQ_SNAPSHOT_PAIR_HASH = "qfq-pair-hash-1"
EFFECTIVE_UNIVERSE_HASH = "effective-universe-hash-1"
UNIVERSE_ISOLATION_HASH = "universe-isolation-hash-1"


def qfq_plan_fields():
    return {
        "qfq_snapshot_pair": QFQ_SNAPSHOT_PAIR,
        "qfq_snapshot_pair_hash": QFQ_SNAPSHOT_PAIR_HASH,
    }


def partition_plan_fields():
    return {
        **qfq_plan_fields(),
        "effective_universe_hash": EFFECTIVE_UNIVERSE_HASH,
        "universe_isolation_hash": UNIVERSE_ISOLATION_HASH,
    }


def qfq_run_tags():
    return {
        "fq_clx_qfq_snapshot_pair_hash": QFQ_SNAPSHOT_PAIR_HASH,
        "fq_clx_qfq_stock_snapshot_id": "stock-qfq-snapshot-1",
        "fq_clx_qfq_etf_snapshot_id": "etf-qfq-snapshot-1",
    }


def partition_run_tags():
    return {
        **qfq_run_tags(),
        "fq_clx_effective_universe_hash": EFFECTIVE_UNIVERSE_HASH,
        "fq_clx_universe_isolation_hash": UNIVERSE_ISOLATION_HASH,
    }


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

    class SensorResult:
        def __init__(self, run_requests=None, cursor=None):
            self.run_requests = run_requests or []
            self.cursor = cursor

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
    module.SensorResult = SensorResult
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
        "fqdagster.defs.jobs.clx_daily_selection",
        SimpleNamespace(
            clx_daily_selection_partition_job=SimpleNamespace(name="partition"),
            clx_daily_selection_finalize_job=SimpleNamespace(name="finalize"),
            clx_pre_pool_reconcile_job=SimpleNamespace(name="pre_reconcile"),
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
            **partition_plan_fields(),
        }
    )
    monkeypatch.setattr(module, "_make_service", lambda: service)

    result = module.clx_daily_selection_stock_sensor(SimpleNamespace())

    assert result.run_key == "stock-attempt-1"
    assert result.tags["fq_clx_asset_type"] == "stock"
    assert result.tags["fq_clx_qfq_stock_snapshot_id"] == "stock-qfq-snapshot-1"
    assert result.tags["fq_clx_qfq_etf_snapshot_id"] == "etf-qfq-snapshot-1"
    assert result.tags["fq_clx_qfq_snapshot_pair_hash"] == QFQ_SNAPSHOT_PAIR_HASH
    assert result.tags["fq_clx_effective_universe_hash"] == EFFECTIVE_UNIVERSE_HASH
    assert result.tags["fq_clx_universe_isolation_hash"] == UNIVERSE_ISOLATION_HASH
    assert marker_calls == [("stock_postclose_ready", "2026-03-19")]


def _ready_marker(trade_date="2026-08-07", batch_id="clx-b-1"):
    return {
        "pipeline_key": "clx_daily_selection_ready",
        "trade_date": trade_date,
        "status": "success",
        "updated_at": "2026-08-07T20:00:00+08:00",
        "generation_id": batch_id,
        "generation_order": "1",
        "publication_id": "pub-1",
        "payload": {
            "batch_id": batch_id,
            "content_hash": "hash-1",
            "partition_ids": ["p-stock", "p-etf"],
            "generation_id": batch_id,
            "generation_order": "1",
            "publication_id": "pub-1",
        },
    }


def test_pre_pool_reconcile_sensor_dispatches_new_generation_once(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-08-07"],
    )
    monkeypatch.setattr(
        module,
        "get_clx_ready_marker",
        lambda trade_date=None: _ready_marker(),
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: None,
    )

    result = module.clx_pre_pool_reconcile_sensor(SimpleNamespace(cursor=""))

    assert len(result.run_requests) == 1
    run_request = result.run_requests[0]
    assert run_request.run_key == "clx-pre-reconcile:2026-08-07:clx-b-1:pub-1:attempt-1"
    assert run_request.tags["fq_trade_date"] == "2026-08-07"
    assert run_request.tags["fq_clx_batch_id"] == "clx-b-1"
    assert run_request.tags["fq_clx_generation_id"] == "clx-b-1"
    assert run_request.tags["fq_clx_publication_id"] == "pub-1"
    assert run_request.tags["fq_clx_content_hash"] == "hash-1"
    import json

    cursor = json.loads(result.cursor)
    assert cursor["2026-08-07"]["generation_id"] == "clx-b-1"
    assert cursor["2026-08-07"]["attempt"] == 1
    assert cursor["2026-08-07"]["status"] == "requested"

    # 同一 generation 再次触发且仍未完成：应重试（attempt 递增）
    again = module.clx_pre_pool_reconcile_sensor(SimpleNamespace(cursor=result.cursor))
    assert len(again.run_requests) == 1
    assert (
        again.run_requests[0].run_key
        == "clx-pre-reconcile:2026-08-07:clx-b-1:pub-1:attempt-2"
    )


def test_pre_pool_reconcile_sensor_skips_generation_with_done_marker(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-08-07"],
    )
    monkeypatch.setattr(
        module,
        "get_clx_ready_marker",
        lambda trade_date=None: _ready_marker(),
    )
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: {
            "pipeline_key": "clx_pre_pool_reconcile_done",
            "trade_date": trade_date,
            "status": "success",
            "payload": {
                "generation_id": "clx-b-1",
                "publication_id": "pub-1",
            },
        },
    )

    result = module.clx_pre_pool_reconcile_sensor(SimpleNamespace(cursor=""))

    assert getattr(result, "run_requests", None) in (None, [])


def test_pre_pool_reconcile_sensor_skips_without_ready_marker(monkeypatch):
    module = import_sensor_module(monkeypatch)
    monkeypatch.setattr(
        module,
        "resolve_recent_completed_trade_dates",
        lambda limit=5: ["2026-08-07"],
    )
    monkeypatch.setattr(module, "get_clx_ready_marker", lambda trade_date=None: None)

    result = module.clx_pre_pool_reconcile_sensor(SimpleNamespace(cursor=""))

    assert getattr(result, "run_requests", None) in (None, [])


@pytest.mark.parametrize(
    "missing_field", ["effective_universe_hash", "universe_isolation_hash"]
)
def test_partition_sensor_requires_universe_hashes(monkeypatch, missing_field):
    module = import_sensor_module(monkeypatch)
    plan = {
        "action": "run",
        "run_key": "stock-attempt-1",
        "attempt_id": "attempt-stock-1",
        "attempt_no": 1,
        "selection_key": "selection-stock",
        "marker_snapshot_hash": "hash-stock",
        **partition_plan_fields(),
    }
    plan.pop(missing_field)
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
        lambda: SimpleNamespace(plan_partition=lambda *_args: plan),
    )

    with pytest.raises(ValueError, match=missing_field):
        module.clx_daily_selection_stock_sensor(SimpleNamespace())


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
                **partition_plan_fields(),
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
                "generation_order": "v2|20260319|qfq-pair-hash-1|batch-1",
                **qfq_plan_fields(),
            }
        ),
    )

    result = module.clx_daily_selection_finalizer_sensor(SimpleNamespace())

    assert result.run_key == "finalize-hash"
    assert result.tags["fq_clx_partition_ids"] == "stock-p,etf-p"
    assert result.tags["fq_clx_finalization_attempt_id"] == "finalize-attempt-1"
    assert result.tags["fq_clx_generation_order"].startswith("v2|")
    assert result.tags["fq_clx_qfq_etf_snapshot_id"] == "etf-qfq-snapshot-1"


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
            **partition_plan_fields(),
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
            "generation_order": "v2|20260318|qfq-pair-hash-1|batch-old",
            **qfq_plan_fields(),
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


@pytest.mark.parametrize("value", [None, "", "0", "-1", "1.5"])
def test_attempt_number_tags_require_positive_integers(monkeypatch, value):
    module = import_job_module(monkeypatch)

    with pytest.raises(module.Failure, match="positive integer|requires"):
        module._required_positive_int_tag({"attempt_no": value}, "attempt_no")


def test_partition_job_rejects_invalid_attempt_number_before_service_creation(
    monkeypatch,
):
    module = import_job_module(monkeypatch)
    service_calls = []
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda **_kwargs: service_calls.append(True),
    )
    context = SimpleNamespace(
        run=SimpleNamespace(
            tags={
                "fq_clx_asset_type": "stock",
                "fq_clx_attempt_id": "attempt-1",
                "fq_clx_attempt_no": "0",
                "fq_trade_date": "2026-03-19",
                "fq_clx_selection_key": "selection-stock",
                "fq_clx_marker_snapshot_hash": "hash-stock",
                **partition_run_tags(),
            }
        )
    )

    with pytest.raises(module.Failure, match="positive integer"):
        module.clx_daily_selection_partition_op(context)

    assert service_calls == []


@pytest.mark.parametrize(
    "missing_tag",
    ["fq_clx_effective_universe_hash", "fq_clx_universe_isolation_hash"],
)
def test_partition_job_requires_universe_hash_tags_before_service_creation(
    monkeypatch, missing_tag
):
    module = import_job_module(monkeypatch)
    service_calls = []
    monkeypatch.setattr(
        module,
        "_make_service",
        lambda **_kwargs: service_calls.append(True),
    )
    tags = {
        "fq_clx_asset_type": "stock",
        "fq_clx_attempt_id": "attempt-1",
        "fq_clx_attempt_no": "1",
        "fq_trade_date": "2026-03-19",
        "fq_clx_selection_key": "selection-stock",
        "fq_clx_marker_snapshot_hash": "hash-stock",
        **partition_run_tags(),
    }
    tags.pop(missing_tag)
    context = SimpleNamespace(run=SimpleNamespace(tags=tags))

    with pytest.raises(module.Failure, match=missing_tag):
        module.clx_daily_selection_partition_op(context)

    assert service_calls == []


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
                "fq_clx_attempt_no": "1",
                "fq_trade_date": "2026-03-19",
                "fq_clx_selection_key": "selection-stock",
                "fq_clx_marker_snapshot_hash": "hash-stock",
                **partition_run_tags(),
            }
        )
    )

    with pytest.raises(module.Failure, match="upstream_drift"):
        module.clx_daily_selection_partition_op(context)


def test_partition_job_uses_frozen_snapshot_pair_as_expected_fence(monkeypatch):
    module = import_job_module(monkeypatch)
    calls = {}

    class Service:
        def execute_partition(
            self,
            attempt_id,
            marker_provider,
            **expected,
        ):
            calls.update(
                {
                    "attempt_id": attempt_id,
                    "stock_marker": marker_provider("stock"),
                    **expected,
                }
            )
            return {"status": "completed", "partition": {"partition_id": "p1"}}

    monkeypatch.setattr(module, "_make_service", lambda **_kwargs: Service())
    monkeypatch.setattr(
        module,
        "get_postclose_marker",
        lambda pipeline_key, trade_date: (pipeline_key, trade_date),
    )
    context = SimpleNamespace(
        run_id="dagster-partition-run-1",
        run=SimpleNamespace(
            tags={
                "fq_trade_date": "2026-03-19",
                "fq_clx_asset_type": "stock",
                "fq_clx_attempt_id": "attempt-1",
                "fq_clx_attempt_no": "1",
                "fq_clx_selection_key": "selection-stock",
                "fq_clx_marker_snapshot_hash": "postclose-hash-stock",
                **partition_run_tags(),
            }
        ),
    )

    result = module.clx_daily_selection_partition_op(context)

    assert result["partition"]["partition_id"] == "p1"
    assert calls == {
        "attempt_id": "attempt-1",
        "stock_marker": ("stock_postclose_ready", "2026-03-19"),
        "claim_owner": "dagster-partition-run-1",
        "expected_asset_type": "stock",
        "expected_trade_date": "2026-03-19",
        "expected_attempt_no": 1,
        "expected_selection_key": "selection-stock",
        "expected_marker_snapshot_hash": "postclose-hash-stock",
        "expected_qfq_snapshot_pair_hash": QFQ_SNAPSHOT_PAIR_HASH,
        "expected_qfq_snapshot_ids": {
            "stock": "stock-qfq-snapshot-1",
            "etf": "etf-qfq-snapshot-1",
        },
        "expected_effective_universe_hash": EFFECTIVE_UNIVERSE_HASH,
        "expected_universe_isolation_hash": UNIVERSE_ISOLATION_HASH,
    }


@pytest.mark.parametrize(
    ("tag", "expected_key", "persisted_value"),
    [
        (
            "fq_clx_effective_universe_hash",
            "expected_effective_universe_hash",
            EFFECTIVE_UNIVERSE_HASH,
        ),
        (
            "fq_clx_universe_isolation_hash",
            "expected_universe_isolation_hash",
            UNIVERSE_ISOLATION_HASH,
        ),
    ],
)
def test_partition_job_propagates_universe_hash_mismatch_from_service(
    monkeypatch, tag, expected_key, persisted_value
):
    module = import_job_module(monkeypatch)

    class Service:
        def execute_partition(self, _attempt_id, _marker_provider, **expected):
            if expected[expected_key] != persisted_value:
                raise ValueError(f"{expected_key} mismatch")
            return {"status": "completed"}

    monkeypatch.setattr(module, "_make_service", lambda **_kwargs: Service())
    tags = {
        "fq_trade_date": "2026-03-19",
        "fq_clx_asset_type": "stock",
        "fq_clx_attempt_id": "attempt-1",
        "fq_clx_attempt_no": "1",
        "fq_clx_selection_key": "selection-stock",
        "fq_clx_marker_snapshot_hash": "postclose-hash-stock",
        **partition_run_tags(),
    }
    tags[tag] = "wrong-hash"
    context = SimpleNamespace(run=SimpleNamespace(tags=tags))

    with pytest.raises(ValueError, match=f"{expected_key} mismatch"):
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
            expected_attempt_no,
            expected_partition_ids,
            expected_qfq_snapshot_pair_hash,
            expected_qfq_snapshot_ids,
            expected_generation_order,
        ):
            calls.update(
                {
                    "finalization_attempt_id": finalization_attempt_id,
                    "claim_owner": claim_owner,
                    "expected_trade_date": expected_trade_date,
                    "expected_batch_id": expected_batch_id,
                    "expected_attempt_no": expected_attempt_no,
                    "expected_partition_ids": expected_partition_ids,
                    "expected_qfq_snapshot_pair_hash": (
                        expected_qfq_snapshot_pair_hash
                    ),
                    "expected_qfq_snapshot_ids": expected_qfq_snapshot_ids,
                    "expected_generation_order": expected_generation_order,
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
                "fq_clx_finalization_attempt_no": "1",
                "fq_clx_generation_order": ("v2|20260319|qfq-pair-hash-1|batch-1"),
                **qfq_run_tags(),
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
        "expected_attempt_no": 1,
        "expected_partition_ids": ["stock-p", "etf-p"],
        "expected_qfq_snapshot_pair_hash": QFQ_SNAPSHOT_PAIR_HASH,
        "expected_qfq_snapshot_ids": {
            "stock": "stock-qfq-snapshot-1",
            "etf": "etf-qfq-snapshot-1",
        },
        "expected_generation_order": "v2|20260319|qfq-pair-hash-1|batch-1",
        "stock_marker": ("stock_postclose_ready", "2026-03-19"),
    }
