import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


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


def _load_ops_module(monkeypatch):
    project_src = (
        Path(__file__).resolve().parents[2] / "morningglory" / "fqdagster" / "src"
    )
    monkeypatch.syspath_prepend(str(project_src))
    monkeypatch.setitem(sys.modules, "dagster", _build_dagster_stub())
    sys.modules.pop("fqdagster.defs.ops.gantt", None)
    return importlib.import_module("fqdagster.defs.ops.gantt")


def _build_context():
    return SimpleNamespace(log=SimpleNamespace(info=lambda *args, **kwargs: None))


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

    assert ops.resolve_gantt_backfill_trade_dates() == []


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
        "persist_shouban30_for_date",
        lambda trade_date: calls.append(("shouban30", trade_date))
        or {"as_of_date": trade_date},
    )

    assert ops.run_gantt_backfill(context) == ["2026-03-04", "2026-03-05"]
    assert calls == [
        ("xgb", "2026-03-04"),
        ("jygs", "2026-03-04"),
        ("plate_reason", "2026-03-04"),
        ("gantt", "2026-03-04"),
        ("shouban30", "2026-03-04"),
        ("xgb", "2026-03-05"),
        ("jygs", "2026-03-05"),
        ("plate_reason", "2026-03-05"),
        ("gantt", "2026-03-05"),
        ("shouban30", "2026-03-05"),
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
        "persist_shouban30_for_date",
        lambda trade_date: calls.append(("shouban30", trade_date))
        or {"as_of_date": trade_date},
    )

    with pytest.raises(RuntimeError, match="boom"):
        ops.run_gantt_backfill(context)

    assert calls == [
        ("xgb", "2026-03-04"),
        ("jygs", "2026-03-04"),
        ("plate_reason", "2026-03-04"),
        ("gantt", "2026-03-04"),
        ("shouban30", "2026-03-04"),
        ("xgb", "2026-03-05"),
        ("jygs", "2026-03-05"),
        ("plate_reason", "2026-03-05"),
        ("gantt", "2026-03-05"),
    ]
