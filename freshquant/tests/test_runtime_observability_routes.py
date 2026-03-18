from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask


def test_runtime_components_route(monkeypatch, tmp_path):
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "heartbeat",
                "component": "guardian_strategy",
                "runtime_node": "host:guardian",
                "node": "heartbeat",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/components")

    body = resp.get_json()
    assert resp.status_code == 200
    assert "guardian_strategy" in body["components"]
    assert "broker_gateway" in body["components"]


def test_runtime_traces_and_detail_routes(monkeypatch, tmp_path):
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "component": "guardian_strategy",
                "runtime_node": "host:guardian",
                "node": "receive_signal",
                "ts": "2026-03-09T10:00:00+08:00",
            },
            {
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "request_id": "req_1",
                "component": "order_submit",
                "runtime_node": "host:rear",
                "node": "tracking_create",
                "ts": "2026-03-09T10:00:01+08:00",
            },
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    traces_resp = client.get("/api/runtime/traces")
    detail_resp = client.get("/api/runtime/traces/trc_1")

    traces_body = traces_resp.get_json()
    detail_body = detail_resp.get_json()
    assert traces_resp.status_code == 200
    assert traces_body["traces"][0]["trace_id"] == "trc_1"
    assert traces_body["traces"][0]["trace_kind"] == "guardian_signal"
    assert traces_body["traces"][0]["trace_status"] == "broken"
    assert (
        traces_body["traces"][0]["break_reason"]
        == "missing_downstream_after_order_submit"
    )
    assert traces_body["traces"][0]["entry_component"] == "guardian_strategy"
    assert traces_body["traces"][0]["exit_component"] == "order_submit"
    assert traces_body["traces"][0]["duration_ms"] == 1000
    assert detail_resp.status_code == 200
    assert [step["node"] for step in detail_body["trace"]["steps"]] == [
        "receive_signal",
        "tracking_create",
    ]
    assert detail_body["trace"]["steps"][1]["offset_ms"] == 1000
    assert detail_body["trace"]["steps"][1]["delta_prev_ms"] == 1000


def test_runtime_traces_route_keeps_tracked_events_when_heartbeats_exceed_limit(
    monkeypatch, tmp_path
):
    tz = timezone(timedelta(hours=8))
    base_ts = datetime(2026, 3, 9, 9, 30, tzinfo=tz)
    records = [
        {
            "event_type": "trace_step",
            "trace_id": "trc_heartbeat_window",
            "component": "guardian_strategy",
            "runtime_node": "host:guardian",
            "node": "receive_signal",
            "ts": base_ts.isoformat(),
        },
        {
            "event_type": "trace_step",
            "trace_id": "trc_heartbeat_window",
            "request_id": "req_heartbeat_window",
            "component": "order_submit",
            "runtime_node": "host:rear",
            "node": "tracking_create",
            "ts": (base_ts + timedelta(seconds=1)).isoformat(),
        },
    ]
    records.extend(
        {
            "event_type": "heartbeat",
            "component": "xt_consumer",
            "runtime_node": "host:xt_consumer",
            "node": "heartbeat",
            "status": "info",
            "ts": (base_ts + timedelta(seconds=10 + index)).isoformat(),
        }
        for index in range(2200)
    )
    _write_events(
        tmp_path,
        runtime_node_path="host_mixed",
        component="runtime_mix",
        date="2026-03-09",
        file_name="runtime_mix_2026-03-09_1.jsonl",
        records=records,
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/traces")

    body = resp.get_json()
    assert resp.status_code == 200
    assert [trace["trace_id"] for trace in body["traces"]] == ["trc_heartbeat_window"]


def test_runtime_traces_route_filters_against_full_matched_set(monkeypatch, tmp_path):
    import freshquant.runtime_observability.assembler as assembler

    assembler._lookup_symbol_name_cached.cache_clear()
    monkeypatch.setattr(
        assembler,
        "query_instrument_info",
        lambda symbol: {"name": f"Name-{symbol}"},
    )
    records = [
        {
            "event_type": "trace_step",
            "trace_id": f"trc_fullset_{index:04d}",
            "component": "guardian_strategy",
            "runtime_node": "host:guardian",
            "node": "receive_signal",
            "symbol": "000001",
            "ts": f"2026-03-09T10:{index // 60:02d}:{index % 60:02d}+08:00",
        }
        for index in range(2105)
    ]
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=records,
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/traces?symbol=000001")

    body = resp.get_json()
    assert resp.status_code == 200
    assert len(body["traces"]) == 2105
    assert body["traces"][-1]["trace_id"] == "trc_fullset_0000"


def test_runtime_raw_file_tail_route(monkeypatch, tmp_path):
    _write_events(
        tmp_path,
        runtime_node_path="host_guardian",
        component="guardian_strategy",
        date="2026-03-09",
        file_name="guardian_strategy_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "trace_step",
                "trace_id": "trc_1",
                "component": "guardian_strategy",
                "runtime_node": "host:guardian",
                "node": "receive_signal",
                "ts": "2026-03-09T10:00:00+08:00",
            }
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get(
        "/api/runtime/raw-files/tail?runtime_node=host:guardian"
        "&component=guardian_strategy&date=2026-03-09"
        "&file=guardian_strategy_2026-03-09_1.jsonl"
    )

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["records"][0]["trace_id"] == "trc_1"


def test_runtime_events_route_keeps_xt_component_heartbeats_visible(
    monkeypatch, tmp_path
):
    _write_events(
        tmp_path,
        runtime_node_path="host_xt_producer",
        component="xt_producer",
        date="2026-03-09",
        file_name="xt_producer_2026-03-09_1.jsonl",
        records=[
            {
                "event_type": "trace_step",
                "component": "order_submit",
                "runtime_node": "host:rear",
                "node": "tracking_create",
                "trace_id": "trc_ignore",
                "ts": "2026-03-09T09:59:59+08:00",
            },
            {
                "event_type": "bootstrap",
                "component": "xt_producer",
                "runtime_node": "host:xt_producer",
                "node": "bootstrap",
                "status": "info",
                "ts": "2026-03-09T10:00:00+08:00",
            },
            {
                "event_type": "heartbeat",
                "component": "xt_producer",
                "runtime_node": "host:xt_producer",
                "node": "heartbeat",
                "status": "info",
                "metrics": {"connected": 1, "subscribed_codes": 20},
                "ts": "2026-03-09T10:00:10+08:00",
            },
        ],
    )
    monkeypatch.setenv("FQ_RUNTIME_LOG_DIR", str(tmp_path))
    client = _make_runtime_client()

    resp = client.get("/api/runtime/events?component=xt_producer")

    body = resp.get_json()
    assert resp.status_code == 200
    assert [event["node"] for event in body["events"]] == ["bootstrap", "heartbeat"]
    assert body["events"][-1]["event_type"] == "heartbeat"
    assert body["events"][-1]["metrics"]["connected"] == 1


def _write_events(
    root: Path,
    *,
    runtime_node_path: str,
    component: str,
    date: str,
    file_name: str,
    records: list[dict],
) -> None:
    path = root / runtime_node_path / component / date / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _make_runtime_client():
    from freshquant.rear.runtime.routes import runtime_bp

    app = Flask("test_runtime_routes")
    app.register_blueprint(runtime_bp)
    return app.test_client()
